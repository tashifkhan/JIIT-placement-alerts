# AGENTS.md - Development Guidelines for Agentic Coding

This guide provides essential information for agentic coding systems operating in the SuperSet Telegram Notification Bot repository.

## Project Overview

A Python 3.12+ bot that scrapes job postings from JIIT's SuperSet placement portal, saves them to MongoDB, and broadcasts them to registered Telegram users. Tech stack: FastAPI, Pydantic, Telegram Bot API, MongoDB, LangChain/LangGraph.

## Build, Test & Development Commands

### Environment Setup
```bash
# Install dependencies using uv (recommended)
cd app && uv sync

# Or using pip
pip install -r requirements.txt

# Source the virtual environment
source .venv/bin/activate
```

### Running the Application
```bash
# Run main entry point with available commands:
python main.py bot                    # Run Telegram bot server
python main.py webhook                # Run webhook/API server
python main.py update                 # Fetch and process job postings
python main.py send --telegram        # Send unsent notices via Telegram
python main.py send --web             # Send via Web Push
python main.py send --both            # Send via both channels
python main.py official               # Update official placement data

# Legacy (runs update + send)
python main.py
```

### Testing
```bash
# Run all tests
pytest

# Run single test file
pytest tests/test_file.py

# Run specific test
pytest tests/test_file.py::test_function_name

# Run with verbose output
pytest -v tests/

# Run with coverage
pytest --cov=. tests/
```

### Database Management
- MongoDB Atlas connection string: `MONGO_CONNECTION_STR` in `.env`
- Database name: `SupersetPlacement`
- Collections: `Notices`, `Jobs`, `PlacementOffers`, `Users`

### Environment Variables
See `/app/.env` - Required: `MONGO_CONNECTION_STR`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GOOGLE_API_KEY`, `SUPERSET_CREDENTIALS` (JSON), `PLACEMENT_EMAIL`, `PLACEMENT_PASSWORD`

## Code Style Guidelines

### Python Version & Format
- **Python Version**: 3.12+
- **Line Length**: No strict limit enforced (code examples suggest ~90-100 chars)
- **Indentation**: 4 spaces (no tabs)
- **String Quotes**: Double quotes preferred for docstrings and user-facing strings

### Imports
- Organize in three groups: standard library, third-party, local imports (separated by blank lines)
- Use explicit imports, avoid `import *`
- Sort imports alphabetically within groups
- Example:
```python
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime

from pymongo import MongoClient
from pydantic_settings import BaseSettings
from telegram import Update

from core.config import safe_print
```

### Type Hints
- Use type hints for all function parameters and return types
- Use `typing` module: `Optional`, `Dict`, `List`, `Any`, `Tuple`
- Use `|` syntax only when targeting Python 3.10+ (use `Union` for broader compatibility)
- Example:
```python
def process_notice(notice_id: str, user_count: int) -> Dict[str, Any]:
    """Process a notice for all users."""
    pass
```

### Naming Conventions
- **Classes**: PascalCase (e.g., `DatabaseService`, `NoticeFormatterService`)
- **Functions/Methods**: snake_case (e.g., `send_message`, `get_user_count`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `MAX_RETRIES`, `DEFAULT_TIMEOUT`)
- **Private Methods**: Prefix with `_` (e.g., `_validate_connection`)
- **Module Names**: snake_case (e.g., `database_service.py`, `telegram_service.py`)

### Documentation
- Use triple-quoted docstrings for modules, classes, and functions
- Include Args, Returns sections for functions
- First line is a summary (one sentence)
- Example:
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

### Class Structure
- Service classes use dependency injection (services passed to __init__)
- Logger initialized as `self.logger = logging.getLogger(self.__class__.__name__)`
- Service methods organized into logical sections with comment headers
- Example:
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

### Error Handling
- Log errors with context using `self.logger.error(msg, exc_info=True)`
- Use `safe_print()` from `core.config` for user-facing messages (handles daemon mode)
- Wrap external API calls (MongoDB, Telegram) in try-except with proper logging
- Raise meaningful exceptions with descriptive messages
- Example:
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
- Use `logging.getLogger(self.__class__.__name__)` in class constructors
- Log at appropriate levels: INFO (important actions), ERROR (failures), DEBUG (detailed traces)
- Example:
```python
self.logger.info("Successfully connected to MongoDB")
self.logger.error("Connection failed", exc_info=True)
self.logger.debug("Processing notice ID: %s", notice_id)
```

### Configuration
- Use Pydantic `BaseSettings` with `pydantic_settings` for config management
- All settings from environment variables with `Field(validation_alias="ENV_VAR_NAME")`
- Provide defaults and descriptions for all settings
- Load configuration using `@lru_cache` decorated function

### Project Structure
```
app/
├── core/              # Core config and utilities
│   └── config.py      # Pydantic Settings, logging setup
├── services/          # Service layer (business logic)
│   ├── database_service.py
│   ├── telegram_service.py
│   └── ...
├── servers/           # API/Bot servers (Flask, FastAPI, Telegram)
│   ├── bot_server.py
│   ├── webhook_server.py
│   └── ...
├── data/              # Data models and schemas
├── tests/             # Test files (pytest format)
├── main.py            # CLI entry point
├── requirements.txt   # Python dependencies
└── pyproject.toml     # Project configuration
```

### Best Practices
- Keep services focused on single responsibility
- Use type hints throughout for IDE support and clarity
- Validate user input and external data early
- Close resources properly (database connections, file handles)
- Avoid global state; use dependency injection
- Create helper methods for repeated patterns
- Add comments explaining "why" not "what"

## Key Dependencies
- **FastAPI**: Web framework for webhook server
- **python-telegram-bot**: Telegram Bot API wrapper
- **pymongo**: MongoDB driver
- **pydantic & pydantic-settings**: Data validation and config
- **langchain & langgraph**: LLM integration for notice formatting
- **apscheduler**: Job scheduling for periodic tasks
- **beautifulsoup4**: HTML parsing for scraping

## Notes for Agents
- Always check `.env` and configuration for required credentials before running
- MongoDB collections must exist; no automatic schema creation
- Telegram bot requires valid token and chat ID configured
- Service classes use explicit dependency injection - pass dependencies to __init__
- Use `safe_print()` instead of print() to handle daemon mode logging
- Run tests in `/app` directory: `cd app && pytest`
