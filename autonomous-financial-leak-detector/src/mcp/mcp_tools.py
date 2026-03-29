import boto3
from loguru import logger

class FinancialMCP:
    def __init__(self):
        self.s3 = boto3.client('s3')

    def fetch_transaction_context(self, bucket: str, key: str):
        """Simulates MCP Tool: Fetching raw data from S3"""
        logger.info(f"Fetching context from s3://{bucket}/{key}")
        # Lógica de extracción aquí
        pass

    def get_historical_patterns(self, user_id: str):
        """Simulates MCP Tool: Querying Redshift/Athena for user behavior"""
        # Esto es lo que "alimenta" al agente para que no alucine
        return {"avg_spend": 150.0, "common_currency": "USD", "risk_level": "low"}