import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from enum import StrEnum
from pprint import pprint
from urllib.parse import parse_qs, urlparse

import aiohttp
from aiohttp import ClientSession

from app import build_jwt_token
from server import MBANK_SESSION_UUID, Settings


API_ORIGIN = "https://api.enablebanking.com"

class ASPSP_NAME(StrEnum):
    SANTANDER = "Santander Bank Polska"
    MBANK = "mBank"
    REVOLUT = "Revolut"

ASPSP_COUNTRY = "PL"

SESSION_UUID = MBANK_SESSION_UUID

async def retrieve_account_balances(requests: ClientSession, account_uid: str, base_headers: dict):
    r = await requests.get(f"{API_ORIGIN}/accounts/{account_uid}/balances", headers=base_headers)
    if r.status == 200:
        print("Balances:")
        pprint(await r.json())
    else:
        print(f"Error response {r.status}:", (await r.text()))
        return


async def retrieve_account_transactions(requests: ClientSession, account_uid: str, base_headers: dict, last_days: int = 7):
    now = datetime.now(timezone.utc)
    query = {
        "date_from": (now - timedelta(days=last_days)).date().isoformat(),
        "transaction_status": "HOLD",
    }
    continuation_key = None
    ind = -1
    while True:
        ind += 1
        if continuation_key:
            query["continuation_key"] = continuation_key
        r = await requests.get(
            f"{API_ORIGIN}/accounts/{account_uid}/transactions",
            params=query,
            headers=base_headers,
        )
        if r.status == 200:
            resp_data = await r.json()
            with open(f"resp_{now.isoformat()}_{account_uid}_{ind}.json", "wt") as f:
                json.dump(resp_data, f, indent=4)
            print(f"Transactions: {len(resp_data['transactions'])} items")
            continuation_key = resp_data.get("continuation_key")
            if not continuation_key:
                print("No continuation key. All transactions were fetched")
                break
            print(f"Going to fetch more transactions with continuation key {continuation_key}")
        else:
            print(f"Error response {r.status}:", (await r.text()))
            return

async def list_asps(aspsp_country: str, requests: ClientSession, base_headers: dict):
    # Requesting available ASPSPs
    r = await requests.get(f"{API_ORIGIN}/aspsps", headers=base_headers)
    if r.status == 200:
        print("Available ASPSPs:")
        result = (await r.json())["aspsps"]
        filtered = [r for r in result if r["country"] == aspsp_country]
        pprint(filtered)
    else:
        print(f"Error response {r.status}:", (await r.text()))
        return


async def create_session(aspsp: ASPSP_NAME, requests: ClientSession, base_headers: dict):
    # Requesting application details
    r = await requests.get(f"{API_ORIGIN}/application", headers=base_headers)
    if r.status == 200:
        app = await r.json()
        print("Application details:")
        pprint(app)
    else:
        print(f"Error response {r.status}:", (await r.text()))
        return

    # # Starting authorization
    body = {
        "access": {
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
        },
        "aspsp": {"name": aspsp.value, "country": ASPSP_COUNTRY},
        "state": str(uuid.uuid4()),
        "redirect_url": app["redirect_urls"][0],
        "psu_type": "personal",
    }
    r = await requests.post(f"{API_ORIGIN}/auth", json=body, headers=base_headers)
    if r.status == 200:
        auth_url = (await r.json())["url"]
        print(f"To authenticate open URL {auth_url}")
    else:
        print(f"Error response {r.status}:", await r.text())
        return

    # Reading auth code and creating user session
    redirected_url = input("Paste here the URL you have been redirected to: ")
    auth_code = parse_qs(urlparse(redirected_url).query)["code"][0]
    r = await requests.post(f"{API_ORIGIN}/sessions", json={"code": auth_code}, headers=base_headers)
    if r.status == 200:
        session = await r.json()
        with open(f"sessions/{aspsp.name.lower()}.json", "wt") as f:
            json.dump(session, f, indent=4)
        print("New user session has been created:")
        pprint(session)
    else:
        print(f"Error response {r.status}:", r.text)
        return


async def run():
    settings = await Settings.load(MBANK_SESSION_UUID)
    base_headers = {"Authorization": f"Bearer {build_jwt_token(settings)}"}

    async with aiohttp.ClientSession() as requests:
        r = await requests.get(f"{API_ORIGIN}/sessions/{settings.session_uuid}", headers=base_headers)

        if r.status == 200:
            print("Stored session data:")
            session = await r.json()
            pprint(session)
        else:
            print(f"Error response {r.status}:", await r.text())
            return

        # Using the first available account for the following API calls
        for account_uid in session["accounts"]:
            await retrieve_account_balances(requests, account_uid, base_headers)
            # await retrieve_account_transactions(requests, account_uid, base_headers)


    print("All done!")


async def run_create_session(aspsp: ASPSP_NAME):
    settings = await Settings.load(MBANK_SESSION_UUID)
    async with aiohttp.ClientSession() as requests:
        await create_session(aspsp, requests, {"Authorization": f"Bearer {build_jwt_token(settings)}"})

async def run_list_asps(aspsp_country: str):
    settings = await Settings.load(MBANK_SESSION_UUID)
    async with aiohttp.ClientSession() as requests:
        await list_asps(aspsp_country, requests, {"Authorization": f"Bearer {build_jwt_token(settings)}"})


if __name__ == "__main__":
    # asyncio.run(run_create_session(ASPSP_NAME.MBANK))
    # asyncio.run(run_list_asps(ASPSP_COUNTRY))
    asyncio.run(run())