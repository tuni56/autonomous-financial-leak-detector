import streamlit as st
import boto3
import json
import uuid
from datetime import datetime

st.set_page_config(page_title="AFLD | AI Audit Dashboard", layout="wide", page_icon="🕵️")

REGION = "us-east-2"
LANDING_BUCKET = "afld-transactions-landing-7f8533d9"
AUDIT_BUCKET   = "afld-audit-reports-7f8533d9"
ALERTS_QUEUE   = "https://sqs.us-east-2.amazonaws.com/748607162458/afld-audit-engine-alerts-queue"
DLQ_URL        = "https://sqs.us-east-2.amazonaws.com/748607162458/afld-audit-engine-dlq"

s3  = boto3.client("s3",  region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)

SCENARIOS = {
    "normal": {
        "amount": 49.99, "category": "Software", "description": "GitHub Copilot monthly subscription",
        "metadata": {"hour_utc": 15, "device": "MacBook Pro - Chrome", "ip": "181.45.23.10", "ip_country": "Argentina"},
    },
    "suspicious": {
        "amount": 200.0, "category": "Gardening Tools", "description": "Premium Garden Hose Set & Sprinkler System",
        "metadata": {"hour_utc": 6, "device": "Unknown-Device-Linux-x86", "ip": "45.152.66.201", "ip_country": "Romania"},
    },
    "fraud": {
        "amount": 15000.0, "category": "Luxury Goods", "description": "Rolex Submariner - Dubai Duty Free",
        "metadata": {"hour_utc": 2, "device": "Unknown-Device-Windows", "ip": "185.220.101.45", "ip_country": "Netherlands (Tor exit node)"},
    },
}

# ── Header ──────────────────────────────────────────────────────────────────
st.title("🕵️ Autonomous Financial Leak Detector")
st.caption("Amazon Bedrock · Claude 3.5 Sonnet · SNS → SQS · Dead Letter Queue · us-east-2")
st.divider()

col_inject, col_reports, col_queue = st.columns([1, 2, 1])

# ── LEFT: Inject ─────────────────────────────────────────────────────────────
with col_inject:
    st.subheader("📤 Inject Transaction")
    scenario = st.selectbox("Scenario", list(SCENARIOS.keys()))
    tx = SCENARIOS[scenario]
    st.metric("Amount", f"${tx['amount']:,.2f}")
    st.caption(f"{tx['category']} · {tx['description']}")
    st.caption(f"🌐 IP: `{tx['metadata']['ip']}` ({tx['metadata']['ip_country']})")
    st.caption(f"🕐 Hour UTC: `{tx['metadata']['hour_utc']}:00`")

    if st.button("🚀 Send to AWS", use_container_width=True):
        payload = {
            "transaction_id": str(uuid.uuid4()),
            "user_id": "user_rocio_99",
            "amount": tx["amount"],
            "currency": "USD",
            "category": tx["category"],
            "description": tx["description"],
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": tx["metadata"],
        }
        key = f"pending/{payload['transaction_id']}.json"
        s3.put_object(Bucket=LANDING_BUCKET, Key=key, Body=json.dumps(payload), ContentType="application/json")
        st.success("✅ Uploaded to S3 landing zone")
        st.code(f"s3://{LANDING_BUCKET}/{key}", language="text")
        st.info("Lambda will trigger automatically via S3 event notification.")

    st.divider()

    # Simulate a Lambda failure to populate DLQ
    st.subheader("💥 Simulate Failure")
    st.caption("Sends a malformed event to trigger DLQ routing after 2 retries.")
    if st.button("Inject Bad Payload", use_container_width=True):
        bad_key = f"pending/BAD_{uuid.uuid4()}.json"
        s3.put_object(Bucket=LANDING_BUCKET, Key=bad_key, Body=b"not-valid-json{{", ContentType="application/json")
        st.warning(f"Bad payload sent → Lambda will fail → DLQ in ~60s")

# ── CENTER: Audit Reports ─────────────────────────────────────────────────────
with col_reports:
    st.subheader("🤖 Agent Verdicts")
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

    try:
        resp = s3.list_objects_v2(Bucket=AUDIT_BUCKET, Prefix="reports/")
        objects = sorted(resp.get("Contents", []), key=lambda x: x["LastModified"], reverse=True)

        if not objects:
            st.info("📡 System online. No reports yet.")
        else:
            for obj in objects[:6]:
                report = json.loads(s3.get_object(Bucket=AUDIT_BUCKET, Key=obj["Key"])["Body"].read())
                analysis = report.get("analysis", {})
                tx_data  = report.get("transaction", {})
                is_anomaly = analysis.get("anomaly", False)
                risk = analysis.get("risk_score", 0)

                if is_anomaly:
                    st.error(f"🚨 **FLAGGED** · {tx_data.get('description', '—')} · ${tx_data.get('amount', 0):,.2f}")
                    st.metric("Risk Score", f"{risk*100:.0f}%", delta="HIGH RISK", delta_color="inverse")
                else:
                    st.success(f"✅ **CLEARED** · {tx_data.get('description', '—')} · ${tx_data.get('amount', 0):,.2f}")
                    st.metric("Risk Score", f"{risk*100:.0f}%", delta_color="off")

                st.caption(f"🧠 {analysis.get('reason', '—')}")
                with st.expander("Full JSON"):
                    st.json(report)
                st.divider()
    except Exception as e:
        st.error(f"S3 error: {e}")

# ── RIGHT: SQS Alerts + DLQ ──────────────────────────────────────────────────
with col_queue:
    st.subheader("📨 SNS → SQS Alerts")
    try:
        msgs = sqs.receive_message(
            QueueUrl=ALERTS_QUEUE,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=1,
            AttributeNames=["All"],
        ).get("Messages", [])

        if not msgs:
            st.info("Queue empty.")
        for m in msgs:
            body = json.loads(m["Body"])
            inner = json.loads(body.get("Message", "{}"))
            status = inner.get("status", "?")
            risk   = inner.get("risk_score", 0)
            if status == "FLAGGED":
                st.error(f"🚨 {status} · risk {risk*100:.0f}%")
            else:
                st.success(f"✅ {status} · risk {risk*100:.0f}%")
            st.caption(inner.get("reason", "—"))
            st.divider()
    except Exception as e:
        st.warning(f"SQS: {e}")

    st.subheader("☠️ Dead Letter Queue")
    try:
        dlq_msgs = sqs.receive_message(
            QueueUrl=DLQ_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=1,
            AttributeNames=["All"],
        ).get("Messages", [])

        if not dlq_msgs:
            st.success("DLQ empty — no failures.")
        for m in dlq_msgs:
            approx_age = int(m.get("Attributes", {}).get("ApproximateFirstReceiveTimestamp", 0))
            st.error(f"💀 Failed event in DLQ")
            with st.expander("Raw message"):
                st.code(m.get("Body", "")[:500], language="json")
            st.divider()
    except Exception as e:
        st.warning(f"DLQ: {e}")
