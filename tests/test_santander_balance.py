import importlib
import json
import os
import sys
from unittest.mock import patch

import pytest
from aioresponses import aioresponses
from httpx import ASGITransport, AsyncClient

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import server
from eb_client import ASPSP_NAME, BankSession

SESSION_FIXTURE = os.path.join(ROOT, "fixtures", "session.json")
BALANCES_FIXTURE = os.path.join(ROOT, "fixtures", "balances.json")
CONFIG_PATH = os.path.join(ROOT, "config.json")

SANTANDER_UUID = "test-santander-uuid"
MBANK_UUID = "test-mbank-uuid"


def _mock_bank_session(aspsp):
    bs = BankSession.__new__(BankSession)
    bs.session_id = SANTANDER_UUID if aspsp == ASPSP_NAME.SANTANDER else MBANK_UUID
    return bs


@pytest.mark.asyncio
async def test_santander_balance_handler(monkeypatch):
    monkeypatch.setenv("CONFIG_PATH", CONFIG_PATH)

    with open(SESSION_FIXTURE, "r", encoding="utf-8") as f:
        session_data = json.load(f)
    with open(BALANCES_FIXTURE, "r", encoding="utf-8") as f:
        balances_data = json.load(f)

    with aioresponses() as mocked, patch("eb_client.BankSession.load", side_effect=_mock_bank_session):
        mocked.get("https://api.ipify.org", body="1.2.3.4")
        mocked.get(f"https://api.enablebanking.com/sessions/{SANTANDER_UUID}", payload=session_data)

        accounts = session_data["accounts"]
        for acct in accounts:
            mocked.get(f"https://api.enablebanking.com/accounts/{acct}/balances", payload=balances_data)

        importlib.reload(server)

        ctx = server.lifespan(server.app)
        await ctx.__aenter__()

        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get("/santander-balance")
            assert resp.status_code == 200
            data = resp.json()
            assert data["accounts"][0]["balance"] == balances_data["balances"][1]["balance_amount"]["amount"]
            assert data["accounts"][1]["balance"] == balances_data["balances"][1]["balance_amount"]["amount"]

        await ctx.__aexit__(None, None, None)
