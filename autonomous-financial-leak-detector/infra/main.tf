# --- Provider Configuration ---
provider "aws" {
  region = "us-east-1"
}

# --- Variables & Locals ---
variable "project_name" {
  default = "afld-audit-engine"
}

resource "random_id" "suffix" {
  byte_length = 4
}

# --- S3 Infrastructure ---
resource "aws_s3_bucket" "landing_zone" {
  bucket        = "afld-transactions-landing-${random_id.suffix.hex}"
  force_destroy = true
}

resource "aws_s3_bucket" "audit_reports" {
  bucket        = "afld-audit-reports-${random_id.suffix.hex}"
  force_destroy = true
}

# --- IAM Role for Lambda ---
resource "aws_iam_role" "lambda_role" {
  name = "${var.project_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}


# --- IAM Policy for Lambda ---
resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.project_name}-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = "bedrock:InvokeModel"
        Effect   = "Allow"
        Resource = "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-*"
      },
      {
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Effect   = "Allow"
        Resource = [
          "${aws_s3_bucket.landing_zone.arn}",
          "${aws_s3_bucket.landing_zone.arn}/*",
          "${aws_s3_bucket.audit_reports.arn}",
          "${aws_s3_bucket.audit_reports.arn}/*"
        ]
      },
      {
        Action   = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# --- Lambda Function ---
resource "aws_lambda_function" "auditor" {
  function_name = "${var.project_name}-handler"
  role          = aws_iam_role.lambda_role.arn
  handler       = "src.lambdas.auditor_handler.handler"
  runtime       = "python3.12"

  filename = "lambda_payload.zip"

  environment {
    variables = {
      AUDIT_REPORT_BUCKET = aws_s3_bucket.audit_reports.id
      MODEL_ID            = "anthropic.claude-3-5-sonnet-20240620-v1:0"
      AWS_REGION_NAME     = "us-east-1"
      SNS_TOPIC_ARN       = aws_sns_topic.audit_alerts.arn
      DLQ_URL             = aws_sqs_queue.dlq.url
    }
  }

  timeout     = 30
  memory_size = 512
}

# --- S3 Trigger ---
resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auditor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.landing_zone.arn
}

resource "aws_s3_bucket_notification" "landing_zone_trigger" {
  bucket = aws_s3_bucket.landing_zone.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.auditor.arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3]
}

# --- Messaging: SNS + SQS + DLQ ---

resource "aws_sns_topic" "audit_alerts" {
  name = "${var.project_name}-audit-alerts"
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.project_name}-dlq"
  message_retention_seconds = 86400
}

resource "aws_sqs_queue" "alerts_queue" {
  name                       = "${var.project_name}-alerts-queue"
  visibility_timeout_seconds = 60
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 2
  })
}

resource "aws_sqs_queue_policy" "alerts_queue_policy" {
  queue_url = aws_sqs_queue.alerts_queue.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.alerts_queue.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.audit_alerts.arn } }
    }]
  })
}

resource "aws_sns_topic_subscription" "sqs_subscription" {
  topic_arn = aws_sns_topic.audit_alerts.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.alerts_queue.arn
}

# DLQ for Lambda async failures (2 retries exhausted)
resource "aws_lambda_function_event_invoke_config" "auditor_async" {
  function_name = aws_lambda_function.auditor.function_name
  maximum_retry_attempts = 1
  destination_config {
    on_failure {
      destination = aws_sqs_queue.dlq.arn
    }
  }
}

# --- IAM additions: SNS publish + SQS send to DLQ ---
resource "aws_iam_role_policy" "lambda_messaging_policy" {
  name = "${var.project_name}-messaging-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = "sns:Publish"
        Effect   = "Allow"
        Resource = aws_sns_topic.audit_alerts.arn
      },
      {
        Action   = "sqs:SendMessage"
        Effect   = "Allow"
        Resource = aws_sqs_queue.dlq.arn
      }
    ]
  })
}

# --- CloudWatch Monitoring ---
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.auditor.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.project_name}-lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Lambda audit engine threw an error"
  alarm_actions       = [aws_sns_topic.audit_alerts.arn]
  dimensions = {
    FunctionName = aws_lambda_function.auditor.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${var.project_name}-dlq-not-empty"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Transactions are failing — check DLQ"
  alarm_actions       = [aws_sns_topic.audit_alerts.arn]
  dimensions = {
    QueueName = aws_sqs_queue.dlq.name
  }
}

# --- Outputs ---
output "sns_topic_arn" {
  value = aws_sns_topic.audit_alerts.arn
}

output "sqs_alerts_queue_url" {
  value = aws_sqs_queue.alerts_queue.url
}

output "sqs_dlq_url" {
  value = aws_sqs_queue.dlq.url
}

# --- Outputs ---
output "s3_landing_bucket" {
  value = aws_s3_bucket.landing_zone.id
}

output "s3_audit_bucket" {
  value = aws_s3_bucket.audit_reports.id
}

output "lambda_function_name" {
  value = aws_lambda_function.auditor.function_name
}
