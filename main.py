import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from pprint import pprint
from urllib.parse import parse_qs, urlparse

import aiohttp
from aiohttp import ClientSession

from server import MBANK_SESSION_UUID, build_jwt_token, Settings, SANTANDER_SESSION_UUID

API_ORIGIN = "https://api.enablebanking.com"
ASPSP_NAME = "Santander Bank Polska"
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

async def create_session(requests: ClientSession, base_headers: dict):
    # Requesting application details
    r = await requests.get(f"{API_ORIGIN}/application", headers=base_headers)
    if r.status == 200:
        app = await r.json()
        print("Application details:")
        pprint(app)
    else:
        print(f"Error response {r.status}:", (await r.text()))
        return

    # # Requesting available ASPSPs
    # r = requests.get(f"{API_ORIGIN}/aspsps", headers=base_headers)
    # if r.status_code == 200:
    #     print("Available ASPSPs:")
    #     # pprint(r.json()["aspsps"])
    # else:
    #     print(f"Error response {r.status_code}:", r.text)
    #     return
    #
    # # Starting authorization
    body = {
        "access": {
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
        },
        "aspsp": {"name": ASPSP_NAME, "country": ASPSP_COUNTRY},
        "state": str(uuid.uuid4()),
        "redirect_url": app["redirect_urls"][0],
        "psu_type": "personal",
    }
    r = await requests.post(f"{API_ORIGIN}/auth", json=body, headers=base_headers)
    if r.status == 200:
        auth_url = (await r.json())["url"]
        print(f"To authenticate open URL {auth_url}")
    else:
        print(f"Error response {r.status}:", r.text)
        return

    # Reading auth code and creating user session
    redirected_url = input("Paste here the URL you have been redirected to: ")
    auth_code = parse_qs(urlparse(redirected_url).query)["code"][0]
    r = await requests.post(f"{API_ORIGIN}/sessions", json={"code": auth_code}, headers=base_headers)
    if r.status == 200:
        session = await r.json()
        with open("session_s.json", "wt") as f:
            json.dump(session, f, indent=4)
        print("New user session has been created:")
        pprint(session)
    else:
        print(f"Error response {r.status}:", r.text)
        return


async def main():
    settings = await Settings.load(SANTANDER_SESSION_UUID)
    base_headers = {"Authorization": f"Bearer {build_jwt_token(settings)}"}

    async with aiohttp.ClientSession() as requests:
        r = await requests.get(f"{API_ORIGIN}/sessions/{settings.session_uuid}", headers=base_headers)

        if r.status == 200:
            print("Stored session data:")
            session = await r.json()
            pprint(session)
        else:
            print(f"Error response {r.status}:", r.text)
            return

        # Using the first available account for the following API calls
        for account_uid in session["accounts"]:
            # await retrieve_account_balances(requests, account_uid, base_headers)
            await retrieve_account_transactions(requests, account_uid, base_headers)


    print("All done!")


if __name__ == "__main__":
    asyncio.run(main())
