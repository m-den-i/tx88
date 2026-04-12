import logging
import os
import random
import time
import json
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

import aiohttp
import jwt as pyjwt
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel
from contextlib import asynccontextmanager

from transaction_converter import Transaction

API_ORIGIN = "https://api.enablebanking.com"
IPIFY_URL = "https://api.ipify.org"

PSU_USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) Chrome/104.0.0.0 Gecko/20100101 Firefox/103.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
]

logger = logging.getLogger("tx88.server")
logging.basicConfig(level=logging.INFO)


# Required env vars
CONFIG_PATH = os.environ["SANTANDER_CONFIG_PATH"]
SANTANDER_SESSION_UUID = os.environ["SANTANDER_SESSION_UUID"]
MBANK_SESSION_UUID = os.environ["MBANK_SESSION_UUID"]

class ConfigModel(BaseModel):
    keyPath: str
    applicationId: str


class SessionResponseModel(BaseModel):
    # minimal required fields from sessions/{session_id}
    accounts: List[str]


class Settings:
    """Holds application configuration loaded from files and the session fetched from the API.

    All attributes are required and guaranteed to be present when `load` returns.
    """

    def __init__(self, application_id: str, app_private_key: str, session_uuid: str):
        self.application_id: str = application_id
        self.app_private_key: str = app_private_key
        self.session_uuid: str = session_uuid

    @classmethod
    async def load(cls, session_uuid: str, config_path: str = CONFIG_PATH) -> "Settings":
        # Validate config file
        with open(config_path, "rt", encoding="utf-8") as f:
            cfg_data = json.load(f)
        cfg = ConfigModel.model_validate(cfg_data)
        # Read private key
        key_path = cfg.keyPath
        if not os.path.isabs(key_path):
            key_path = os.path.join(os.path.dirname(__file__), key_path)
        with open(key_path, "r", encoding="utf-8") as f:
            private_key = f.read()

        return cls(
            application_id=cfg.applicationId,
            app_private_key=private_key,
            session_uuid=session_uuid,
        )


# Module-level settings object will be assigned in lifespan
santander_settings: Optional["Settings"] = None
mbank_settings: Optional["Settings"] = None
public_ip: Optional[str] = None


async def _fetch_public_ip() -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(IPIFY_URL) as resp:
            return await resp.text()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global santander_settings
    global mbank_settings
    global public_ip
    santander_settings = await Settings.load(SANTANDER_SESSION_UUID)
    mbank_settings = await Settings.load(MBANK_SESSION_UUID)
    for settings in (santander_settings, mbank_settings):
        logger.info("Settings loaded: application_id=%s session_uuid=%s", settings.application_id, settings.session_uuid)
    public_ip = await _fetch_public_ip()
    logger.info("Detected public IP: %s", public_ip)
    yield


app = FastAPI(lifespan=lifespan)


def build_jwt_token(settings: Settings) -> str:
    iat = int(time.time())
    jwt_body = {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": iat, "exp": iat + 600}
    jwt_token = pyjwt.encode(jwt_body, settings.app_private_key, algorithm="RS256", headers={"kid": settings.application_id})
    if isinstance(jwt_token, bytes):
        jwt_token = jwt_token.decode()
    return jwt_token


class AccountTransactionsResponse(BaseModel):
    account_uid: UUID
    transactions: list[Transaction]


class Application:
    def __init__(self, settings: Settings, extra_headers: dict | None = None):
        self.settings = settings
        self.headers = {"Authorization": f"Bearer {build_jwt_token(settings)}", **(extra_headers or {})}

    async def __aenter__(self):
        self.client = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return await self.client.close()

    async def get_session(self) -> SessionResponseModel:
        async with self.client.get(f"{API_ORIGIN}/sessions/{self.settings.session_uuid}", headers=self.headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                    detail={"error": "external_api_error", "status": resp.status, "text": text})
            data = await resp.json()

        return SessionResponseModel.model_validate(data)

    async def get_account_balances(self, session_parsed: SessionResponseModel):
        accounts = session_parsed.accounts

        results = []
        for account_uid in accounts:
            async with self.client.get(f"{API_ORIGIN}/accounts/{account_uid}/balances", headers=self.headers) as resp2:
                if resp2.status != 200:
                    text = await resp2.text()
                    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                        detail={"error": "external_api_error", "status": resp2.status, "text": text})
                bal = await resp2.json()
            results.append({"account_uid": account_uid, "balances": bal})
        return results

    async def get_account_transactions(
        self,
        account_uid: str,
        transaction_status: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[Transaction]:
        params: dict = {"transaction_status": transaction_status}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        async with self.client.get(
            f"{API_ORIGIN}/accounts/{account_uid}/transactions",
            headers=self.headers,
            params=params,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={"error": "external_api_error", "status": resp.status, "text": text},
                )
            data = await resp.json()

        return [Transaction.model_validate(t) for t in data.get("transactions", [])]

    async def get_all_transactions(
        self,
        session_parsed: SessionResponseModel,
        transaction_status: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list["AccountTransactionsResponse"]:
        results = []
        for account_uid in session_parsed.accounts:
            txns = await self.get_account_transactions(account_uid, transaction_status, date_from, date_to)
            results.append(AccountTransactionsResponse(account_uid=UUID(account_uid), transactions=txns))
        return results


class BalanceResponse(BaseModel):
    uuid: UUID
    balance: Decimal


class AccountsResponse(BaseModel):
    accounts: list[BalanceResponse]

    @classmethod
    def from_eb_accounts(cls, eb_accounts: list[dict]) -> "AccountsResponse":
        accounts = []
        for acc in eb_accounts:
            for bal in acc["balances"]["balances"]:
                if bal["balance_type"] == "ITAV":
                    accounts.append(BalanceResponse(uuid=UUID(acc["account_uid"]), balance=Decimal(bal["balance_amount"]["amount"])))
        return AccountsResponse.model_validate({"accounts": accounts})


class TransactionsResponse(BaseModel):
    accounts: list[AccountTransactionsResponse]


@app.get("/santander-balance")
async def santander_balance():
    psu_headers = {
        "Psu-Ip-Address": public_ip,
        "Psu-User-Agent": random.choice(PSU_USER_AGENTS),
    }
    async with Application(santander_settings, extra_headers=psu_headers) as app:
        session = await app.get_session()
        results = await app.get_account_balances(session)
    resp = AccountsResponse.from_eb_accounts(results)
    return resp


@app.get("/mbank-balance")
async def mbank_balance():
    # Fetch session from the API
    async with Application(mbank_settings) as app:
        session = await app.get_session()
        results = await app.get_account_balances(session)
    return AccountsResponse.from_eb_accounts(results)


@app.get("/santander-card-blockades", response_model=TransactionsResponse)
async def santander_card_blockades():
    psu_headers = {
        "Psu-Ip-Address": public_ip,
        "Psu-User-Agent": random.choice(PSU_USER_AGENTS),
    }
    async with Application(santander_settings, extra_headers=psu_headers) as app:
        session = await app.get_session()
        accounts = await app.get_all_transactions(session, transaction_status="PDNG")
    return TransactionsResponse(accounts=accounts)


@app.get("/mbank-card-blockades", response_model=TransactionsResponse)
async def mbank_card_blockades():
    async with Application(mbank_settings) as app:
        session = await app.get_session()
        accounts = await app.get_all_transactions(session, transaction_status="PDNG")
    return TransactionsResponse(accounts=accounts)


@app.get("/santander-transactions", response_model=TransactionsResponse)
async def santander_transactions(
    date_from: str | None = Query(default=None, description="Date to fetch transactions from (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="Date to fetch transactions to (YYYY-MM-DD)"),
):
    psu_headers = {
        "Psu-Ip-Address": public_ip,
        "Psu-User-Agent": random.choice(PSU_USER_AGENTS),
    }
    async with Application(santander_settings, extra_headers=psu_headers) as app:
        session = await app.get_session()
        accounts = await app.get_all_transactions(session, transaction_status="BOOK", date_from=date_from, date_to=date_to)
    return TransactionsResponse(accounts=accounts)


@app.get("/mbank-transactions", response_model=TransactionsResponse)
async def mbank_transactions(
    date_from: str | None = Query(default=None, description="Date to fetch transactions from (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="Date to fetch transactions to (YYYY-MM-DD)"),
):
    async with Application(mbank_settings) as app:
        session = await app.get_session()
        accounts = await app.get_all_transactions(session, transaction_status="BOOK", date_from=date_from, date_to=date_to)
    return TransactionsResponse(accounts=accounts)
