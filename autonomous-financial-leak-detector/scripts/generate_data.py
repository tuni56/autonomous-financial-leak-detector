import json
import os

def create_mock_data():
    transactions = [
        {
            "id": "TX_NORMAL_01",
            "amount": 45.50,
            "category": "Cafe & Snacks",
            "description": "Starbucks La Plata",
            "user": "rocio_baigorria"
        },
        {
            "id": "TX_SUSPICIOUS_02",
            "amount": 1200.00,
            "category": "Software",
            "description": "Adobe Creative Cloud Annual Prepago",
            "user": "rocio_baigorria"
        },
        {
            "id": "TX_FRAUD_03",
            "amount": 15000.00,
            "category": "Luxury",
            "description": "Rolex Submariner - Dubai Duty Free",
            "user": "rocio_baigorria"
        }
    ]

    os.makedirs("data", exist_ok=True)
    for tx in transactions:
        filename = f"data/{tx['id']}.json"
        with open(filename, 'w') as f:
            json.dump(tx, f, indent=4)
        print(f"✅ Creado: {filename}")

if __name__ == "__main__":
    create_mock_data()