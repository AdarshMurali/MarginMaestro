# Compute: ECS Fargate, two services (API + Chroma) behind an ALB, on the
# account's default VPC/subnets (decided MM-102 -- see docs/ROADMAP.md Phase
# 10). Deliberately no NAT Gateway: both tasks run in the default *public*
# subnets with a public IP, since the only outbound-internet need (pulling
# public Docker Hub images, reaching Azure SQL/OpenAI/Slack) doesn't
# otherwise require inbound reachability -- inbound is still locked down by
# security group, not by network placement. Chroma is reachable from the API
# task only, over a private Cloud Map DNS name, never through the ALB.

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

# ---- Cluster + service discovery -------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = "marginmaestro-${var.app_env}"
}

resource "aws_service_discovery_private_dns_namespace" "internal" {
  name = "marginmaestro.internal"
  vpc  = data.aws_vpc.default.id
}

resource "aws_service_discovery_service" "chroma" {
  name = "chroma"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.internal.id

    dns_records {
      type = "A"
      ttl  = 10
    }

    routing_policy = "MULTIVALUE"
  }

  # Enables ECS-managed health checks (task IPs registered/deregistered as
  # tasks start/stop). `failure_threshold`'s value is deprecated/ignored by
  # AWS (always 1) but the block itself is still required for this behavior.
  health_check_custom_config {
    failure_threshold = 1
  }
}

# ---- Security groups --------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "marginmaestro-${var.app_env}-alb"
  description = "Public ingress to the MarginMaestro ALB"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP from anywhere (no custom domain/cert yet)"
    from_port   = 80
    to_port     = 80
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

resource "aws_security_group" "api" {
  name        = "marginmaestro-${var.app_env}-api"
  description = "MarginMaestro API task"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "From the ALB only"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "chroma" {
  name        = "marginmaestro-${var.app_env}-chroma"
  description = "MarginMaestro Chroma task -- reachable from the API task only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "From the API task only"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "efs" {
  name        = "marginmaestro-${var.app_env}-efs"
  description = "EFS mount targets for Chromas persistent /data volume"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "NFS from the Chroma task only"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.chroma.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---- Persistent storage for Chroma ------------------------------------------
# Mirrors docker-compose.yml's `chroma_data:/data` volume -- without this,
# every task restart/redeploy would silently wipe the RAG corpus and require
# re-running ingestion before the CSA-RAG agent works again.

resource "aws_efs_file_system" "chroma_data" {
  creation_token = "marginmaestro-${var.app_env}-chroma-data"
  encrypted      = true
}

resource "aws_efs_mount_target" "chroma_data" {
  for_each = toset(data.aws_subnets.default.ids)

  file_system_id  = aws_efs_file_system.chroma_data.id
  subnet_id       = each.value
  security_groups = [aws_security_group.efs.id]
}

# ---- IAM ---------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/marginmaestro-${var.app_env}-api"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "chroma" {
  name              = "/ecs/marginmaestro-${var.app_env}-chroma"
  retention_in_days = 7
}

# Shared by both tasks -- pulls public Docker Hub images (no ECR auth
# needed) and only needs permission to write the two log groups above.
resource "aws_iam_role" "execution" {
  name               = "marginmaestro-${var.app_env}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
}

data "aws_iam_policy_document" "execution_logs" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "${aws_cloudwatch_log_group.api.arn}:*",
      "${aws_cloudwatch_log_group.chroma.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "execution_logs" {
  name   = "logs"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_logs.json
}

# API task role: the app fetches its own secrets at startup via
# config.secrets_manager.SecretsManagerSource (see settings.py), rather than
# ECS's native secrets-injection -- keeps secrets loading compute-platform
# agnostic, consistent with the existing tested source-loading pattern.
resource "aws_iam_role" "api_task" {
  name               = "marginmaestro-${var.app_env}-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume_role.json
}

resource "aws_iam_role_policy_attachment" "api_task_secrets" {
  role       = aws_iam_role.api_task.name
  policy_arn = aws_iam_policy.read_secrets.arn
}

resource "aws_iam_role_policy_attachment" "api_task_documents" {
  role       = aws_iam_role.api_task.name
  policy_arn = aws_iam_policy.read_write_documents.arn
}

# ---- ALB ----------------------------------------------------------------------

resource "aws_lb" "api" {
  name               = "marginmaestro-${var.app_env}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = data.aws_subnets.default.ids
}

resource "aws_lb_target_group" "api" {
  name        = "marginmaestro-${var.app_env}-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip"

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# ---- Chroma task/service -------------------------------------------------------

resource "aws_ecs_task_definition" "chroma" {
  family                   = "marginmaestro-${var.app_env}-chroma"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn

  volume {
    name = "chroma-data"
    efs_volume_configuration {
      file_system_id = aws_efs_file_system.chroma_data.id
      root_directory = "/"
    }
  }

  container_definitions = jsonencode([
    {
      name      = "chroma"
      image     = "chromadb/chroma:1.5.3"
      essential = true
      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]
      mountPoints = [
        { sourceVolume = "chroma-data", containerPath = "/data" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.chroma.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "chroma"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "chroma" {
  name            = "marginmaestro-${var.app_env}-chroma"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.chroma.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.chroma.id]
    assign_public_ip = true
  }

  service_registries {
    registry_arn = aws_service_discovery_service.chroma.arn
  }

  depends_on = [aws_efs_mount_target.chroma_data]
}

# ---- API task/service -----------------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = "marginmaestro-${var.app_env}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "adarshmurali/marginmaestro:latest"
      essential = true
      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]
      environment = [
        { name = "APP_ENV", value = var.app_env },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "CHROMA_HOST", value = "chroma.${aws_service_discovery_private_dns_namespace.internal.name}" },
        { name = "CHROMA_PORT", value = "8000" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "api" {
  name            = "marginmaestro-${var.app_env}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.api]
}
