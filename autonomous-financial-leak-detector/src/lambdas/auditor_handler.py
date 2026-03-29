import json
import os
from loguru import logger
from src.agents.bedrock_agent import FinancialAuditor
from src.mcp.mcp_tools import FinancialMCP

# Inicializamos fuera del handler para reutilizar en ejecuciones calientes (Warm Starts)
auditor = FinancialAuditor()
mcp = FinancialMCP()

def handler(event, context):
    """
    AWS Lambda Entry Point
    Expects an S3 Event Trigger
    """
    try:
        # 1. Extraer info del evento de S3
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = event['Records'][0]['s3']['object']['key']
        user_id = key.split('/')[0] # Asumiendo estructura: user_id/transaccion.json
        
        logger.info(f"Processing audit for User: {user_id} | File: {key}")

        # 2. Enriquecer con MCP 
        transaction_data = mcp.get_transaction_from_s3(bucket, key)
        historical_context = mcp.get_historical_context(user_id)

        if not transaction_data:
            raise ValueError("Empty transaction data")

        # 3. Ejecutar Razonamiento del Agente
        analysis = auditor.analyze_transaction(
            transaction=transaction_data, 
            context=historical_context
        )

        # 4. Acciones basadas en el resultado
        report = {
            "user_id": user_id,
            "analysis": analysis.dict(),
            "status": "FLAGGED" if analysis.anomaly else "CLEARED"
        }

        logger.success(f"Audit completed. Risk Score: {analysis.risk_score}")
        
        return {
            "statusCode": 200,
            "body": json.dumps(report)
        }

    except Exception as e:
        logger.error(f"Critical error in Audit Lambda: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal Audit Failure"})
        }