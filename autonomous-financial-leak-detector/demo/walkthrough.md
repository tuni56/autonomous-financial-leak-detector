# AFLD — Demo Walkthrough & Architecture Notes

## Stack
- **Brain:** Claude 3.5 Sonnet via Amazon Bedrock (`anthropic.claude-3-5-sonnet-20240620-v1:0`)
- **Compute:** AWS Lambda Python 3.12
- **Storage:** S3 (landing zone + audit reports)
- **Messaging:** SNS → SQS → DLQ
- **IaC:** Terraform
- **UI:** Streamlit (runs locally)
- **Region:** `us-east-2` (Ohio)

---

## Event Flow

```
S3 upload (pending/*.json)
  └─► Lambda auditor
        ├─► MCP layer — fetches transaction from S3 + user historical profile
        ├─► Bedrock (Claude) — detective reasoning against MCP context
        ├─► S3 audit_reports/reports/*.json — persists report
        ├─► SNS topic audit-alerts — publishes result (always, not just anomalies)
        │     └─► SQS alerts-queue — dashboard reads from here
        └─► [on any failure] → SQS DLQ — Lambda writes directly via sqs.send_message()
```

> **Note on DLQ routing:** S3 triggers Lambda synchronously, so AWS's native async retry/DLQ mechanism doesn't apply here. Instead, the handler explicitly calls `_send_to_dlq()` in every exception branch before returning. This fires immediately on the first failure — no 60s wait.

### Deployed AWS Resources

| Resource | Name |
|---|---|
| Lambda | `afld-audit-engine-handler` |
| S3 landing | `afld-transactions-landing-7f8533d9` |
| S3 reports | `afld-audit-reports-7f8533d9` |
| SNS topic | `afld-audit-engine-audit-alerts` |
| SQS alerts | `afld-audit-engine-alerts-queue` |
| SQS DLQ | `afld-audit-engine-dlq` |

---

## Key Files

```
infra/main.tf                        # All infrastructure (Terraform)
src/agents/bedrock_agent.py          # Bedrock invocation + AuditResult Pydantic model
src/mcp/mcp_tools.py                 # S3 fetch + historical user profile (MCP context layer)
src/lambdas/auditor_handler.py       # Lambda handler — orchestrates everything
scripts/inject_transaction.py        # CLI to inject test transactions
scripts/audit_dashboard.py           # Streamlit dashboard (3 columns)
```

---

## Demo Scenarios

The key insight: **Claude flags behavior, not just amounts.**
The `suspicious` scenario is $200 — pocket change — but it gets flagged because the MCP context layer exposes that the user has never bought gardening tools, is transacting at 3 AM from a Romanian IP on an unknown device.

| Scenario | Amount | Category | IP | Hour (UTC) | Expected verdict |
|---|---|---|---|---|---|
| `normal` | $49.99 | Software | 181.45.23.10 (Argentina) | 15:00 | ✅ CLEARED |
| `suspicious` | $200.00 | Gardening Tools | 45.152.66.201 (Romania) | 06:00 (3 AM ART) | 🚨 FLAGGED |
| `fraud` | $15,000.00 | Luxury Goods | 185.220.101.45 (Tor exit node) | 02:00 | 🚨 FLAGGED |

### MCP Historical Profile (what Claude reasons against)
```json
{
  "location": "La Plata, Argentina",
  "typical_active_hours": "09:00-22:00 ART (UTC-3)",
  "common_categories": ["Software", "Cloud Services", "Restaurants", "Books"],
  "never_purchased": ["Gardening", "Luxury Goods", "Heavy Machinery", "Firearms"],
  "known_ip_ranges": ["181.x.x.x (Argentina)", "200.x.x.x (Argentina)"],
  "known_devices": ["MacBook Pro - Chrome", "iPhone 14 - Safari"]
}
```

Claude's expected reasoning on `suspicious`:
> *"Category 'Gardening Tools' has never appeared in this user's purchase history, the transaction originated from Romania while all known IPs are Argentine, and the 06:00 UTC timestamp corresponds to 3:00 AM local time — outside the user's typical activity window."*

That sentence is the demo. It proves the MCP context layer is doing real work.

---

## Design Decisions

**Detective prompt, not detection prompt**
The Bedrock prompt explicitly tells Claude *not* to flag based on amount alone, and lists the behavioral signals to look for: category mismatch, unusual hour, foreign IP, unknown device. This forces reasoning against the MCP context rather than a simple threshold check.

**`raise` instead of `return 500` in the generic Exception branch**
If Lambda returns a 500, AWS considers the invocation successful and won't retry. Re-raising keeps the door open for future async retry configuration.

**Explicit DLQ write on every failure**
S3 → Lambda is synchronous, so AWS's native async DLQ routing doesn't apply. The handler calls `_send_to_dlq()` directly in every `except` branch. Fires immediately, works regardless of invocation type.

**`json.JSONDecodeError` caught explicitly**
The bad payload (`not-valid-json{{`) raises `JSONDecodeError` which is a subclass of `ValueError`. Both are caught in the same branch and routed to DLQ.

**user_id read from payload, not S3 key**
The S3 key is `pending/<uuid>.json` — `parts[0]` would always be `"pending"`. The actual `user_id` lives inside the JSON payload, fetched first before any other logic.

**S3 trigger filters `pending/*.json`**
`filter_prefix = "pending/"` + `filter_suffix = ".json"`. Both the inject script and the dashboard always upload to `pending/uuid.json`. Uploading to any other path silently skips the trigger.

**SNS publishes on every result, not just anomalies**
Keeps the SQS feed active during the demo for both CLEARED and FLAGGED verdicts.

**Warm starts**
`FinancialAuditor` and `FinancialMCP` are instantiated outside the handler to reuse connections across warm invocations.

---

## Deploy Commands

```bash
# From project root

# 1. Package Lambda
zip -r infra/lambda_payload.zip src/ -x "src/lambdas/demo_app.py"

# 2. Deploy all infrastructure
cd infra && terraform apply -auto-approve

# 3. Launch dashboard (runs locally, no AWS cost)
cd .. && uv run streamlit run scripts/audit_dashboard.py
```

### Redeploy Lambda only (no infra changes)
```bash
zip -r infra/lambda_payload.zip src/ -x "src/lambdas/demo_app.py"
cd infra && terraform apply -target=aws_lambda_function.auditor -auto-approve
```

---

## Demo Script (recommended sequence)

1. Show empty dashboard → "system online, awaiting transactions"
2. Inject **normal** → Refresh → ✅ CLEARED, low risk score across all 3 columns
3. Inject **suspicious** → Refresh → 🚨 FLAGGED at $200 — pause here, read Claude's reasoning out loud
4. Inject **fraud** → Refresh → max risk score, Tor exit node visible in the metadata
5. Click "Inject Bad Payload" → Refresh → failed event appears immediately in DLQ column
6. Expand the JSON of any report to show the full depth of the analysis

**Recording tips:**
- Use `kazam` (`sudo apt install kazam`) or OBS, 1920x1080, capture browser window only
- Run this in a terminal alongside the dashboard to show Lambda logs firing in real time:
  ```bash
  aws logs tail /aws/lambda/afld-audit-engine-handler --follow --region us-east-2
  ```

### What CloudWatch logs look like per transaction

**Happy path:**
```
Processing audit | user=user_rocio_99 | file=pending/abc123.json
MCP: fetching s3://afld-transactions-landing-7f8533d9/pending/abc123.json
Invoking Bedrock model: anthropic.claude-3-5-sonnet-20240620-v1:0
Bedrock response: {"anomaly": true, "risk_score": 0.88, "reason": "..."}
Report saved → reports/xyz.json | status=FLAGGED | risk=0.88
SNS alert published | status=FLAGGED
```

**Bad payload:**
```
MCP: fetching s3://...
Validation error: JSONDecodeError: ...
Event routed to DLQ | reason=JSONDecodeError: ...
```

---

## Teardown — Stop Everything & Avoid Charges

Run this after the demo. Lambda and S3 have no idle cost, but SNS/SQS have a small per-request cost and the KMS key (if still in state) has a $1/month flat fee.

```bash
# 1. Stop the dashboard (Ctrl+C in the terminal running Streamlit)

# 2. Destroy all AWS infrastructure
cd infra && terraform destroy -auto-approve
```

That's it. `terraform destroy` removes Lambda, both S3 buckets (force_destroy=true so objects are deleted too), SNS topic, both SQS queues, IAM role and policies, S3 notification, and Lambda permission.

**Verify nothing is left:**
```bash
# Check no buckets remain
aws s3 ls | grep afld

# Check Lambda is gone
aws lambda get-function --function-name afld-audit-engine-handler --region us-east-2

# Check SQS queues are gone
aws sqs list-queues --queue-name-prefix afld --region us-east-2
```

All three should return empty or a `ResourceNotFoundException`.

**What has zero cost at rest (no need to destroy):**
- IAM roles and policies — always free
- CloudWatch log groups — free unless you're storing GBs of logs; delete manually if needed:
  ```bash
  aws logs delete-log-group --log-group-name /aws/lambda/afld-audit-engine-handler --region us-east-2
  ```

**Bedrock** — pay-per-token only, no idle cost. Nothing to turn off.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Lambda doesn't trigger on upload | Path doesn't match `pending/*.json` filter | Ensure key starts with `pending/` and ends with `.json` |
| `KMSAccessDeniedException` | Lambda configured with custom KMS key without permissions | Remove `kms_key_arn` from `aws_lambda_function` resource |
| SQS empty after publish | SNS has no active subscription to the queue | Check `aws_sns_topic_subscription` and `aws_sqs_queue_policy` |
| DLQ not receiving failed events | `DLQ_URL` env var missing in Lambda | Redeploy after adding `DLQ_URL` to Terraform env vars |
| Bedrock `AccessDeniedException` | Model not enabled in region | Bedrock console → Model access → enable Claude 3.5 Sonnet in us-east-2 |
| Claude flags `normal` transaction | Stale Lambda code (prompt not updated) | Repackage and redeploy Lambda after any code change |
| `user_id` shows as `"pending"` in logs | Reading from S3 key instead of payload | Confirm handler fetches transaction before extracting `user_id` |
