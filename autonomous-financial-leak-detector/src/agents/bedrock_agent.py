import os
import json
import boto3
from loguru import logger
from pydantic import BaseModel

class AuditResult(BaseModel):
    anomaly: bool
    risk_score: float
    reason: str

class FinancialAuditor:
    def __init__(self):
        self.client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION_NAME", "us-east-2"))
        self.model_id = os.environ.get("MODEL_ID", "anthropic.claude-3-5-sonnet-20240620-v1:0")

    def analyze_transaction(self, transaction: dict, context: dict) -> AuditResult:
        prompt = f"""You are a financial fraud detective. Your job is NOT just to flag large amounts — anyone can do that.
Your job is to cross-reference the transaction details against the user's historical profile and find behavioral anomalies.

Look for signals like:
- Transaction category doesn't match the user's typical spending profile
- Unusual hour (e.g. 2-4 AM local time)
- IP geolocation inconsistent with the user's known location
- Device or metadata that doesn't match prior sessions
- Merchant type the user has never transacted with before

User historical profile (provided by MCP context layer):
{json.dumps(context, indent=2)}

Incoming transaction:
{json.dumps(transaction, indent=2)}

Respond with ONLY this JSON — no explanation outside it:
{{"anomaly": true or false, "risk_score": 0.0 to 1.0, "reason": "one specific sentence citing which signals triggered the flag"}}"""

        logger.info(f"Invoking Bedrock model: {self.model_id}")
        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": prompt}]
            }),
            contentType="application/json",
            accept="application/json"
        )

        raw = json.loads(response["body"].read())
        result = json.loads(raw["content"][0]["text"])
        logger.info(f"Bedrock response: {result}")
        return AuditResult(**result)
