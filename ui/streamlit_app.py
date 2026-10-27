"""Streamlit front end for the Ledger API. It only talks to the HTTP API, never the DB.

streamlit run ui/streamlit_app.py

Customers identify themselves by mobile number. Internal account IDs and
transaction reference IDs are kept out of sight, except for the reference of a
successful transaction, which is shown as its receipt.
"""

import os
import uuid
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv
from markdown_safe import escape  # sibling module; Streamlit puts ui/ on sys.path

st.set_page_config(page_title="Transaction Ledger", page_icon="📒", layout="wide")

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
DEMO_PHONE = "9000000001"
REPO_URL = "https://github.com/gowdavidwan2003/ledger-api"


def _secrets_to_env() -> None:
    """On Streamlit Cloud, configuration arrives as st.secrets, not a .env file."""
    try:
        for key, value in st.secrets.items():
            # TOML allows EMBED_API = 1 or = true as well as "1"; accept them all.
            if isinstance(value, str | int | float | bool):
                os.environ.setdefault(key, str(value))
    except Exception:  # no secrets file locally: .env is used instead
        pass


def _embed_api() -> bool:
    """Run the API in-process when asked to, or when the app has database
    credentials but no external API to talk to (the hosted setup)."""
    flag = os.getenv("EMBED_API", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    return flag == "" and bool(os.getenv("DATABASE_URL")) and not os.getenv("API_URL")


@st.cache_resource(show_spinner="Starting the ledger API…")
def _embedded_api_url() -> str:
    from embedded_api import start  # sibling module

    return start(int(os.getenv("EMBEDDED_API_PORT", "8765")))


_secrets_to_env()
EMBEDDED = _embed_api()
API_URL = _embedded_api_url() if EMBEDDED else os.getenv("API_URL", "http://localhost:8000").rstrip("/")

FRIENDLY = {
    "PHONE_NOT_REGISTERED": "No account found for this number. Create one in the **Create account** tab.",
    "PHONE_ALREADY_REGISTERED": "An account with this number already exists. Use the **Log in** tab instead.",
    "REFERENCE_ID_CONFLICT": "This looks like a repeat of an earlier request with different details. Submit again.",
    "DATABASE_UNAVAILABLE": "The service is busy right now. Please try again in a moment.",
}


def api(method: str, path: str, **kwargs) -> tuple[int, dict]:
    try:
        res = requests.request(method, f"{API_URL}{path}", timeout=15, **kwargs)
    except requests.ConnectionError:
        st.error(f"Can't reach the API at {API_URL}. Is `uvicorn app.main:app` running?")
        st.stop()
    return res.status_code, res.json()


def show_error(body: dict) -> None:
    err = body.get("error", {})
    code = err.get("code")
    if code == "INSUFFICIENT_FUNDS":
        d = err["details"]
        st.error(
            f"**Transaction declined: insufficient balance.** "
            f"Available {rupees(d['balance'])}, requested {rupees(d['requested'])}. Nothing was deducted."
        )
    elif code == "VALIDATION_ERROR":
        fields = ", ".join(sorted({e["field"] for e in err.get("details") or []})) or "input"
        st.error(f"Please check: {fields}.")
    else:
        st.error(FRIENDLY.get(code, err.get("message", "Something went wrong.")))


def rupees(value: str) -> str:
    whole, _, frac = value.partition(".")
    # Indian digit grouping: 1,23,45,678.90
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join([*groups, tail]) + (f".{frac}" if frac else "")


def new_reference() -> str:
    return f"TXN{uuid.uuid4().hex[:10].upper()}"


st.session_state.setdefault("account_id", None)
# The idempotency key for the transaction being entered. It survives failed or
# timed-out attempts, so a resubmit can't double-post, and rotates after success.
st.session_state.setdefault("pending_ref", new_reference())
st.session_state.setdefault("receipt", None)
st.session_state.setdefault("form_generation", 0)

st.title("📒 Transaction Ledger")

# --- Logged out: log in or sign up by phone ------------------------------------------
if not st.session_state.account_id:
    st.info(
        f"🧪 **Demo app: use a dummy mobile number.** Any 10-digit number starting with 6–9 works. "
        f"No OTP is sent and no SMS goes out. Try the demo account **Vidwan Gowda**: `{DEMO_PHONE}`."
    )
    login, signup = st.tabs(["Log in", "Create account"])

    with login, st.form("login"):
        phone = st.text_input("Mobile number", placeholder=DEMO_PHONE, max_chars=16)
        if st.form_submit_button("Log in", type="primary", use_container_width=True):
            code, body = api("POST", "/accounts/lookup", json={"phone": phone})
            if code == 200:
                st.session_state.account_id = body["id"]
                st.rerun()
            show_error(body)

    with signup, st.form("signup"):
        name = st.text_input("Full name", placeholder="Vidwan Gowda")
        phone = st.text_input("Mobile number (dummy)", placeholder="9XXXXXXXXX", max_chars=16)
        st.caption("New accounts always start with a balance of ₹0.00.")
        if st.form_submit_button("Create account", type="primary", use_container_width=True):
            code, body = api("POST", "/accounts", json={"name": name, "phone": phone})
            if code == 201:
                st.session_state.account_id = body["id"]
                st.rerun()
            show_error(body)
    st.stop()

# --- Logged in -------------------------------------------------------------------------
account_id = st.session_state.account_id
code, account = api("GET", f"/accounts/{account_id}")
if code != 200:
    st.session_state.account_id = None
    st.rerun()

with st.sidebar:
    st.caption("Logged in as")
    st.subheader(escape(account["name"]))
    st.write(account["phone"])
    if st.button("Log out", use_container_width=True):
        st.session_state.account_id = None
        st.session_state.receipt = None
        st.rerun()
    st.divider()
    if EMBEDDED:
        # Hosted: the API only listens on the container's loopback, so link the repo docs.
        st.caption(f"[API reference]({REPO_URL}#api) · [Error codes]({REPO_URL}/blob/main/docs/ERRORS.md)")
    else:
        st.caption(f"[API docs]({API_URL}/docs)")

top = st.columns([5, 3, 3])
top[0].subheader(escape(account["name"]))
top[0].caption(account["phone"])
top[1].metric("Balance", rupees(account["balance"]))
top[2].caption("Customer since")
top[2].write(account["created_at"][:10])

st.divider()
left, right = st.columns([1, 2], gap="large")

with left:
    st.subheader("New transaction")

    if receipt := st.session_state.receipt:
        st.success(receipt)

    # A new form identity after every success resets its fields, so clicking Submit
    # again can't silently post the same transaction a second time under a fresh
    # reference. After a failure the fields (and the reference) are kept for retry.
    n = st.session_state.form_generation
    with st.form(f"txn-{n}"):
        txn_type = st.segmented_control("Type", ["credit", "debit"], default="credit", key=f"type-{n}")
        amount = st.number_input("Amount (₹)", min_value=0.01, step=100.0, format="%.2f", key=f"amount-{n}")
        description = st.text_input("Description", placeholder="e.g. Salary, Rent, Coffee", key=f"desc-{n}")
        if st.form_submit_button("Submit", type="primary", use_container_width=True):
            st.session_state.receipt = None
            code, body = api(
                "POST",
                f"/accounts/{account_id}/transactions",
                json={
                    "type": txn_type,
                    "amount": f"{amount:.2f}",
                    "description": description,
                    "reference_id": st.session_state.pending_ref,
                },
            )
            if code in (200, 201):
                verb = "credited to" if body["type"] == "credit" else "debited from"
                note = " (already processed earlier, not charged again)" if code == 200 else ""
                st.session_state.receipt = (
                    f"✅ **{rupees(body['amount'])} {verb} your account{note}.**  \n"
                    f"Reference: `{body['reference_id']}` · Balance: {rupees(body['balance_after'])}"
                )
                st.session_state.pending_ref = new_reference()
                st.session_state.form_generation += 1
                st.rerun()
            if code == 409:
                st.session_state.pending_ref = new_reference()
            show_error(body)

with right:
    st.subheader("History")
    type_filter = st.segmented_control("Filter", ["all", "credit", "debit"], default="all", key="filter")
    params = {"limit": 50}
    if type_filter and type_filter != "all":
        params["type"] = type_filter

    rows, cursor = [], None
    for _ in range(4):  # up to 200 rows in the UI
        if cursor:
            params["cursor"] = cursor
        code, page = api("GET", f"/accounts/{account_id}/transactions", params=params)
        if code != 200:
            show_error(page)
            break
        rows += page["data"]
        cursor = page["next_cursor"]
        if not cursor:
            break

    if not rows:
        st.caption("No transactions yet.")
    else:
        st.dataframe(
            [
                {
                    "When (UTC)": t["created_at"].replace("T", " ")[:19],
                    "Type": "🟢 credit" if t["type"] == "credit" else "🔴 debit",
                    "Amount": ("+" if t["type"] == "credit" else "−") + rupees(t["amount"]),
                    "Balance after": rupees(t["balance_after"]),
                    "Description": t["description"],
                    "Reference": t["reference_id"],
                }
                for t in rows
            ],
            hide_index=True,
            use_container_width=True,
        )
