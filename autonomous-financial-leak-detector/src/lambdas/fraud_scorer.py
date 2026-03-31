"""
fraud_scorer.py — Lambda handler for real-time fraud scoring via Amazon Bedrock (On-Demand).
Invoked synchronously by Managed Flink or directly via API/test event.
"""
import json
import os
import boto3

MODEL_ID      = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")
REGION        = os.environ.get("AWS_REGION_NAME", "us-east-1")

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
sns     = boto3.client("sns", region_name=REGION)

SYSTEM_PROMPT = (
    "You are a financial fraud detection expert. "
    "Analyze the transaction and respond ONLY with valid JSON: "
    '{"verdict": "FRAUD"|"SUSPICIOUS"|"LEGITIMATE", "confidence": 0.0-1.0, "reason": "<one sentence>"}'
)


def handler(event, context):
    transaction = event if "transaction_id" in event else event.get("body", event)
    if isinstance(transaction, str):
        transaction = json.loads(transaction)

    user_message = (
        f"Analyze this transaction for fraud:\n{json.dumps(transaction, indent=2)}"
    )

    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 256,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}]
        }),
    )

    result = json.loads(response["body"].read())
    analysis = json.loads(result["content"][0]["text"])

    if SNS_TOPIC_ARN and analysis.get("verdict") in ("FRAUD", "SUSPICIOUS"):
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"[AFLD-Fraud] {analysis['verdict']} — tx {transaction.get('transaction_id', 'unknown')}",
            Message=json.dumps({"transaction": transaction, "analysis": analysis}),
        )

    return {"statusCode": 200, "body": json.dumps(analysis)}
