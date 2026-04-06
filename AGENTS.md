# AGENTS.md — tx88

Coding agent instructions for the `tx88` project. This file is intended for AI agents (Claude, Codex, etc.) working in this repository.

---

## Project Overview

`tx88` is a Python 3.13 FastAPI service that fetches bank transaction data from the Enable Banking API (Santander, mBank) and exposes balance/transaction endpoints. It uses `uv` for dependency and environment management.

Key files:
- `server.py` — FastAPI app, route handlers, JWT auth, aiohttp API client
- `transaction_converter.py` — Pydantic models for transactions + CSV export logic
- `settings.py` — Settings/secrets loading via Redis
- `redislib.py` — Async Redis client wrapper
- `main.py` — CLI script for manual API interaction
- `fixtures/` — JSON fixtures used in tests
- `tests/` — pytest test suite

---

## Environment Setup

This project uses **`uv`** (Astral's package manager). Do not use `pip` or `poetry` directly.

```bash
uv sync          # install all dependencies into .venv
uv run <cmd>     # run a command inside the managed venv
```

Required environment variables (normally in `.env`, never committed):
```
SANTANDER_CONFIG_PATH=config.json
SANTANDER_SESSION_UUID=<uuid>
MBANK_SESSION_UUID=<uuid>
REDIS_READER_SETTINGS='{"redis_url": "...", "storage": "tx88_secrets"}'
```

---

## Build / Run Commands

```bash
# Run the dev server locally
uv run uvicorn server:app --reload

# Run via Docker (production)
docker build -t tx88 .
docker run -p 8080:80 --env-file .env tx88
```

---

## Test Commands

**Run all tests:**
```bash
uv run pytest
```

**Run a single test file:**
```bash
uv run pytest tests/test_transaction_converter.py
uv run pytest tests/test_santander_balance.py
```

**Run a single test class:**
```bash
uv run pytest tests/test_transaction_converter.py::TestFlatten
uv run pytest tests/test_transaction_converter.py::TestToCsv
```

**Run a single test function:**
```bash
uv run pytest tests/test_transaction_converter.py::TestFlatten::test_scalar
uv run pytest tests/test_santander_balance.py::test_santander_balance_handler
```

**Run by keyword (substring match):**
```bash
uv run pytest -k "test_minimal_valid"
uv run pytest -k "flatten"
```

**Verbose output:**
```bash
uv run pytest -v
uv run pytest -v tests/test_transaction_converter.py::TestRealFixture
```

There is no separate lint or type-check command configured. No ruff, mypy, or flake8 config exists in `pyproject.toml`. Do not add linting steps unless the user requests them.

---

## Code Style Guidelines

### Python Version
- **Python 3.13** is required (`requires-python = "==3.13.*"`).
- Use modern built-in generics: `list[str]`, `dict[str, Any]`, `tuple[int, ...]` — do **not** import `List`, `Dict`, `Tuple` from `typing` for annotations (legacy style exists in `server.py` but new code should use modern syntax).
- For union types prefer `X | Y` over `Optional[X]` in new code, though `Optional[X]` is also acceptable for clarity.

### Imports
Order imports in three groups separated by blank lines:
1. Standard library (`logging`, `os`, `json`, `decimal`, `typing`, ...)
2. Third-party packages (`aiohttp`, `fastapi`, `pydantic`, `jwt`, ...)
3. Local modules (`transaction_converter`, `settings`, `redislib`, ...)

Use `from __future__ import annotations` at the top of files that use forward references in type hints (see `transaction_converter.py`).

Alias imports only when necessary to avoid name collisions (e.g., `import jwt as pyjwt`).

### Naming Conventions
- **Functions and variables**: `snake_case`
- **Classes**: `PascalCase`
- **Module-level constants**: `UPPER_SNAKE_CASE`
- **Private helpers**: prefix with `_` (e.g., `_flatten`)
- **Pydantic model classes**: suffix with `Model` for config/response schemas when disambiguation helps (e.g., `ConfigModel`, `SessionResponseModel`)

### Formatting
- No formatter (black, ruff format) is configured. Match the existing style in surrounding code.
- Indent with **4 spaces**.
- Keep lines reasonably short; no enforced column limit.
- Leave two blank lines between top-level class and function definitions.
- Leave one blank line between methods inside a class.
- Group related code with `# --- Section header ---` comments (see `transaction_converter.py`).

### Types and Pydantic
- Use **Pydantic v2** (`BaseModel`, `model_validate()`, `model_dump()`). Do not use v1-style `.dict()` or `.parse_obj()`.
- All Pydantic model fields that can be absent should default to `None` with `Optional[...]` or `... | None`.
- Required fields (no default) should be listed before optional ones.
- Use `Decimal` for monetary amounts; never use `float`.
- Use `UUID` (from `uuid`) for identifiers that are UUIDs.

### Error Handling
- In FastAPI route handlers, raise `HTTPException` with a structured `detail` dict for all error conditions:
  ```python
  raise HTTPException(
      status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
      detail={"error": "external_api_error", "status": resp.status, "text": text},
  )
  ```
- Always check HTTP response status codes explicitly; do not assume success.
- Read the response body (`await resp.text()`) before raising so it is included in the error detail.

### Async Patterns
- Use `async with aiohttp.ClientSession()` (or the `Application` context manager) for all outbound HTTP calls; never use `requests` in async code.
- Use `@asynccontextmanager` for FastAPI lifespan management.
- Module-level settings objects populated during lifespan should be typed `Optional["Settings"]` and assigned via `global`.

### Logging
- Obtain a module-level logger: `logger = logging.getLogger("tx88.<module_name>")`.
- Use `%s`-style lazy formatting in log calls: `logger.info("key=%s", value)`.
- `logging.basicConfig(level=logging.INFO)` is called once in `server.py`; do not repeat it in other modules.

---

## Testing Guidelines

### Test Structure
- Tests live in `tests/`. Mirror the source module name: `test_transaction_converter.py` for `transaction_converter.py`.
- Group related tests into **plain pytest classes** (no `unittest.TestCase`). Use a flat function for integration-style async tests.
- Place module-level fixture constants (e.g., `MINIMAL`) at the top of the test file for reuse.

### Async Tests
- Mark async test functions with `@pytest.mark.asyncio`.
- Use `httpx.AsyncClient` with `ASGITransport` for in-process FastAPI endpoint testing (no real server needed).
- Manually enter/exit the FastAPI lifespan context when testing endpoints that depend on lifespan-initialized state:
  ```python
  ctx = server.lifespan(app)
  await ctx.__aenter__()
  # ... run tests ...
  await ctx.__aexit__(None, None, None)
  ```

### Mocking
- Mock `aiohttp` external HTTP calls with `aioresponses` (context manager: `with aioresponses() as mocked:`).
- Use `monkeypatch.setenv(...)` to inject required environment variables in tests.
- Use `importlib.reload(server)` after patching env vars to ensure the module re-reads them.
- Load JSON fixture files from the `fixtures/` directory using paths derived from `os.path.dirname(__file__)`.

### Fixture Files
- `fixtures/session.json` — mocked Enable Banking sessions response
- `fixtures/balances.json` — mocked Enable Banking balances response
- `fixtures/resp_*.json` — real transaction response payloads used for integration tests
