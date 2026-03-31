# Derecho Viejo — Real-Time Fraud Detection Stack

**Project:** AFLD-Fraud | **Owner:** Rocio-Distinguished | **Environment:** Staging-Demo  
**Region:** `us-east-1`

---

## Architecture

```
Transactions
     │
     ▼
Amazon Kinesis Data Stream (ON_DEMAND)
     │
     ▼
Amazon Managed Service for Apache Flink
  • Parallelism: 2  (credit-efficient, no auto-scaling)
  • Checkpointing: every 60s → S3
     │
     ▼
AWS Lambda — fraud_scorer
     │
     ▼
Amazon Bedrock — Claude 3 Haiku (On-Demand)
     │
     ├─ FRAUD / SUSPICIOUS → SNS → Email alert
     └─ LEGITIMATE → return verdict
```

---

## Stack Components

| Resource | Name | Notes |
|---|---|---|
| Kinesis Data Stream | `afld-fraud-transactions` | ON_DEMAND, 24h retention |
| Managed Flink App | `afld-fraud-detector` | Flink 1.18, parallelism=2 |
| Flink Checkpoints S3 | `afld-fraud-flink-checkpoints-<account_id>` | State backup every 60s |
| Lambda | `afld-fraud-scorer` | Python 3.12, 512 MB, 29s timeout |
| Bedrock Model | `claude-3-haiku-20240307-v1:0` | On-Demand, swap via env var |
| SNS Topic | `afld-fraud-alerts` | Fraud/Suspicious verdicts + Lambda errors |
| CloudWatch Alarm | `afld-fraud-daily-spend-15usd` | Triggers if estimated charges > $15/day |
| CloudWatch Alarm | `afld-fraud-scorer-errors` | Lambda error count > 0 |
| CloudWatch Alarm | `afld-fraud-kinesis-iterator-age` | Iterator age > 30s |

---

## Bedrock — On-Demand Strategy

- Default model: **Claude 3 Haiku** — fastest, lowest cost per token, ideal for demo cycle.
- To switch to Sonnet (higher accuracy), update the Lambda env var — no infra change needed:

```bash
aws lambda update-function-configuration \
  --function-name afld-fraud-scorer \
  --environment "Variables={BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0,SNS_TOPIC_ARN=<arn>,AWS_REGION_NAME=us-east-1}"
```

- Provisioned Throughput is **not used** — zero idle cost during demo.

---

## Cost Guardrail

A CloudWatch billing alarm fires when `EstimatedCharges` (USD, 24h window) exceeds **$15**.  
Notification goes to the email set in `terraform.tfvars`.

> Note: AWS billing metrics only exist in `us-east-1`. The stack uses a second aliased provider for this alarm automatically.

---

## Deploy

### Prerequisites

1. Terraform >= 1.5 installed.
2. AWS credentials configured (`aws configure` or env vars).
3. Bedrock model access enabled in the AWS Console:  
   `Bedrock → Model access → Enable: Claude 3 Haiku + Claude 3 Sonnet`

### Steps

```bash
cd infra/fraud_detection

# 1. Configure
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set your alert_email

# 2. Deploy
terraform init
terraform plan
terraform apply
```

After `apply`, confirm the SNS email subscription (check your inbox).

---

## Test the Fraud Endpoint

Invoke the Lambda directly — no API Gateway needed:

```bash
aws lambda invoke \
  --function-name afld-fraud-scorer \
  --payload '{"transaction_id":"TX-001","amount":9999.99,"user_id":"new_user_42","merchant":"UNKNOWN_INTL","country":"XX"}' \
  --cli-binary-format raw-in-base64-out \
  response.json && cat response.json
```

Expected response:

```json
{
  "verdict": "FRAUD",
  "confidence": 0.97,
  "reason": "High-value transaction to unknown international merchant from a new user account."
}
```

---

## Flink JAR (next step)

The Flink application currently has a placeholder for the application code.  
To wire the full streaming pipeline, compile your Flink job and update `main.tf`:

```hcl
code_content {
  s3_content_location {
    bucket_arn = "arn:aws:s3:::your-jar-bucket"
    file_key   = "afld-fraud-detector-1.0.jar"
  }
}
```

The Kinesis source is configured inside the Flink app via `FlinkKinesisConsumer` — IAM permissions are already provisioned.

---

## Region Change Log

| Date | Change |
|---|---|
| 2026-03-31 | Migrated all resources from `us-east-2` → `us-east-1` (Bedrock model availability + billing alarm requirement) |
