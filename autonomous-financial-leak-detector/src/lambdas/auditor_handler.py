import json
import os
import uuid
import boto3
from datetime import datetime
from loguru import logger
from src.agents.bedrock_agent import FinancialAuditor
from src.mcp.mcp_tools import FinancialMCP

auditor = FinancialAuditor()
mcp = FinancialMCP()

AUDIT_BUCKET  = os.environ["AUDIT_REPORT_BUCKET"]
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")
DLQ_URL       = os.environ.get("DLQ_URL")
REGION        = os.environ.get("AWS_REGION_NAME", "us-east-2")

s3  = boto3.client("s3")
sns = boto3.client("sns", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)


def handler(event, context):
    try:
        record = event.get("Records", [{}])[0]
        bucket = record["s3"]["bucket"]["name"]
        key    = record["s3"]["object"]["key"]

        # Fetch transaction first — user_id lives inside the payload, not the S3 key
        transaction_data = mcp.get_transaction_from_s3(bucket, key)
        user_id = transaction_data.get("user_id", "unknown")

        logger.info(f"Processing audit | user={user_id} | file={key}")

        if not transaction_data:
            raise ValueError("Empty transaction data")

        historical_context = mcp.get_historical_context(user_id)
        analysis = auditor.analyze_transaction(transaction=transaction_data, context=historical_context)

        report = {
            "report_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "source_file": key,
            "transaction": transaction_data,
            "analysis": analysis.dict(),
            "status": "FLAGGED" if analysis.anomaly else "CLEARED",
        }

        report_key = f"reports/{report['report_id']}.json"
        s3.put_object(Bucket=AUDIT_BUCKET, Key=report_key, Body=json.dumps(report, indent=2), ContentType="application/json")
        logger.success(f"Report saved → {report_key} | status={report['status']} | risk={analysis.risk_score:.2f}")

        if SNS_TOPIC_ARN:
            subject = f"[AFLD] {'FLAGGED' if analysis.anomaly else 'CLEARED'} — {transaction_data.get('description', key)}"
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=subject[:100],
                Message=json.dumps({
                    "status": report["status"],
                    "risk_score": analysis.risk_score,
                    "reason": analysis.reason,
                    "transaction": transaction_data,
                    "report_s3_key": report_key,
                }),
            )
            logger.info(f"SNS alert published | status={report['status']}")

        return {"statusCode": 200, "body": json.dumps(report)}

    except KeyError as e:
        logger.error(f"Malformed S3 event, missing key: {e}")
        _send_to_dlq(event, f"KeyError: {e}")
        return {"statusCode": 400, "body": json.dumps({"error": f"Malformed event: {e}"})}
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"Validation error: {e}")
        _send_to_dlq(event, f"{type(e).__name__}: {e}")
        return {"statusCode": 422, "body": json.dumps({"error": str(e)})}
    except Exception as e:
        logger.exception(f"Critical error in Audit Lambda: {e}")
        _send_to_dlq(event, f"{type(e).__name__}: {e}")
        raise


def _send_to_dlq(event: dict, error_msg: str):
    if not DLQ_URL:
        return
    try:
        sqs.send_message(
            QueueUrl=DLQ_URL,
            MessageBody=json.dumps({"error": error_msg, "original_event": event}),
        )
        logger.info(f"Event routed to DLQ | reason={error_msg}")
    except Exception as e:
        logger.error(f"Failed to send to DLQ: {e}")
