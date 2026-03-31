terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags { tags = local.tags }
}

# ─────────────────────────────────────────────
# DATA INGESTION — Kinesis Data Stream (on-demand)
# ─────────────────────────────────────────────
resource "aws_kinesis_stream" "transactions" {
  name             = "afld-fraud-transactions"
  stream_mode_details {
    stream_mode = "ON_DEMAND"
  }
  retention_period = 24
}

# ─────────────────────────────────────────────
# IAM — Flink Application Role
# ─────────────────────────────────────────────
resource "aws_iam_role" "flink_role" {
  name = "afld-fraud-flink-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "kinesisanalytics.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "flink_policy" {
  name = "afld-fraud-flink-policy"
  role = aws_iam_role.flink_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:GetRecords", "kinesis:GetShardIterator",
          "kinesis:DescribeStream", "kinesis:ListShards"
        ]
        Resource = aws_kinesis_stream.transactions.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.flink_checkpoints.arn, "${aws_s3_bucket.flink_checkpoints.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogGroups", "logs:DescribeLogStreams"]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.fraud_scorer.arn
      }
    ]
  })
}

# ─────────────────────────────────────────────
# S3 — Flink Checkpoint Storage
# ─────────────────────────────────────────────
resource "aws_s3_bucket" "flink_checkpoints" {
  bucket        = "afld-fraud-flink-checkpoints-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

data "aws_caller_identity" "current" {}

# ─────────────────────────────────────────────
# STATEFUL PROCESSING — Managed Flink Application
# ─────────────────────────────────────────────
resource "aws_kinesisanalyticsv2_application" "fraud_detector" {
  name                   = "afld-fraud-detector"
  runtime_environment    = "FLINK-1_18"
  service_execution_role = aws_iam_role.flink_role.arn

  application_configuration {
    application_code_configuration {
      code_content_type = "PLAINTEXT"
      # Placeholder — replace with your compiled Flink JAR via S3 code_content_s3_location
      code_content {
        text_content = "# Replace with S3 JAR reference"
      }
    }

    flink_application_configuration {
      parallelism_configuration {
        configuration_type = "CUSTOM"
        parallelism        = 2
        parallelism_per_kpu = 1
        auto_scaling_enabled = false
      }

      checkpoint_configuration {
        configuration_type        = "CUSTOM"
        checkpointing_enabled     = true
        checkpoint_interval       = 60000  # 60 seconds in ms
        min_pause_between_checkpoints = 5000
      }

      monitoring_configuration {
        configuration_type = "CUSTOM"
        log_level          = "INFO"
        metrics_level      = "APPLICATION"
      }
    }

  }

  # Kinesis source is wired inside the Flink application code (via KinesisConsumer).
  # The IAM policy above grants the required GetRecords permissions.

  cloudwatch_logging_options {
    log_stream_arn = aws_cloudwatch_log_stream.flink.arn
  }
}

resource "aws_cloudwatch_log_group" "flink" {
  name              = "/aws/kinesisanalytics/afld-fraud-detector"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_stream" "flink" {
  name           = "afld-fraud-detector-stream"
  log_group_name = aws_cloudwatch_log_group.flink.name
}

# ─────────────────────────────────────────────
# IAM — Lambda Fraud Scorer Role
# ─────────────────────────────────────────────
resource "aws_iam_role" "lambda_fraud_role" {
  name = "afld-fraud-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_fraud_policy" {
  name = "afld-fraud-lambda-policy"
  role = aws_iam_role.lambda_fraud_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # On-Demand Bedrock — no Provisioned Throughput ARN needed
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.fraud_alerts.arn
      }
    ]
  })
}

# ─────────────────────────────────────────────
# AI INFERENCE — Lambda + Bedrock (On-Demand)
# ─────────────────────────────────────────────
data "archive_file" "fraud_scorer" {
  type        = "zip"
  output_path = "${path.module}/fraud_scorer.zip"
  source {
    content  = file("${path.module}/../../src/lambdas/fraud_scorer.py")
    filename = "fraud_scorer.py"
  }
}

resource "aws_lambda_function" "fraud_scorer" {
  function_name = "afld-fraud-scorer"
  role          = aws_iam_role.lambda_fraud_role.arn
  handler       = "fraud_scorer.handler"
  runtime       = "python3.12"
  timeout       = 29   # sub-30s for sync invocation from Flink
  memory_size   = 512

  filename         = data.archive_file.fraud_scorer.output_path
  source_code_hash = data.archive_file.fraud_scorer.output_base64sha256

  environment {
    variables = {
      # Use Haiku by default (fastest + cheapest); swap to Sonnet for higher accuracy
      BEDROCK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
      SNS_TOPIC_ARN    = aws_sns_topic.fraud_alerts.arn
      AWS_REGION_NAME  = var.aws_region
    }
  }
}

resource "aws_cloudwatch_log_group" "lambda_fraud" {
  name              = "/aws/lambda/${aws_lambda_function.fraud_scorer.function_name}"
  retention_in_days = 7
}

# ─────────────────────────────────────────────
# ALERTING — SNS Topic + Email Subscription
# ─────────────────────────────────────────────
resource "aws_sns_topic" "fraud_alerts" {
  name = "afld-fraud-alerts"
}

resource "aws_sns_topic_subscription" "email_alert" {
  topic_arn = aws_sns_topic.fraud_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ─────────────────────────────────────────────
# COST GUARDRAIL — CloudWatch Billing Alarm ($15/day)
# AWS billing metrics only exist in us-east-1
# ─────────────────────────────────────────────
provider "aws" {
  alias  = "billing"
  region = "us-east-1"
  default_tags { tags = local.tags }
}

resource "aws_sns_topic" "billing_alert" {
  provider = aws.billing
  name     = "afld-fraud-billing-alert"
}

resource "aws_sns_topic_subscription" "billing_email" {
  provider  = aws.billing
  topic_arn = aws_sns_topic.billing_alert.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "daily_cost_guard" {
  provider = aws.billing

  alarm_name          = "afld-fraud-daily-spend-15usd"
  alarm_description   = "AFLD-Fraud stack estimated daily spend exceeded $15 USD"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 86400  # 24h — billing metrics update ~3x/day
  statistic           = "Maximum"
  threshold           = 15

  dimensions = {
    Currency = "USD"
  }

  alarm_actions = [aws_sns_topic.billing_alert.arn]
  treat_missing_data = "notBreaching"
}

# ─────────────────────────────────────────────
# OPERATIONAL ALARMS
# ─────────────────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "afld-fraud-scorer-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_actions       = [aws_sns_topic.fraud_alerts.arn]
  dimensions = {
    FunctionName = aws_lambda_function.fraud_scorer.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "kinesis_iterator_age" {
  alarm_name          = "afld-fraud-kinesis-iterator-age"
  alarm_description   = "Kinesis iterator age > 30s — processing falling behind"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "GetRecords.IteratorAgeMilliseconds"
  namespace           = "AWS/Kinesis"
  period              = 60
  statistic           = "Maximum"
  threshold           = 30000
  alarm_actions       = [aws_sns_topic.fraud_alerts.arn]
  dimensions = {
    StreamName = aws_kinesis_stream.transactions.name
  }
}
