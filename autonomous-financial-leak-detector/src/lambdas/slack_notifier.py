"""
slack_notifier.py — Forwards SNS alerts to Slack via Incoming Webhook.
Deployed as a Lambda function triggered by the audit-alerts SNS topic.
"""
import json
import os
import urllib.request

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]


def handler(event, _context):
    sns_message = json.loads(event["Records"][0]["Sns"]["Message"])

    status   = sns_message.get("status", "UNKNOWN")
    risk     = sns_message.get("risk_score", "—")
    reason   = sns_message.get("reason", "—")
    tx       = sns_message.get("transaction", {})
    tx_id    = tx.get("transaction_id") or tx.get("description", "unknown")
    report   = sns_message.get("report_s3_key", "—")

    color = "#e01e5a" if status == "FLAGGED" else "#2eb886"

    payload = {
        "attachments": [{
            "color": color,
            "title": f"[AFLD] {status} — {tx_id}",
            "fields": [
                {"title": "Risk Score", "value": str(risk), "short": True},
                {"title": "Status",     "value": status,   "short": True},
                {"title": "Reason",     "value": reason,   "short": False},
                {"title": "Report",     "value": report,   "short": False},
            ],
            "footer": "AFLD Audit Engine",
        }]
    }

    req = urllib.request.Request(
        SLACK_WEBHOOK_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req)
    return {"statusCode": 200}
