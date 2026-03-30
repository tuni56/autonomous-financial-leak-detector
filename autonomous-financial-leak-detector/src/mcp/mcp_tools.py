import json
import boto3
from loguru import logger

class FinancialMCP:
    def __init__(self):
        self.s3 = boto3.client("s3")

    def get_transaction_from_s3(self, bucket: str, key: str) -> dict:
        logger.info(f"MCP: fetching s3://{bucket}/{key}")
        obj = self.s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read())

    def get_historical_context(self, user_id: str) -> dict:
        # MCP context layer — simulates a Redshift/Athena query on user behavior history
        return {
            "user_id": user_id,
            "location": "La Plata, Argentina",
            "typical_active_hours": "09:00-22:00 ART (UTC-3)",
            "avg_monthly_spend": 850.0,
            "common_categories": ["Software", "Cloud Services", "Restaurants", "Books"],
            "never_purchased": ["Gardening", "Luxury Goods", "Heavy Machinery", "Firearms"],
            "known_devices": ["MacBook Pro - Chrome", "iPhone 14 - Safari"],
            "known_ip_ranges": ["181.x.x.x (Argentina)", "200.x.x.x (Argentina)"],
            "risk_baseline": "low",
            "last_30_days_transactions": 14,
            "flagged_before": False,
        }
