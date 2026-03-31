"""
fraud_scorer.py
Lambda handler — Real-Time Fraud Detection via Amazon Bedrock (On-Demand).
Triggered by: Managed Apache Flink (sync) or direct Lambda invocation (test/demo).
"""
import json
import os
import boto3

# ── Config ────────────────────────────────────────────────────────────────────
MODEL_ID      = os.environ["BEDROCK_MODEL_ID"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
REGION        = os.environ["AWS_REGION_NAME"]

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
sns     = boto3.client("sns",             region_name=REGION)

SYSTEM_PROMPT = (
    "You are a financial fraud detection expert. "
    "Analyze the transaction and respond ONLY with valid JSON: "
    '{"verdict": "FRAUD"|"SUSPICIOUS"|"LEGITIMATE", "confidence": 0.0-1.0, "reason": "<one sentence>"}'
)

ALERT_VERDICTS = {"FRAUD", "SUSPICIOUS"}

# ── Handler ───────────────────────────────────────────────────────────────────
def handler(event, _context):
    tx = _parse_transaction(event)

    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 256,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": f"Analyze this transaction for fraud:\n{json.dumps(tx, indent=2)}"}],
        }),
    )

    analysis = json.loads(json.loads(response["body"].read())["content"][0]["text"])

    if analysis.get("verdict") in ALERT_VERDICTS:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"[AFLD-Fraud] {analysis['verdict']} — tx {tx.get('transaction_id', 'unknown')}",
            Message=json.dumps({"transaction": tx, "analysis": analysis}),
        )

    return {"statusCode": 200, "body": json.dumps(analysis)}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _parse_transaction(event: dict) -> dict:
    """Normalise event shape: direct invocation, API GW proxy, or Flink record."""
    if "transaction_id" in event:
        return event
    body = event.get("body", event)
    return json.loads(body) if isinstance(body, str) else body
