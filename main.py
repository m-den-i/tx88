import asyncio
import json
import uuid
from datetime import date, datetime, timezone, timedelta
from pprint import pprint
from urllib.parse import parse_qs, urlparse

import click

from eb_client import ASPSP_NAME, EnableBankingClient, BankSessionClient, BankSession, Settings
from transaction_converter import TransactionStatus

API_ORIGIN = "https://api.enablebanking.com"
ASPSP_COUNTRY = "PL"



async def _list_asps(country: str):
    settings = await Settings.load()
    async with EnableBankingClient(settings) as client:
        pprint(await client.list_asps(country))


async def _create_session(aspsp: ASPSP_NAME):
    settings = await Settings.load()
    async with EnableBankingClient(settings) as client:
        app_data = await client.get_application()
        auth_url = await client.start_auth(
            aspsp=aspsp,
            country=ASPSP_COUNTRY,
            redirect_url=app_data["redirect_urls"][0],
            state=str(uuid.uuid4()),
            access_until=(datetime.now(timezone.utc) + timedelta(days=90)).isoformat(),
        )
        click.echo(f"Open this URL to authenticate:\n{auth_url}")
        redirected_url = click.prompt("Paste the URL you were redirected to")
        auth_code = parse_qs(urlparse(redirected_url).query)["code"][0]
        session_data = await client.complete_session(auth_code)
    path = f"sessions/{aspsp.name.lower()}.json"
    with open(path, "wt") as f:
        json.dump(session_data, f, indent=4)
    click.echo(f"Session saved to {path}")
    pprint(session_data)


async def _show_session(aspsp: ASPSP_NAME):
    settings = await Settings.load()
    bank_session = BankSession.load(aspsp)
    async with BankSessionClient(settings, bank_session.session_id) as client:
        session = await client.get_session()
        click.echo(f"Accounts: {session.accounts}")
        for b in await client.get_account_balances(session):
            click.echo(f"Balances for {b['account_uid']}:")
            pprint(b["balances"])


async def _transactions(aspsp: ASPSP_NAME, date_from: str | None, date_to: str | None, status: str):
    today = date.today()
    eff_from = date_from or (today - timedelta(days=7)).isoformat()
    eff_to = date_to or today.isoformat()
    settings = await Settings.load()
    bank_session = BankSession.load(aspsp)
    async with BankSessionClient(settings, bank_session.session_id) as client:
        session = await client.get_session()
        for account_uid in session.accounts:
            txns = await client.get_account_transactions(
                account_uid, TransactionStatus(status), eff_from, eff_to
            )
            click.echo(f"Transactions for {account_uid} ({len(txns)} items):")
            pprint([t.model_dump() for t in txns])



ASPSP_CHOICES = click.Choice([a.name for a in ASPSP_NAME], case_sensitive=False)


@click.group()
def cli():
    """tx88 management CLI."""


@cli.command("list-asps")
@click.option("--country", default=ASPSP_COUNTRY, show_default=True, help="Filter by country code.")
def list_asps(country: str):
    """List available ASPSPs."""
    asyncio.run(_list_asps(country))


@cli.command("create-session")
@click.argument("aspsp", type=ASPSP_CHOICES)
def create_session(aspsp: str):
    """Create a new bank session and save it to sessions/<ASPSP>.json."""
    asyncio.run(_create_session(ASPSP_NAME[aspsp.upper()]))


@cli.command("show-session")
@click.argument("aspsp", type=ASPSP_CHOICES)
def show_session(aspsp: str):
    """Show session info and account balances for an ASPSP."""
    asyncio.run(_show_session(ASPSP_NAME[aspsp.upper()]))


@cli.command("transactions")
@click.argument("aspsp", type=ASPSP_CHOICES)
@click.option("--date-from", default=None, help="Date to fetch from (YYYY-MM-DD). Defaults to 7 days ago.")
@click.option("--date-to", default=None, help="Date to fetch to (YYYY-MM-DD). Defaults to today.")
@click.option(
    "--status",
    type=click.Choice(["BOOK", "HOLD"], case_sensitive=False),
    default="BOOK",
    show_default=True,
    help="Transaction status filter.",
)
def transactions(aspsp: str, date_from: str | None, date_to: str | None, status: str):
    """Fetch transactions for an ASPSP."""
    asyncio.run(_transactions(ASPSP_NAME[aspsp.upper()], date_from, date_to, status.upper()))


if __name__ == "__main__":
    cli()
