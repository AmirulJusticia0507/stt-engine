"""Tests untuk register publik, paket, checkout, webhook, dan kuota."""
from __future__ import annotations

import hashlib

import pytest


def _reg(client, username, password="pass1234"):
    return client.post("/api/v1/auth/register", json={"username": username, "password": password})


def _token(client, username, password="pass1234"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_register_ok_and_auto_free(client):
    r = _reg(client, "budi_bill")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["username"] == "budi_bill"
    assert "access_token" in data
    me = client.get("/api/v1/subscriptions/me",
                    headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.status_code == 200
    assert me.json()["data"]["plan"] == "free"


def test_register_validation_and_duplicate(client):
    assert _reg(client, "x").status_code == 400  # terlalu pendek
    assert _reg(client, "budi_dup", "123").status_code == 400  # password pendek
    assert _reg(client, "budi_dup").status_code == 200
    assert _reg(client, "budi_dup").status_code == 400  # duplikat


def test_plans_public(client):
    r = client.get("/api/v1/plans")
    assert r.status_code == 200
    codes = {p["code"] for p in r.json()["data"]}
    assert {"free", "basic", "pro"} <= codes


def test_checkout_butuh_midtrans_key(client, monkeypatch):
    _reg(client, "bayu_bill")
    tok = _token(client, "bayu_bill")
    monkeypatch.delenv("MIDTRANS_SERVER_KEY", raising=False)
    r = client.post("/api/v1/subscriptions/checkout",
                    json={"plan": "basic", "period": "monthly"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 503, r.text


def test_checkout_dan_webhook_aktivasi(client, monkeypatch):
    async def fake_snap(order_id, amount, username):
        return {"token": "snap-tok", "redirect_url": "https://snap/abc"}

    monkeypatch.setattr("app.billing.create_snap_transaction", fake_snap)
    monkeypatch.setenv("MIDTRANS_SERVER_KEY", "test-server-key")
    _reg(client, "siti_bill")
    tok = _token(client, "siti_bill")
    r = client.post("/api/v1/subscriptions/checkout",
                    json={"plan": "pro", "period": "yearly"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    order_id = r.json()["order_id"]
    assert r.json()["amount"] == 1490000

    # webhook Midtrans dengan signature valid
    sig = hashlib.sha512(f"{order_id}2001490000.00test-server-key".encode()).hexdigest()
    w = client.post("/api/v1/midtrans/webhook", json={
        "order_id": order_id, "status_code": "200", "gross_amount": "1490000.00",
        "signature_key": sig, "transaction_status": "settlement",
        "fraud_status": "accept", "payment_type": "bank_transfer",
    })
    assert w.status_code == 200, w.text
    me = client.get("/api/v1/subscriptions/me",
                    headers={"Authorization": f"Bearer {tok}"}).json()["data"]
    assert me["plan"] == "pro" and me["status"] == "active"
    assert me["quota_limit"] is None  # unlimited
    hist = client.get("/api/v1/billing",
                      headers={"Authorization": f"Bearer {tok}"}).json()["data"]
    assert any(p["order_id"] == order_id and p["status"] == "success" for p in hist)


def test_webhook_signature_salah(client, monkeypatch):
    monkeypatch.setenv("MIDTRANS_SERVER_KEY", "test-server-key")
    r = client.post("/api/v1/midtrans/webhook", json={
        "order_id": "x", "status_code": "200", "gross_amount": "1",
        "signature_key": "salah", "transaction_status": "settlement",
    })
    assert r.status_code == 403


def test_kuota_free_dan_bypass_admin(client):
    from app.auth import check_quota, consume_quota

    _reg(client, "kuota_bill")
    ok, info = check_quota("kuota_bill", 10)
    assert ok and info["quota_limit"] == 10
    consume_quota("kuota_bill", 10)
    ok, info = check_quota("kuota_bill", 1)
    assert not ok
    ok, info = check_quota("admin", 9999)  # admin bebas
    assert ok and info.get("bypass") == "admin"


def test_admin_set_subscription(client, auth_headers):
    _reg(client, "eko_bill")
    r = client.post("/api/v1/subscriptions/eko_bill/set",
                    json={"plan": "basic", "period": "monthly"},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["quota_limit"] == 300
    # user biasa tidak boleh
    tok = _token(client, "eko_bill")
    r2 = client.post("/api/v1/subscriptions/eko_bill/set",
                     json={"plan": "pro", "period": "monthly"},
                     headers={"Authorization": f"Bearer {tok}"})
    assert r2.status_code == 403


def test_admin_cancel_subscription(client, auth_headers):
    _reg(client, "budi_cancel")
    # Aktifkan paket basic dulu
    r = client.post("/api/v1/subscriptions/budi_cancel/set",
                    json={"plan": "basic", "period": "monthly"},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    # Admin membatalkan
    r = client.post("/api/v1/subscriptions/budi_cancel/cancel",
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["plan"] == "free" and data["quota_limit"] == 10
    # User biasa tidak boleh
    tok = _token(client, "budi_cancel")
    r2 = client.post("/api/v1/subscriptions/budi_cancel/cancel",
                     headers={"Authorization": f"Bearer {tok}"})
    assert r2.status_code == 403
    # Cek bahwa paket user kembali free
    me = client.get("/api/v1/subscriptions/me",
                    headers={"Authorization": f"Bearer {tok}"}).json()["data"]
    assert me["plan"] == "free" and me["quota_limit"] == 10
