import logging
import os
import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

import aiohttp
from fastapi import FastAPI, Query
from pydantic import BaseModel
from contextlib import asynccontextmanager

from app import Application, Settings, AccountTransactionsResponse
from transaction_converter import TransactionStatus

IPIFY_URL = "https://api.ipify.org"

PSU_USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) Chrome/104.0.0.0 Gecko/20100101 Firefox/103.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
]

logger = logging.getLogger("tx88.server")
logging.basicConfig(level=logging.INFO)

# Required env vars
SANTANDER_SESSION_UUID = os.environ["SANTANDER_SESSION_UUID"]
MBANK_SESSION_UUID = os.environ["MBANK_SESSION_UUID"]

# Module-level settings object will be assigned in lifespan
santander_settings: Optional[Settings] = None
mbank_settings: Optional[Settings] = None
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


def _psu_headers() -> dict:
    return {
        "Psu-Ip-Address": public_ip,
        "Psu-User-Agent": random.choice(PSU_USER_AGENTS),
    }


def _date_range_or_defaults(
    date_from: str | None,
    date_to: str | None,
) -> tuple[str, str]:
    today = date.today()
    return (
        date_from or (today - timedelta(days=7)).isoformat(),
        date_to or today.isoformat(),
    )


@app.get("/santander-balance")
async def santander_balance():
    async with Application(santander_settings, extra_headers=_psu_headers()) as client:
        session = await client.get_session()
        results = await client.get_account_balances(session)
    return AccountsResponse.from_eb_accounts(results)


@app.get("/mbank-balance")
async def mbank_balance():
    async with Application(mbank_settings) as client:
        session = await client.get_session()
        results = await client.get_account_balances(session)
    return AccountsResponse.from_eb_accounts(results)


@app.get("/santander-card-blockades", response_model=TransactionsResponse)
async def santander_card_blockades(
    date_from: str | None = Query(default=None, description="Date to fetch blockades from (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="Date to fetch blockades to (YYYY-MM-DD)"),
):
    eff_from, eff_to = _date_range_or_defaults(date_from, date_to)
    async with Application(santander_settings, extra_headers=_psu_headers()) as client:
        session = await client.get_session()
        accounts = await client.get_all_transactions(
            session,
            transaction_status=TransactionStatus.HOLD,
            date_from=eff_from,
            date_to=eff_to,
        )
    return TransactionsResponse(accounts=accounts)


@app.get("/mbank-card-blockades", response_model=TransactionsResponse)
async def mbank_card_blockades(
    date_from: str | None = Query(default=None, description="Date to fetch blockades from (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="Date to fetch blockades to (YYYY-MM-DD)"),
):
    eff_from, eff_to = _date_range_or_defaults(date_from, date_to)
    async with Application(mbank_settings) as client:
        session = await client.get_session()
        accounts = await client.get_all_transactions(
            session,
            transaction_status=TransactionStatus.HOLD,
            date_from=eff_from,
            date_to=eff_to,
        )
    return TransactionsResponse(accounts=accounts)


@app.get("/santander-transactions", response_model=TransactionsResponse)
async def santander_transactions(
    date_from: str | None = Query(default=None, description="Date to fetch transactions from (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="Date to fetch transactions to (YYYY-MM-DD)"),
):
    eff_from, eff_to = _date_range_or_defaults(date_from, date_to)
    async with Application(santander_settings, extra_headers=_psu_headers()) as client:
        session = await client.get_session()
        accounts = await client.get_all_transactions(
            session,
            transaction_status=TransactionStatus.BOOK,
            date_from=eff_from,
            date_to=eff_to,
        )
    return TransactionsResponse(accounts=accounts)


@app.get("/mbank-transactions", response_model=TransactionsResponse)
async def mbank_transactions(
    date_from: str | None = Query(default=None, description="Date to fetch transactions from (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="Date to fetch transactions to (YYYY-MM-DD)"),
):
    eff_from, eff_to = _date_range_or_defaults(date_from, date_to)
    async with Application(mbank_settings) as client:
        session = await client.get_session()
        accounts = await client.get_all_transactions(
            session,
            transaction_status=TransactionStatus.BOOK,
            date_from=eff_from,
            date_to=eff_to,
        )
    return TransactionsResponse(accounts=accounts)
