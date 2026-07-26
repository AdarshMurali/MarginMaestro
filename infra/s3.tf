data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "documents" {
  bucket = "marginmaestro-${var.environment}-documents-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "read_write_documents" {
  statement {
    sid    = "ReadWriteMarginMaestroDocuments"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
    ]

    resources = [
      aws_s3_bucket.documents.arn,
      "${aws_s3_bucket.documents.arn}/*",
    ]
  }
}

resource "aws_iam_policy" "read_write_documents" {
  name        = "marginmaestro-${var.environment}-documents"
  description = "Least-privilege read/write access to MarginMaestro's document corpus bucket"
  policy      = data.aws_iam_policy_document.read_write_documents.json
}
