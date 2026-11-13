import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI, Query
from pydantic import BaseModel

from eb_client import (
    BankSessionClient,
    Settings,
    BankSession,
    AccountTransactionsResponse,
    ASPSP_NAME,
    get_public_ip,
    BLOCKADES_STATUS_BY_ASPSP,
    extract_iban,
)
from transaction_converter import TransactionStatus

logger = logging.getLogger("tx88.server")
logging.basicConfig(level=logging.INFO)

# Module-level globals assigned in lifespan
settings: Settings
bank_sessions: dict[ASPSP_NAME, BankSession] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global settings, bank_sessions
    settings = await Settings.load()
    logger.info("Settings loaded: application_id=%s", settings.application_id)
    bank_sessions = {aspsp: BankSession.load(aspsp) for aspsp in (ASPSP_NAME.SANTANDER, ASPSP_NAME.MBANK)}
    for aspsp, bs in bank_sessions.items():
        logger.info("Session loaded: aspsp=%s session_id=%s", aspsp.name, bs.session_id)
    logger.info("Detected public IP: %s", await get_public_ip())
    yield


app = FastAPI(lifespan=lifespan)


class BalanceResponse(BaseModel):
    uuid: UUID
    balance: Decimal
    iban: str | None = None


class AccountsResponse(BaseModel):
    accounts: list[BalanceResponse]

    @classmethod
    def from_eb_accounts(
        cls,
        eb_accounts: list[dict],
        details_by_uid: dict[str, dict] | None = None,
    ) -> "AccountsResponse":
        details_by_uid = details_by_uid or {}
        accounts = []
        for acc in eb_accounts:
            uid = acc["account_uid"]
            iban = extract_iban(details_by_uid.get(uid, {}))
            for bal in acc["balances"]["balances"]:
                if bal["balance_type"] == "ITAV":
                    accounts.append(
                        BalanceResponse(
                            uuid=UUID(uid),
                            balance=Decimal(bal["balance_amount"]["amount"]),
                            iban=iban,
                        )
                    )
        return AccountsResponse.model_validate({"accounts": accounts})


class TransactionsResponse(BaseModel):
    accounts: list[AccountTransactionsResponse]


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
    async with BankSessionClient(settings, bank_sessions[ASPSP_NAME.SANTANDER].session_id) as client:
        session = await client.get_session()
        results, details_by_uid = await asyncio.gather(
            client.get_account_balances(session),
            client.get_all_account_details(session),
        )
    return AccountsResponse.from_eb_accounts(results, details_by_uid)


@app.get("/mbank-balance")
async def mbank_balance():
    async with BankSessionClient(settings, bank_sessions[ASPSP_NAME.MBANK].session_id) as client:
        session = await client.get_session()
        results, details_by_uid = await asyncio.gather(
            client.get_account_balances(session),
            client.get_all_account_details(session),
        )
    return AccountsResponse.from_eb_accounts(results, details_by_uid)


@app.get("/santander-card-blockades", response_model=TransactionsResponse)
async def santander_card_blockades(
    date_from: str | None = Query(default=None, description="Date to fetch blockades from (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="Date to fetch blockades to (YYYY-MM-DD)"),
):
    eff_from, eff_to = _date_range_or_defaults(date_from, date_to)
    async with BankSessionClient(settings, bank_sessions[ASPSP_NAME.SANTANDER].session_id) as client:
        session = await client.get_session()
        accounts = await client.get_all_transactions(
            session,
            transaction_status=BLOCKADES_STATUS_BY_ASPSP[ASPSP_NAME.SANTANDER],
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
    async with BankSessionClient(settings, bank_sessions[ASPSP_NAME.MBANK].session_id) as client:
        session = await client.get_session()
        accounts = await client.get_all_transactions(
            session,
            transaction_status=BLOCKADES_STATUS_BY_ASPSP[ASPSP_NAME.MBANK],
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
    async with BankSessionClient(settings, bank_sessions[ASPSP_NAME.SANTANDER].session_id) as client:
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
    async with BankSessionClient(settings, bank_sessions[ASPSP_NAME.MBANK].session_id) as client:
        session = await client.get_session()
        accounts = await client.get_all_transactions(
            session,
            transaction_status=TransactionStatus.BOOK,
            date_from=eff_from,
            date_to=eff_to,
        )
    return TransactionsResponse(accounts=accounts)
