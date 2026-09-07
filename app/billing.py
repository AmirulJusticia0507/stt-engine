"""Integrasi Midtrans (Snap + webhook notification)."""
from __future__ import annotations

import base64
import hashlib
import os

import httpx


def server_key() -> str:
    return os.getenv("MIDTRANS_SERVER_KEY") or ""


def is_sandbox() -> bool:
    return (os.getenv("MIDTRANS_SANDBOX", "true") or "true").lower() not in ("0", "false", "no")


def api_base() -> str:
    return "https://app.sandbox.midtrans.com" if is_sandbox() else "https://app.midtrans.com"


def _auth_header() -> str:
    return "Basic " + base64.b64encode(f"{server_key()}:".encode()).decode()


async def create_snap_transaction(order_id: str, amount: int, username: str) -> dict:
    """Buat transaksi Snap. Return {"token", "redirect_url"}."""
    finish_url = (os.getenv("APP_BASE_URL") or "").rstrip("/") + f"/billing.html?order_id={order_id}"
    payload = {
        "transaction_details": {"order_id": order_id, "gross_amount": amount},
        "customer_details": {"first_name": username},
        "callbacks": {"finish": finish_url},
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{api_base()}/snap/v1/transactions",
            json=payload,
            headers={"Authorization": _auth_header(), "Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
    return {"token": data["token"], "redirect_url": data["redirect_url"]}


def verify_signature(order_id: str, status_code: str, gross_amount: str, signature_key: str) -> bool:
    """Signature Midtrans: SHA512(order_id + status_code + gross_amount + serverKey)."""
    import hmac

    expected = hashlib.sha512(
        f"{order_id}{status_code}{gross_amount}{server_key()}".encode()
    ).hexdigest()
    return hmac.compare_digest(expected, signature_key or "")


def is_paid_status(transaction_status: str, fraud_status: str = "") -> bool:
    if transaction_status == "settlement":
        return True
    return transaction_status == "capture" and fraud_status in ("", "accept")
