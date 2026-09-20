# AGENTS.md

Working notes for coding agents on the SuperSet Telegram notification bot.

## Project overview

A Python 3.12+ bot that scrapes job postings from JIIT's SuperSet placement portal, saves them to MongoDB, and broadcasts them to registered Telegram users. Stack: FastAPI, Pydantic, Telegram Bot API, MongoDB, LangChain/LangGraph.

## Commands

### Setup

```bash
cd app && uv sync

# or with pip
pip install -r requirements.txt
source .venv/bin/activate
```

### Running

```bash
python main.py bot                  # Telegram bot server (commands only)
python main.py scheduler            # Scheduled jobs only
python main.py webhook              # Webhook/API server
python main.py update               # Fetch and process updates
python main.py send --telegram      # Send unsent notices via Telegram
python main.py send --web           # Send unsent notices via Web Push
python main.py send --both          # Send via both channels
python main.py official             # Update official placement data
python main.py official-seed        # Seed frozen prior-year official batches
python main.py stop [bot|scheduler] # Stop a running daemon
python main.py status [name]        # Check daemon status
python main.py                      # Legacy: update + send once
```

`bot` and `scheduler` accept `--daemon` to run in the background.

### Tests

```bash
pytest                              # all tests
pytest tests/test_file.py           # one file
pytest tests/test_file.py::test_name
pytest -v tests/
pytest --cov=. tests/
```

### Database

- Connection string: `MONGO_CONNECTION_STR` in `.env`
- Year databases are named `YYYY-YY` (compact `202526` maps to `2025-26`) and hold `Notices`, `Jobs`, `PlacementOffers`, `Policies`, `OfficialPlacementData`, `OfficialPlacementBatches`.
- The global database (`GLOBAL_DATABASE_NAME`, default `PlacementBotGlobal`) holds `Users` and `PlacementYears`.
- `DBClient(use_global_database=True)` selects the global database. `DBClient(placement_year="202526")` or `DBClient(database_name=database_name_for_year(year))` selects a year database.
- Schemas and indexes: `docs/DATABASE.md`.

### Environment variables

See `app/.env`. Required: `MONGO_CONNECTION_STR`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GOOGLE_API_KEY`, `SUPERSET_CREDENTIALS` (JSON), `PLACEMENT_EMAIL`, `PLACEMENT_PASSWORD`.

## Code style

### Python version and format

- Python 3.12+.
- 4 spaces, no tabs.
- Double quotes for docstrings and user-facing strings.
- No strict line limit, but keep lines around 90-100 characters.

### Imports

- Three groups separated by blank lines: standard library, third-party, local.
- Explicit imports only, no `import *`.
- Alphabetical within each group.

```python
import logging
import os
from datetime import datetime
from typing import Any

from pymongo import MongoClient
from pydantic_settings import BaseSettings
from telegram import Update

from core.config import safe_print
```

### Type hints

- Annotate every function parameter and return type.
- Use builtin generics and PEP 604 unions: `list[str]`, `dict[str, Any]`, `tuple[int, ...]`, `set[str]`, `type[X]`, `str | None`, `int | str`.
- Import abstract container types (`Iterable`, `Iterator`, `Sequence`, `Mapping`, `Callable`) from `collections.abc`.
- Import from `typing` only what has no builtin form: `Any`, `Literal`, `TypedDict`, `Required`, `cast`, `Protocol`, `TypeVar`, `overload`, `TYPE_CHECKING`, `Final`, `ClassVar`.

```python
def process_notice(notice_id: str, user_count: int) -> dict[str, Any]:
    """Process a notice for all users."""
    pass
```

### Naming

- Classes: PascalCase (`DatabaseService`, `NoticeFormatterService`)
- Functions and methods: snake_case (`send_message`, `get_user_count`)
- Constants: UPPER_SNAKE_CASE (`MAX_RETRIES`, `DEFAULT_TIMEOUT`)
- Private methods: leading underscore (`_validate_connection`)
- Modules: snake_case (`database_service.py`, `telegram_service.py`)

### Docstrings

Triple-quoted, with Args and Returns for functions. The first line is a one-sentence summary.

```python
def create_bot_server(settings: Settings, daemon_mode: bool) -> BotServer:
    """
    Create and configure the Telegram bot server.

    Args:
        settings: Application settings configuration
        daemon_mode: Whether to run in background daemon mode

    Returns:
        Initialized BotServer instance
    """
    pass
```

### Class layout

- Services take their dependencies in `__init__`.
- Logger: `self.logger = logging.getLogger(self.__class__.__name__)`.
- Group methods under comment headers.

```python
class SomeService:
    def __init__(self, dependency: Any):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.dependency = dependency

    # =========================================================================
    # Public Methods
    # =========================================================================

    def public_method(self) -> None:
        """Do something."""
        pass

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _private_method(self) -> None:
        """Internal helper."""
        pass
```

### Errors

- Log with context: `self.logger.error(msg, exc_info=True)`.
- Use `safe_print()` from `core.config` for user-facing output. It handles daemon mode.
- Wrap MongoDB and Telegram calls in try/except.
- Raise exceptions with descriptive messages.

```python
try:
    result = self.db.find_one({"id": doc_id})
except Exception as e:
    error_msg = f"Failed to fetch document: {e}"
    self.logger.error(error_msg, exc_info=True)
    safe_print(error_msg)
    raise
```

### Logging

- `logging.getLogger(self.__class__.__name__)` in constructors.
- INFO for actions, ERROR for failures, DEBUG for traces.

```python
self.logger.info("Successfully connected to MongoDB")
self.logger.error("Connection failed", exc_info=True)
self.logger.debug("Processing notice ID: %s", notice_id)
```

### Configuration

- Pydantic `BaseSettings` from `pydantic_settings`.
- Env vars via `Field(validation_alias="ENV_VAR_NAME")`.
- Give every setting a default and a description.
- Load settings through an `@lru_cache` function.

### Layout

```
app/
├── clients/     # External clients (SuperSet, Google Groups, Telegram, DB)
├── core/        # Settings, logging, LLM helpers, daemon utilities
├── data/        # JSON fixtures and seed data
├── model/       # Pydantic document models
├── runners/     # Update and notification runners
├── scripts/     # One-off migration scripts
├── servers/     # Bot, webhook, and scheduler servers
├── services/    # Business logic
├── tests/       # pytest suite
└── main.py      # CLI entry point
```

### Conventions

- One responsibility per service; pass dependencies in.
- Validate external data at the boundary.
- Close DB connections and file handles.
- No global state.
- Comments explain why, not what.

## Dependencies

- FastAPI for the webhook server
- python-telegram-bot for Telegram
- pymongo for MongoDB
- pydantic and pydantic-settings for models and config
- langchain and langgraph for notice formatting
- apscheduler for scheduled jobs
- beautifulsoup4 for scraping

## Notes

- Check `.env` for credentials before running anything.
- Collections must exist. Nothing creates them automatically.
- Telegram needs a valid token and chat ID.
- Services take dependencies explicitly in `__init__`.
- Use `safe_print()` instead of `print()`.
- Run tests from `app/`: `cd app && pytest`.
