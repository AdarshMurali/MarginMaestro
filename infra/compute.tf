# Compute: a single EC2 instance running the API + Chroma via Docker Compose,
# with an Elastic IP -- decided 2026-08-27, replacing the ECS Fargate + ALB +
# (would-have-been) NAT Gateway approach applied earlier the same week (see
# docs/ROADMAP.md Phase 10 note). Reasons for the pivot:
#  - The app's URL goes on a resume -- it needs to be reachable at any time,
#    not spun up only for demos, which ruled out tearing the stack down
#    between uses to save cost.
#  - Fargate tasks can never be given a stable outbound IP directly (each
#    task run gets a brand-new ENI); the only way to get one is a NAT
#    Gateway (~$32-40/mo) or NAT instance in front of them. An EC2 instance,
#    by contrast, can have an Elastic IP attached directly -- no NAT
#    anything required -- which Azure SQL's IP-based firewall needs exactly
#    once, permanently.
#  - Dropping the ALB (~$18/mo) and Fargate task billing (~$27/mo) for a
#    single small EC2 instance (~$8-15/mo) cuts the always-on cost by
#    roughly two-thirds, while matching the pattern already used for the
#    user's other project (FinSight_AI: dedicated EC2 + static IP + Azure
#    SQL).
# Chroma runs as a second container on the same box (Docker Compose network,
# not a separate service) -- its /data volume persists to the instance's own
# EBS root volume; no EFS needed for a single instance.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

# ---- Security group ---------------------------------------------------------
# Only the API port is open inbound. No SSH port -- admin access is via SSM
# Session Manager (see the IAM role below), which needs no open inbound port
# and no keypair to manage/lose.

resource "aws_security_group" "app" {
  name        = "marginmaestro-${var.app_env}-app"
  description = "MarginMaestro app instance -- API port only, admin access via SSM"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "API, no custom domain/cert yet"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---- IAM ---------------------------------------------------------------------
# The app fetches its own secrets at startup via config.secrets_manager
# (see settings.py), the same pattern as the earlier ECS task role -- these
# two policies are unchanged, just reattached to an instance profile instead.

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "marginmaestro-${var.app_env}-app"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "app_secrets" {
  role       = aws_iam_role.app.name
  policy_arn = aws_iam_policy.read_secrets.arn
}

resource "aws_iam_role_policy_attachment" "app_documents" {
  role       = aws_iam_role.app.name
  policy_arn = aws_iam_policy.read_write_documents.arn
}

# Enables `aws ssm start-session --target <instance-id>` for remote shell
# access (redeploys, log checks) without any open inbound port.
resource "aws_iam_role_policy_attachment" "app_ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "app" {
  name = "marginmaestro-${var.app_env}-app"
  role = aws_iam_role.app.name
}

# ---- Instance ------------------------------------------------------------

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  # Installs Docker + the Compose plugin, then runs the API + Chroma
  # containers -- API only, per the deploy-scope decision (Kafka/Redpanda
  # and the Event Agent/live-feed-poller consumers stay local-only).
  # Re-running `docker compose pull && docker compose up -d` on the box
  # (via SSM) is how a new image gets picked up after a future CI push --
  # this instance doesn't auto-redeploy on its own.
  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail
    dnf install -y docker
    systemctl enable --now docker
    curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
      -o /usr/libexec/docker/cli-plugins/docker-compose
    chmod +x /usr/libexec/docker/cli-plugins/docker-compose

    mkdir -p /opt/marginmaestro
    cat > /opt/marginmaestro/docker-compose.yml <<'COMPOSE'
    services:
      app:
        image: adarshmurali/marginmaestro:latest
        restart: unless-stopped
        ports:
          - "8000:8000"
        environment:
          APP_ENV: ${var.app_env}
          AWS_REGION: ${var.aws_region}
          CHROMA_HOST: chroma
          CHROMA_PORT: "8000"
        depends_on:
          - chroma

      chroma:
        image: chromadb/chroma:1.5.3
        restart: unless-stopped
        volumes:
          - chroma_data:/data

    volumes:
      chroma_data:
    COMPOSE

    cd /opt/marginmaestro && docker compose up -d
  EOF

  tags = {
    Name = "marginmaestro-${var.app_env}-app"
  }
}

resource "aws_eip" "app" {
  domain   = "vpc"
  instance = aws_instance.app.id
}
