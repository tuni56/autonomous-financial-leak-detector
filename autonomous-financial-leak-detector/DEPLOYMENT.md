# AFLD Deployment Guide
## Autonomous Financial Leak Detector — AWS Production Setup

> **Region:** `us-east-1`  
> **Stack A:** AFLD Audit Engine (S3 → Lambda → Bedrock → SNS/SQS)  
> **Stack B:** Derecho Viejo — Real-Time Fraud Detection (Kinesis → Flink → Lambda → Bedrock)

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| AWS CLI | ≥ 2.x | Auth & resource management |
| Terraform | ≥ 1.5 | Infrastructure provisioning |
| Python | 3.11+ | Lambda runtime & scripts |
| uv | latest | Dependency management |

```bash
aws --version && terraform --version && python3 --version && uv --version
```

---

## Step 1 — AWS Account Setup

### 1.1 Enable Bedrock Model Access

```
AWS Console → Amazon Bedrock → Model access → Request access
→ Enable: Claude 3.5 Sonnet  (Audit Engine)
→ Enable: Claude 3 Haiku     (Fraud Scorer — default)
→ Enable: Claude 3 Sonnet    (Fraud Scorer — optional upgrade)
→ Region: us-east-1
```

> ⚠️ Manual step — Terraform cannot automate model access approval.

### 1.2 Configure AWS CLI

```bash
aws configure
# Default region: us-east-1

aws sts get-caller-identity  # verify
```

---

## Stack A — AFLD Audit Engine

### Deploy

```bash
# Package Lambda
pip install boto3 loguru pydantic -t lambda_package/
cp -r src/ lambda_package/
cd lambda_package && zip -r ../infra/lambda_payload.zip . && cd ..

# Deploy
cd infra
terraform init
terraform plan
terraform apply -auto-approve
terraform output
```

### Resources created

| Resource | Name | Purpose |
|----------|------|---------|
| S3 | `afld-transactions-landing-*` | Incoming transaction files |
| S3 | `afld-audit-reports-*` | AI-generated audit reports |
| Lambda | `afld-audit-engine-handler` | Core AI analysis engine |
| SNS | `afld-audit-engine-audit-alerts` | Alert broadcast |
| SQS | `afld-audit-engine-alerts-queue` | Alert consumer queue |
| SQS DLQ | `afld-audit-engine-dlq` | Failed event recovery |
| CloudWatch | Lambda errors + DLQ alarms | Observability |

### Test

```bash
BUCKET=$(cd infra && terraform output -raw s3_landing_bucket)
aws s3 cp data/TX_FRAUD_03.json s3://$BUCKET/TX_FRAUD_03.json

# Watch logs
FUNCTION=$(cd infra && terraform output -raw lambda_function_name)
aws logs tail /aws/lambda/$FUNCTION --follow

# Read report
REPORT_BUCKET=$(cd infra && terraform output -raw s3_audit_bucket)
aws s3 ls s3://$REPORT_BUCKET/reports/
aws s3 cp s3://$REPORT_BUCKET/reports/<report-id>.json - | python3 -m json.tool
```

---

## Stack B — Derecho Viejo (Real-Time Fraud Detection)

### Deploy

```bash
cd infra/fraud_detection
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set alert_email

terraform init
terraform plan
terraform apply -auto-approve
```

Confirm the SNS email subscription (check inbox after apply).

### Resources created

| Resource | Name | Notes |
|----------|------|-------|
| Kinesis | `afld-fraud-transactions` | ON_DEMAND, 24h retention |
| Managed Flink | `afld-fraud-detector` | Flink 1.18, parallelism=2, checkpoint 60s |
| S3 | `afld-fraud-flink-checkpoints-<account>` | Flink state storage |
| Lambda | `afld-fraud-scorer` | Python 3.12, 512MB, Bedrock On-Demand |
| SNS | `afld-fraud-alerts` | FRAUD/SUSPICIOUS verdicts + Lambda errors |
| CloudWatch | 3 alarms | Lambda errors, Kinesis iterator age, $15/day spend |

### Test — direct Lambda invocation

```bash
aws lambda invoke \
  --function-name afld-fraud-scorer \
  --payload '{"transaction_id":"TX-001","amount":9999.99,"user_id":"new_user_42","merchant":"UNKNOWN_INTL","country":"XX"}' \
  --cli-binary-format raw-in-base64-out \
  response.json && cat response.json
```

Expected:
```json
{"verdict": "FRAUD", "confidence": 0.97, "reason": "High-value transaction to unknown international merchant from a new user account."}
```

### Swap Bedrock model (no infra change needed)

```bash
# Upgrade to Sonnet for higher accuracy
aws lambda update-function-configuration \
  --function-name afld-fraud-scorer \
  --environment "Variables={BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0,SNS_TOPIC_ARN=<arn>,AWS_REGION_NAME=us-east-1}"
```

---

## Architecture

```
── Stack A: Audit Engine ──────────────────────────────────────────────

[Fintech App]
     │ PUT transaction.json
     ▼
  S3 Landing ──trigger──▶ Lambda Auditor ──InvokeModel──▶ Bedrock (Claude 3.5 Sonnet)
                                │                                │
                                │◀───────── AuditResult ─────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
               S3 Reports              SNS Alerts ──▶ SQS / Email
                                           │
                                    (on failure) ──▶ SQS DLQ


── Stack B: Derecho Viejo ─────────────────────────────────────────────

[Transaction Producer]
     │ PUT record
     ▼
  Kinesis (ON_DEMAND) ──▶ Managed Flink (p=2, ckpt 60s) ──▶ Lambda fraud_scorer
                                │                                    │
                           S3 Checkpoints              Bedrock (Claude 3 Haiku)
                                                                     │
                                                    FRAUD/SUSPICIOUS ──▶ SNS ──▶ Email
                                                                     │
                                                              CloudWatch Alarms
                                                         (errors · iterator age · $15/day)
```

---

## Cost Estimate (Staging-Demo scale)

| Service | Stack A | Stack B |
|---------|---------|---------|
| Lambda | ~$0.02 | ~$0.02 |
| Bedrock (Haiku/Sonnet) | ~$15–25/mo | ~$5–10/mo |
| S3 | ~$0.50 | ~$0.50 |
| Kinesis ON_DEMAND | — | ~$0.08/GB |
| Managed Flink (2 KPU) | — | ~$0.11/KPU-hr |
| SNS + SQS | < $1 | < $1 |

Cost alarm fires at **$15/day** for Stack B.

---

## Optional — Streamlit Dashboard

```bash
uv run streamlit run scripts/audit_dashboard.py
# http://localhost:8501
```

---

## Teardown

```bash
# Stack A
cd infra && terraform destroy -auto-approve

# Stack B
cd infra/fraud_detection && terraform destroy -auto-approve
```

> Both stacks use `force_destroy = true` on S3 — all data will be permanently deleted.
