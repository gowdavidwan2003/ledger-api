"""Create the demo account (dummy number 9000000001) with some history, through
the public API. Safe to re-run: an existing demo account is left as it is.

python scripts/seed_demo.py            # API_URL from .env, default http://localhost:8000
"""

import os
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()
API = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

DEMO_NAME = "Vidwan Gowda"
DEMO_PHONE = "9000000001"  # dummy number, not a real subscriber
HISTORY = [
    ("credit", "85000.00", "October salary"),
    ("debit", "22000.00", "Rent"),
    ("debit", "1249.50", "Electricity bill"),
    ("credit", "1500.00", "Cashback"),
    ("debit", "3420.75", "Groceries"),
    ("debit", "650.00", "Coffee with team"),
]


def main() -> None:
    res = requests.post(f"{API}/accounts", json={"name": DEMO_NAME, "phone": DEMO_PHONE}, timeout=15)
    if res.status_code == 409:
        print(f"demo account already exists, log in with {DEMO_PHONE}")
        return
    res.raise_for_status()
    tx_url = f"{API}/accounts/{res.json()['id']}/transactions"
    for type_, amount, description in HISTORY:
        body = {"type": type_, "amount": amount, "description": description, "reference_id": uuid.uuid4().hex[:12]}
        requests.post(tx_url, json=body, timeout=15).raise_for_status()

    balance = requests.post(f"{API}/accounts/lookup", json={"phone": DEMO_PHONE}, timeout=15).json()["balance"]
    print(f"created {DEMO_NAME}, log in with {DEMO_PHONE}, balance {balance}")


if __name__ == "__main__":
    main()
