import boto3
import json
import uuid
import sys
from datetime import datetime

LANDING_BUCKET = "afld-transactions-landing-7f8533d9"
REGION = "us-east-2"

SCENARIOS = {
    # Baseline — matches profile perfectly
    "normal": {
        "amount": 49.99,
        "category": "Software",
        "description": "GitHub Copilot monthly subscription",
        "user_id": "user_rocio_99",
        "metadata": {
            "hour_utc": 15,  # 12:00 PM ART — normal working hours
            "device": "MacBook Pro - Chrome",
            "ip": "181.45.23.10",
            "ip_country": "Argentina",
        },
    },
    # Moderate amount but behavioral red flags — this is the money shot for the demo
    "suspicious": {
        "amount": 200.0,
        "category": "Gardening Tools",
        "description": "Premium Garden Hose Set & Sprinkler System",
        "user_id": "user_rocio_99",
        "metadata": {
            "hour_utc": 6,  # 3:00 AM ART — unusual hour
            "device": "Unknown-Device-Linux-x86",
            "ip": "45.152.66.201",
            "ip_country": "Romania",  # never seen before
        },
    },
    # High amount + all red flags stacked
    "fraud": {
        "amount": 15000.0,
        "category": "Luxury Goods",
        "description": "Rolex Submariner - Dubai Duty Free",
        "user_id": "user_rocio_99",
        "metadata": {
            "hour_utc": 2,
            "device": "Unknown-Device-Windows",
            "ip": "185.220.101.45",
            "ip_country": "Netherlands (Tor exit node)",
        },
    },
}


def inject(scenario: str = "suspicious"):
    tx = SCENARIOS.get(scenario)
    if not tx:
        print(f"Unknown scenario '{scenario}'. Choose: {list(SCENARIOS.keys())}")
        return

    payload = {
        "transaction_id": str(uuid.uuid4()),
        "user_id": tx["user_id"],
        "amount": tx["amount"],
        "currency": "USD",
        "category": tx["category"],
        "description": tx["description"],
        "timestamp": datetime.utcnow().isoformat(),
        "metadata": tx["metadata"],
    }

    key = f"pending/{payload['transaction_id']}.json"
    s3 = boto3.client("s3", region_name=REGION)
    s3.put_object(Bucket=LANDING_BUCKET, Key=key, Body=json.dumps(payload), ContentType="application/json")

    print(f"[{scenario.upper()}] Injected → s3://{LANDING_BUCKET}/{key}")
    print(f"  Amount:   ${payload['amount']:,.2f} ({payload['category']})")
    print(f"  IP:       {tx['metadata']['ip']} ({tx['metadata']['ip_country']})")
    print(f"  Hour UTC: {tx['metadata']['hour_utc']}:00")
    print("  Lambda will trigger automatically. Check dashboard in ~5s.")


if __name__ == "__main__":
    inject(sys.argv[1] if len(sys.argv) > 1 else "suspicious")
