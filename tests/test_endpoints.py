import importlib
import json
import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from aioresponses import aioresponses
from httpx import ASGITransport, AsyncClient

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import server as server_module
from eb_client import ASPSP_NAME, BankSession

SESSION_FIXTURE = os.path.join(ROOT, "fixtures", "session.json")
BALANCES_FIXTURE = os.path.join(ROOT, "fixtures", "balances.json")
CONFIG_PATH = os.path.join(ROOT, "config.json")
API = "https://api.enablebanking.com"
IPIFY = "https://api.ipify.org"

SANTANDER_UUID = "aaaaaaaa-0000-0000-0000-000000000001"
MBANK_UUID = "bbbbbbbb-0000-0000-0000-000000000002"

with open(SESSION_FIXTURE, "r", encoding="utf-8") as _f:
    SESSION_DATA = json.load(_f)

with open(BALANCES_FIXTURE, "r", encoding="utf-8") as _f:
    BALANCES_DATA = json.load(_f)

ACCOUNTS = SESSION_DATA["accounts"]

TRANSACTIONS_PAYLOAD = {
    "transactions": [
        {
            "transaction_amount": {"currency": "PLN", "amount": "42.00"},
            "credit_debit_indicator": "DBIT",
            "status": "BOOK",
            "booking_date": "2026-04-07",
            "entry_reference": "ref-001",
        }
    ],
    "continuation_key": None,
}

PENDING_PAYLOAD = {
    "transactions": [
        {
            "transaction_amount": {"currency": "PLN", "amount": "9.99"},
            "credit_debit_indicator": "DBIT",
            "status": "HOLD",
            "booking_date": "2026-04-10",
            "entry_reference": "ref-pending",
        }
    ],
    "continuation_key": None,
}

SANTANDER_PENDING_PAYLOAD = {
    "transactions": [
        {
            "transaction_amount": {"currency": "PLN", "amount": "9.99"},
            "credit_debit_indicator": "DBIT",
            "status": "PDNG",
            "booking_date": "2026-04-10",
            "entry_reference": "ref-pending-santander",
        }
    ],
    "continuation_key": None,
}


def _setup_env(monkeypatch):
    monkeypatch.setenv("CONFIG_PATH", CONFIG_PATH)


def _reload_server():
    importlib.reload(server_module)
    return server_module


def _mock_bank_session(aspsp):
    bs = BankSession.__new__(BankSession)
    bs.session_id = SANTANDER_UUID if aspsp == ASPSP_NAME.SANTANDER else MBANK_UUID
    return bs


@pytest.mark.asyncio
async def test_mbank_balance(monkeypatch):
    _setup_env(monkeypatch)
    srv = _reload_server()

    with aioresponses() as mocked, patch("eb_client.BankSession.load", side_effect=_mock_bank_session):
        mocked.get(f"{API}/sessions/{MBANK_UUID}", payload=SESSION_DATA)
        for acct in ACCOUNTS:
            mocked.get(f"{API}/accounts/{acct}/balances", payload=BALANCES_DATA)
            mocked.get(
                f"{API}/accounts/{acct}/details",
                payload={"account_id": {"iban": f"PL{acct[:8]}"}},
            )
        mocked.get(IPIFY, body="1.2.3.4")

        ctx = srv.lifespan(srv.app)
        await ctx.__aenter__()
        transport = ASGITransport(app=srv.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get("/mbank-balance")

        await ctx.__aexit__(None, None, None)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["accounts"]) == len(ACCOUNTS)
    expected_balance = BALANCES_DATA["balances"][1]["balance_amount"]["amount"]
    for account in data["accounts"]:
        assert account["balance"] == expected_balance
        assert account["iban"] == f"PL{account['uuid'][:8]}"


@pytest.mark.asyncio
async def test_santander_card_blockades(monkeypatch):
    _setup_env(monkeypatch)
    srv = _reload_server()

    date_from, date_to = "2026-04-05", "2026-04-12"

    with aioresponses() as mocked, patch("eb_client.BankSession.load", side_effect=_mock_bank_session):
        mocked.get(f"{API}/sessions/{SANTANDER_UUID}", payload=SESSION_DATA)
        for acct in ACCOUNTS:
            mocked.get(
                f"{API}/accounts/{acct}/transactions"
                f"?transaction_status=PDNG&date_from={date_from}&date_to={date_to}",
                payload=SANTANDER_PENDING_PAYLOAD,
            )
        mocked.get(IPIFY, body="1.2.3.4")

        ctx = srv.lifespan(srv.app)
        await ctx.__aenter__()
        transport = ASGITransport(app=srv.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get(
                "/santander-card-blockades",
                params={"date_from": date_from, "date_to": date_to},
            )

        await ctx.__aexit__(None, None, None)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["accounts"]) == len(ACCOUNTS)
    txn = data["accounts"][0]["transactions"][0]
    assert txn["status"] == "PDNG"
    assert txn["transaction_amount"]["amount"] == "9.99"


@pytest.mark.asyncio
async def test_mbank_card_blockades(monkeypatch):
    _setup_env(monkeypatch)
    srv = _reload_server()

    date_from, date_to = "2026-04-05", "2026-04-12"

    with aioresponses() as mocked, patch("eb_client.BankSession.load", side_effect=_mock_bank_session):
        mocked.get(f"{API}/sessions/{MBANK_UUID}", payload=SESSION_DATA)
        for acct in ACCOUNTS:
            mocked.get(
                f"{API}/accounts/{acct}/transactions"
                f"?transaction_status=HOLD&date_from={date_from}&date_to={date_to}",
                payload=PENDING_PAYLOAD,
            )
        mocked.get(IPIFY, body="1.2.3.4")

        ctx = srv.lifespan(srv.app)
        await ctx.__aenter__()
        transport = ASGITransport(app=srv.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get(
                "/mbank-card-blockades",
                params={"date_from": date_from, "date_to": date_to},
            )

        await ctx.__aexit__(None, None, None)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["accounts"]) == len(ACCOUNTS)
    assert data["accounts"][0]["transactions"][0]["status"] == "HOLD"


@pytest.mark.asyncio
async def test_card_blockades_empty(monkeypatch):
    _setup_env(monkeypatch)
    srv = _reload_server()

    empty_payload = {"transactions": [], "continuation_key": None}
    date_from, date_to = "2026-04-05", "2026-04-12"

    with aioresponses() as mocked, patch("eb_client.BankSession.load", side_effect=_mock_bank_session):
        mocked.get(f"{API}/sessions/{MBANK_UUID}", payload=SESSION_DATA)
        for acct in ACCOUNTS:
            mocked.get(
                f"{API}/accounts/{acct}/transactions"
                f"?transaction_status=HOLD&date_from={date_from}&date_to={date_to}",
                payload=empty_payload,
            )
        mocked.get(IPIFY, body="1.2.3.4")

        ctx = srv.lifespan(srv.app)
        await ctx.__aenter__()
        transport = ASGITransport(app=srv.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get(
                "/mbank-card-blockades",
                params={"date_from": date_from, "date_to": date_to},
            )

        await ctx.__aexit__(None, None, None)

    assert resp.status_code == 200
    for acct_data in resp.json()["accounts"]:
        assert acct_data["transactions"] == []


@pytest.mark.asyncio
async def test_santander_transactions_explicit_dates(monkeypatch):
    _setup_env(monkeypatch)
    srv = _reload_server()

    date_from = "2026-04-01"
    date_to = "2026-04-08"

    with aioresponses() as mocked, patch("eb_client.BankSession.load", side_effect=_mock_bank_session):
        mocked.get(f"{API}/sessions/{SANTANDER_UUID}", payload=SESSION_DATA)
        for acct in ACCOUNTS:
            mocked.get(
                f"{API}/accounts/{acct}/transactions"
                f"?transaction_status=BOOK&date_from={date_from}&date_to={date_to}",
                payload=TRANSACTIONS_PAYLOAD,
            )
        mocked.get(IPIFY, body="1.2.3.4")

        ctx = srv.lifespan(srv.app)
        await ctx.__aenter__()
        transport = ASGITransport(app=srv.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get(
                "/santander-transactions",
                params={"date_from": date_from, "date_to": date_to},
            )

        await ctx.__aexit__(None, None, None)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["accounts"]) == len(ACCOUNTS)
    txn = data["accounts"][0]["transactions"][0]
    assert txn["status"] == "BOOK"
    assert txn["transaction_amount"]["amount"] == "42.00"


@pytest.mark.asyncio
async def test_mbank_transactions_explicit_dates(monkeypatch):
    _setup_env(monkeypatch)
    srv = _reload_server()

    date_from = "2026-04-01"
    date_to = "2026-04-08"

    with aioresponses() as mocked, patch("eb_client.BankSession.load", side_effect=_mock_bank_session):
        mocked.get(f"{API}/sessions/{MBANK_UUID}", payload=SESSION_DATA)
        for acct in ACCOUNTS:
            mocked.get(
                f"{API}/accounts/{acct}/transactions"
                f"?transaction_status=BOOK&date_from={date_from}&date_to={date_to}",
                payload=TRANSACTIONS_PAYLOAD,
            )
        mocked.get(IPIFY, body="1.2.3.4")

        ctx = srv.lifespan(srv.app)
        await ctx.__aenter__()
        transport = ASGITransport(app=srv.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get(
                "/mbank-transactions",
                params={"date_from": date_from, "date_to": date_to},
            )

        await ctx.__aexit__(None, None, None)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["accounts"]) == len(ACCOUNTS)
    assert data["accounts"][0]["transactions"][0]["status"] == "BOOK"


@pytest.mark.asyncio
async def test_transactions_default_date_range(monkeypatch):
    """When no dates supplied, defaults to last 7 days."""
    _setup_env(monkeypatch)
    srv = _reload_server()

    fixed_today = date(2026, 4, 12)
    expected_from = (fixed_today - timedelta(days=7)).isoformat()
    expected_to = fixed_today.isoformat()

    with aioresponses() as mocked, patch("eb_client.BankSession.load", side_effect=_mock_bank_session):
        mocked.get(f"{API}/sessions/{MBANK_UUID}", payload=SESSION_DATA)
        for acct in ACCOUNTS:
            mocked.get(
                f"{API}/accounts/{acct}/transactions"
                f"?transaction_status=BOOK&date_from={expected_from}&date_to={expected_to}",
                payload=TRANSACTIONS_PAYLOAD,
            )
        mocked.get(IPIFY, body="1.2.3.4")

        ctx = srv.lifespan(srv.app)
        await ctx.__aenter__()
        transport = ASGITransport(app=srv.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            with patch("server.date") as mock_date:
                mock_date.today.return_value = fixed_today
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                resp = await ac.get("/mbank-transactions")

        await ctx.__aexit__(None, None, None)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["accounts"]) == len(ACCOUNTS)
    assert data["accounts"][0]["transactions"][0]["status"] == "BOOK"


@pytest.mark.asyncio
async def test_transactions_response_structure(monkeypatch):
    """Response has correct shape: accounts list with account_uid and transactions."""
    _setup_env(monkeypatch)
    srv = _reload_server()

    date_from, date_to = "2026-04-01", "2026-04-08"

    with aioresponses() as mocked, patch("eb_client.BankSession.load", side_effect=_mock_bank_session):
        mocked.get(f"{API}/sessions/{SANTANDER_UUID}", payload=SESSION_DATA)
        for acct in ACCOUNTS:
            mocked.get(
                f"{API}/accounts/{acct}/transactions"
                f"?transaction_status=BOOK&date_from={date_from}&date_to={date_to}",
                payload=TRANSACTIONS_PAYLOAD,
            )
        mocked.get(IPIFY, body="1.2.3.4")

        ctx = srv.lifespan(srv.app)
        await ctx.__aenter__()
        transport = ASGITransport(app=srv.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get(
                "/santander-transactions",
                params={"date_from": date_from, "date_to": date_to},
            )

        await ctx.__aexit__(None, None, None)

    data = resp.json()
    for i, acct_data in enumerate(data["accounts"]):
        assert "account_uid" in acct_data
        assert acct_data["account_uid"] == ACCOUNTS[i]
        assert isinstance(acct_data["transactions"], list)
        for txn in acct_data["transactions"]:
            assert "transaction_amount" in txn
            assert "credit_debit_indicator" in txn
            assert "status" in txn
            assert "booking_date" in txn
