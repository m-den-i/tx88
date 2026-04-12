# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`tx88` is a Python 3.13 FastAPI service that fetches bank transaction data from the [Enable Banking API](https://enablebanking.com/) (Santander, mBank) and exposes balance/transaction endpoints.

- `server.py` — FastAPI app, JWT auth, aiohttp API client, `/santander-balance` and `/mbank-balance` endpoints
- `transaction_converter.py` — Pydantic models for transactions + CSV export logic
- `settings.py` / `redislib.py` — Settings/secrets loading via Redis
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
SANTANDER_CONFIG_PATH=config.json
SANTANDER_SESSION_UUID=<uuid>
MBANK_SESSION_UUID=<uuid>
REDIS_READER_SETTINGS='{"redis_url": "...", "storage": "tx88_secrets"}'
```

`config.json` must contain `keyPath` (path to RSA private key) and `applicationId`.

## Architecture

**Auth flow**: JWT tokens are built per-request in `build_jwt_token()` — signed with the app's RSA private key, valid for 600s. The `Application` context manager wraps an `aiohttp.ClientSession` with fresh headers.

**Lifespan**: `Settings` objects for both banks are loaded at startup via `@asynccontextmanager lifespan`. They are module-level globals (`santander_settings`, `mbank_settings`) typed `Optional[Settings]`.

**Transaction converter**: `TransactionConverter.to_csv()` flattens nested Pydantic models recursively — lists use only the first item.

## Code Conventions

- **Python 3.13**: use built-in generics (`list[str]`, `dict[str, Any]`), `X | Y` unions in new code
- **Pydantic v2**: use `model_validate()` / `model_dump()`, never v1-style `.dict()` / `.parse_obj()`
- `Decimal` for monetary amounts, never `float`
- Logger: `logging.getLogger("tx88.<module_name>")` with `%s`-style formatting
- `from __future__ import annotations` in files with forward references

## Testing Patterns

- Async tests: `@pytest.mark.asyncio` + `httpx.AsyncClient` with `ASGITransport`
- Mock external HTTP: `aioresponses` context manager
- Inject env vars: `monkeypatch.setenv()` + `importlib.reload(server)` to re-read them
- FastAPI lifespan in tests: manually call `await ctx.__aenter__()` / `await ctx.__aexit__(None, None, None)`
- Fixtures: load JSON from `fixtures/` using paths relative to `os.path.dirname(__file__)`
