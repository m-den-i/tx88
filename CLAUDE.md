# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`tx88` is a Python 3.13 FastAPI service that fetches bank transaction data from the [Enable Banking API](https://enablebanking.com/) (Santander, mBank) and exposes balance/transaction endpoints.

- `server.py` — FastAPI app, route handlers, lifespan
- `eb_client.py` — Enable Banking API client (`EnableBankingClient`, `BankSessionClient`), plus `Settings`/`BankSession` loaders and `ASPSP_NAME` enum
- `transaction_converter.py` — Pydantic models for transactions + CSV export logic
- `main.py` — CLI script for manual API interaction and session creation
- `fixtures/` — JSON fixtures used in tests
- `tests/` — pytest test suite

## Commands

Use `uv` (not `pip`/`poetry`) for all dependency and environment management.

```bash
uv sync                          # install dependencies into .venv
uv run uvicorn server:app --reload  # run dev server

uv run pytest                    # run all tests
uv run pytest tests/test_transaction_converter.py::TestFlatten::test_scalar  # single test
uv run pytest -k "flatten"       # by keyword
uv run pytest -v                 # verbose
```

No lint or type-check commands are configured. Do not add linting steps unless requested.

## Required Environment Variables

```
CONFIG_PATH=config.json
REDIS_READER_SETTINGS='{"redis_url": "...", "storage": "tx88_secrets"}'
```

`config.json` must contain `keyPath` (path to RSA private key) and `applicationId`.

Session UUIDs are read at startup from `sessions/<ASPSP_NAME.name.lower()>.json` (e.g. `sessions/santander.json`, `sessions/mbank.json`). Each file must contain a `session_id` field.

## Architecture

**API client**: `EnableBankingClient` handles management endpoints (`list_asps`, `get_application`, `start_auth`, `complete_session`). `BankSessionClient(EnableBankingClient)` adds session-bound endpoints (`get_session`, `get_account_balances`, `get_account_transactions`, `get_all_transactions`). Both are async context managers wrapping `aiohttp.ClientSession`. JWT tokens are minted per-instance in `build_jwt_token()` — RSA-signed, 600 s TTL.

**Lifespan**: `settings: Settings`, `bank_sessions: dict[ASPSP_NAME, BankSession]`, and `public_ip: str` are module-level globals populated at startup via `@asynccontextmanager lifespan`.

**Transaction converter**: `TransactionConverter.to_csv()` flattens nested Pydantic models recursively — lists use only the first item.

## Code Conventions

- **Python 3.13**: use built-in generics (`list[str]`, `dict[str, Any]`), `X | Y` unions in new code
- **Pydantic v2**: use `model_validate()` / `model_dump()`, never v1-style `.dict()` / `.parse_obj()`
- `Decimal` for monetary amounts, never `float`
- Logger: `logging.getLogger("tx88.<module_name>")` with `%s`-style formatting
- **Comments**: no `# --- Section ---` banners or decorative dividers. Group code by ordering and naming. Add a comment only when the *why* is non-obvious.
- **Imports**: always at module top-level. If a local import seems necessary, flag it — it usually signals a circular dependency or design issue that should be fixed instead.

## Testing Patterns

- Async tests: `@pytest.mark.asyncio` + `httpx.AsyncClient` with `ASGITransport`
- Mock external HTTP: `aioresponses` context manager
- Inject env vars: `monkeypatch.setenv()` + `importlib.reload(server)` to re-read them
- FastAPI lifespan in tests: manually call `await ctx.__aenter__()` / `await ctx.__aexit__(None, None, None)`
- Fixtures: load JSON from `fixtures/` using paths relative to `os.path.dirname(__file__)`
