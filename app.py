import json
import logging
import os
import time
from typing import List
from uuid import UUID

logger = logging.getLogger("tx88.app")

import aiohttp
import jwt as pyjwt
from fastapi import HTTPException, status
from pydantic import BaseModel

from transaction_converter import Transaction, TransactionStatus

API_ORIGIN = "https://api.enablebanking.com"


class ConfigModel(BaseModel):
    keyPath: str
    applicationId: str


class Settings:
    """Holds application configuration loaded from files."""

    def __init__(self, application_id: str, app_private_key: str, session_uuid: str):
        self.application_id: str = application_id
        self.app_private_key: str = app_private_key
        self.session_uuid: str = session_uuid

    @classmethod
    async def load(cls, session_uuid: str, config_path: str | None = None) -> "Settings":
        if config_path is None:
            config_path = os.environ["SANTANDER_CONFIG_PATH"]
        with open(config_path, "rt", encoding="utf-8") as f:
            cfg_data = json.load(f)
        cfg = ConfigModel.model_validate(cfg_data)
        key_path = cfg.keyPath
        if not os.path.isabs(key_path):
            key_path = os.path.join(os.path.dirname(config_path), key_path)
        with open(key_path, "r", encoding="utf-8") as f:
            private_key = f.read()
        return cls(
            application_id=cfg.applicationId,
            app_private_key=private_key,
            session_uuid=session_uuid,
        )


class SessionResponseModel(BaseModel):
    accounts: List[str]


class AccountTransactionsResponse(BaseModel):
    account_uid: UUID
    transactions: list[Transaction]


def _filter_by_date(
    transactions: list[Transaction],
    date_from: str | None,
    date_to: str | None,
) -> list[Transaction]:
    """Client-side date filter for banks that ignore date_from/date_to server-side."""
    if not date_from and not date_to:
        return transactions
    result = []
    for tx in transactions:
        if tx.booking_date is None:
            result.append(tx)
            continue
        if date_from and tx.booking_date < date_from:
            continue
        if date_to and tx.booking_date > date_to:
            continue
        result.append(tx)
    return result


def build_jwt_token(settings: Settings) -> str:
    iat = int(time.time())
    jwt_body = {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": iat, "exp": iat + 600}
    jwt_token = pyjwt.encode(jwt_body, settings.app_private_key, algorithm="RS256", headers={"kid": settings.application_id})
    if isinstance(jwt_token, bytes):
        jwt_token = jwt_token.decode()
    return jwt_token


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
        results = []
        for account_uid in session_parsed.accounts:
            async with self.client.get(f"{API_ORIGIN}/accounts/{account_uid}/balances", headers=self.headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                        detail={"error": "external_api_error", "status": resp.status, "text": text})
                bal = await resp.json()
            results.append({"account_uid": account_uid, "balances": bal})
        return results

    async def get_account_transactions(
        self,
        account_uid: str,
        transaction_status: TransactionStatus,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[Transaction]:
        params: dict = {"transaction_status": transaction_status.value}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        async with self.client.get(
            f"{API_ORIGIN}/accounts/{account_uid}/transactions",
            headers=self.headers,
            params=params,
        ) as resp:
            logger.info("EB transactions request: %s", resp.url)
            if resp.status != 200:
                text = await resp.text()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={"error": "external_api_error", "status": resp.status, "text": text},
                )
            data = await resp.json()

        transactions = [Transaction.model_validate(t) for t in data.get("transactions", [])]
        return _filter_by_date(transactions, date_from, date_to)

    async def get_all_transactions(
        self,
        session_parsed: SessionResponseModel,
        transaction_status: TransactionStatus,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[AccountTransactionsResponse]:
        results = []
        for account_uid in session_parsed.accounts:
            txns = await self.get_account_transactions(account_uid, transaction_status, date_from, date_to)
            results.append(AccountTransactionsResponse(account_uid=UUID(account_uid), transactions=txns))
        return results
