# AFLD Deployment Guide
## Autonomous Financial Leak Detector — AWS Production Setup

> Target audience: Small & Medium Fintech businesses  
> Stack: Bedrock · Lambda · S3 · SQS · SNS · CloudWatch · Terraform

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| AWS CLI | ≥ 2.x | Auth & resource management |
| Terraform | ≥ 1.5 | Infrastructure provisioning |
| Python | 3.11+ | Lambda runtime |
| uv | latest | Dependency management |

```bash
# Verify all tools
aws --version && terraform --version && python3 --version && uv --version
```

---

## Step 1 — AWS Account Setup

### 1.1 Enable Bedrock Model Access
Claude 3.5 Sonnet must be explicitly enabled in your AWS account.

```
AWS Console → Amazon Bedrock → Model access → Request access
→ Select: Anthropic Claude 3.5 Sonnet
→ Region: us-east-2 (Ohio)
```

> ⚠️ This is a manual step — Terraform cannot automate model access approval.

### 1.2 Configure AWS CLI credentials

```bash
aws configure
# AWS Access Key ID: <your-key>
# AWS Secret Access Key: <your-secret>
# Default region: us-east-2
# Default output format: json
```

Verify access:
```bash
aws sts get-caller-identity
aws bedrock list-foundation-models --region us-east-2 --query 'modelSummaries[?modelId==`anthropic.claude-3-5-sonnet-20240620-v1:0`]'
```

---

## Step 2 — Package the Lambda

The Lambda ZIP must include your source code and dependencies.

```bash
# From project root
pip install boto3 loguru pydantic -t lambda_package/
cp -r src/ lambda_package/
cd lambda_package && zip -r ../infra/lambda_payload.zip . && cd ..
```

Verify the ZIP contains the correct handler path:
```bash
unzip -l infra/lambda_payload.zip | grep auditor_handler
# Expected: src/lambdas/auditor_handler.py
```

---

## Step 3 — Deploy Infrastructure with Terraform

```bash
cd infra

# Initialize providers
terraform init

# Preview what will be created
terraform plan

# Deploy (approx. 2-3 minutes)
terraform apply -auto-approve
```

### What gets created:

| Resource | Name | Purpose |
|----------|------|---------|
| S3 Bucket | `afld-transactions-landing-*` | Incoming transaction files |
| S3 Bucket | `afld-audit-reports-*` | AI-generated audit reports |
| Lambda | `afld-audit-engine-handler` | Core AI analysis engine |
| SNS Topic | `afld-audit-engine-audit-alerts` | Real-time alert broadcast |
| SQS Queue | `afld-audit-engine-alerts-queue` | Alert consumer queue |
| SQS DLQ | `afld-audit-engine-dlq` | Failed event recovery |
| IAM Role | `afld-audit-engine-lambda-role` | Least-privilege permissions |

### Capture outputs:
```bash
terraform output
# Save these values — you'll need them for testing
```

---

## Step 4 — Add CloudWatch Monitoring

Terraform doesn't include CloudWatch yet. Add this to `infra/main.tf`:

```hcl
# CloudWatch Log Group (explicit, with retention)
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.auditor.function_name}"
  retention_in_days = 30
}

# Alarm: Lambda errors > 0 in 5 minutes
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

# Alarm: DLQ has messages (means transactions failed processing)
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
```

Apply the update:
```bash
terraform apply -auto-approve
```

---

## Step 5 — Subscribe to Alerts (Email / Slack)

### Email alerts:
```bash
aws sns subscribe \
  --topic-arn $(terraform output -raw sns_topic_arn) \
  --protocol email \
  --notification-endpoint your-team@company.com \
  --region us-east-2
```
Check your inbox and confirm the subscription.

### Slack alerts (via webhook):
```bash
aws sns subscribe \
  --topic-arn $(terraform output -raw sns_topic_arn) \
  --protocol https \
  --notification-endpoint https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
  --region us-east-2
```

---

## Step 6 — End-to-End Test

### 6.1 Inject a suspicious transaction:
```bash
# Get the landing bucket name
BUCKET=$(cd infra && terraform output -raw s3_landing_bucket)

# Upload a test transaction (fraud scenario)
aws s3 cp data/TX_FRAUD_03.json s3://$BUCKET/TX_FRAUD_03.json
```

### 6.2 Watch Lambda execution in real time:
```bash
FUNCTION=$(cd infra && terraform output -raw lambda_function_name)

aws logs tail /aws/lambda/$FUNCTION --follow --region us-east-2
```

### 6.3 Check the audit report:
```bash
REPORT_BUCKET=$(cd infra && terraform output -raw s3_audit_bucket)

aws s3 ls s3://$REPORT_BUCKET/reports/ --region us-east-2
aws s3 cp s3://$REPORT_BUCKET/reports/<report-id>.json - | python3 -m json.tool
```

### 6.4 Verify SNS alert was published:
```bash
SQS_URL=$(cd infra && terraform output -raw sqs_alerts_queue_url)

aws sqs receive-message --queue-url $SQS_URL --region us-east-2
```

---

## Step 7 — Run the Streamlit Dashboard (Optional)

```bash
# From project root
uv run streamlit run scripts/audit_dashboard.py
# Opens at http://localhost:8501
```

---

## Architecture Flow

```
[Fintech App / Payment Gateway]
         │
         │  PUT transaction JSON
         ▼
  ┌─────────────┐
  │  S3 Landing │  ← afld-transactions-landing-*
  └──────┬──────┘
         │ S3 Event Trigger
         ▼
  ┌─────────────────────┐
  │   Lambda Auditor    │  ← Python 3.12, 512MB, 30s timeout
  │  + Bedrock Claude   │  ← Claude 3.5 Sonnet behavioral analysis
  └──────┬──────────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
  S3 Report  SNS Alert
  (JSON)     │
             ├──→ SQS Alerts Queue  ← your app consumes this
             ├──→ Email / Slack
             └──→ CloudWatch Alarm (on error)
                        │
                        ▼
                   SQS DLQ  ← failed transactions for manual review
```

---

## Business Value for SMB Fintech

| Scenario | Without AFLD | With AFLD |
|----------|-------------|-----------|
| Duplicate charge detection | Manual review, days later | Flagged in < 5 seconds |
| Off-hours transaction spike | Noticed in monthly report | Real-time SNS alert |
| New merchant category anomaly | Missed entirely | Behavioral AI flags it |
| Failed audit trail | Spreadsheets | Immutable S3 JSON reports |
| Compliance evidence | Manual export | Auto-generated per transaction |

**Cost estimate for SMB scale (10K transactions/month):**
- Lambda: ~$0.02
- Bedrock (Claude 3.5 Sonnet): ~$15–25 (input/output tokens)
- S3: ~$0.50
- SNS + SQS: < $1
- **Total: ~$20–30/month** for full AI-powered fraud detection

---

## Teardown

```bash
cd infra && terraform destroy -auto-approve
```

> All S3 buckets have `force_destroy = true` — data will be permanently deleted.
