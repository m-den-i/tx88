import os
import sys
import json

import pytest
from aioresponses import aioresponses
from httpx import AsyncClient, ASGITransport

# Ensure tests can import server after env vars are set
HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

SESSION_FIXTURE = os.path.join(ROOT, "fixtures", "session.json")
BALANCES_FIXTURE = os.path.join(ROOT, "fixtures", "balances.json")
CONFIG_PATH = os.path.join(ROOT, "config.json")

@pytest.mark.asyncio
async def test_santander_balance_handler(monkeypatch):
    # Arrange: set env vars for config and session uuid
    monkeypatch.setenv("SANTANDER_CONFIG_PATH", CONFIG_PATH)

    # load session fixture
    with open(SESSION_FIXTURE, "r", encoding="utf-8") as f:
        session_data = json.load(f)
    session_uuid = "test-session-uuid"
    monkeypatch.setenv("SANTANDER_SESSION_UUID", session_uuid)

    # Start aioresponses to mock external API calls
    with aioresponses() as mocked:
        # Mock sessions/{session_uuid} to return session fixture
        mocked.get(f"https://api.enablebanking.com/sessions/{session_uuid}", payload=session_data)

        # Mock balances endpoint for all accounts in session fixture
        accounts = session_data["accounts"]
        with open(BALANCES_FIXTURE, "r", encoding="utf-8") as f:
            balances_data = json.load(f)
        for acct in accounts:
            mocked.get(f"https://api.enablebanking.com/accounts/{acct}/balances", payload=balances_data)

        # Import app after env vars and mocks are in place
        import importlib
        server = importlib.import_module("server")
        importlib.reload(server)

        app = server.app

        # Explicitly enter the lifespan context to populate settings
        ctx = server.lifespan(app)
        await ctx.__aenter__()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            # Act
            resp = await ac.get("/santander-balance")
            # Assert
            assert resp.status_code == 200
            data = resp.json()
            assert "accounts" in data
            assert isinstance(data["accounts"], list)
            assert data["accounts"][0]["balances"] == balances_data

        # Exit lifespan
        await ctx.__aexit__(None, None, None)
    print(data)