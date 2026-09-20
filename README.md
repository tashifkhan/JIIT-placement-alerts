# JIIT Placements SuperSet Telegram Notification Bot

Scrapes job postings from JIIT's SuperSet placement portal, stores them in MongoDB, and broadcasts them to registered Telegram users, so you don't have to keep refreshing the portal.

## Live bot

The bot runs at [@SupersetNotificationBot](https://t.me/SupersetNotificationBot). Send `/start` to register and you'll get job posting notifications. The companion site is [JIIT Placement Updates](https://jiit-placement-updates.tashif.codes).

## Analytics before the shutdown

![Usage analytics](https://github.com/user-attachments/assets/8d34bd22-b61e-43ab-8e5c-d72b1682b60c)

## Features

- Register with `/start`, unsubscribe with `/stop`
- Logs into SuperSet and pulls the latest job postings
- Skips duplicates by exact content match
- Reformats posts for Telegram
- Stores users and posts in MongoDB
- Updates hourly from 8 AM to 11 PM IST plus midnight, and scrapes official placement data at 12 PM
- Sends to every registered user at once
- Runs in the background with logging

## Bot commands

- `/start` register for notifications
- `/status` check your subscription
- `/placement_year` choose which placement year you follow
- `/stats` placement statistics
- `/noticestats` notice statistics
- `/web` links to JIIT tools
- `/help` show help
- `/stop` unsubscribe

## Run your own instance

The live bot above works as is. Run your own if you want to customize it or learn from it.

### Prerequisites

- Python 3.12+
- MongoDB, local or Atlas
- Telegram bot token
- SuperSet credentials

### Step 1: Clone the repository

```bash
git clone https://github.com/tashifkhan/placement-alerts-superset-telegram-notification-bot.git
cd placement-alerts-superset-telegram-notification-bot
```

### Step 2: Install dependencies

```bash
cd app
uv sync

# or with pip
pip install -r requirements.txt
```

### Step 3: Telegram credentials

Create a bot:

1. Message `@BotFather` on Telegram
2. Send `/newbot`
3. Pick a name when prompted
4. Copy the token BotFather returns into `.env`

Find your chat ID:

- Personal use: message `@userinfobot` and use the `user_id` it replies with as `TELEGRAM_CHAT_ID`.
- Channel or group: add the bot as an admin, post a message, then open `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` and look for `"chat":{"id":-1001234567890}`. Group and channel IDs are negative.

### Step 4: Set up MongoDB

1. Create a free [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) account
2. Create a cluster; the free tier is enough
3. Click Connect and choose "Connect your application"
4. Copy the connection string and fill in your username, password, and database name
5. Put it in `.env`

### Step 5: Configure environment variables

Copy `.env.example` to `.env` and fill in every placeholder. Protected webhook routes fail closed unless `WEBHOOK_API_KEY` is set. Admin bot commands also fail closed unless your Telegram user ID is listed in `ADMIN_TELEGRAM_USER_IDS`.

```
# MongoDB
MONGO_CONNECTION_STR=mongodb+srv://username:password@cluster.mongodb.net/database
MONGO_DATABASE_NAME=2025-26
GLOBAL_DATABASE_NAME=PlacementBotGlobal
ACTIVE_PLACEMENT_YEAR=202526
DEFAULT_PLACEMENT_YEAR=202526
PLACEMENT_YEARS=["202526", "202627"]

# Telegram Configuration
TELEGRAM_BOT_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ
TELEGRAM_CHAT_ID=your_chat_id
ADMIN_TELEGRAM_USER_IDS=[123456789]

# SuperSet credentials grouped by ingestion year
SUPERSET_CREDENTIALS=[]
SUPERSET_CREDENTIALS_BY_YEAR={"202526":[{"email":"senior@example.com","password":"replace-me"}],"202627":[{"email":"junior@example.com","password":"replace-me"}]}

# Protected webhook API
WEBHOOK_API_KEY=generate_a_long_random_secret
CORS_ORIGINS=["https://your-dashboard.example.com"]
```

#### Placement-year settings

- `PLACEMENT_YEARS` lists the years shown in the bot UI and used for notification routing.
- `SUPERSET_CREDENTIALS_BY_YEAR` lists the years that `update` and `update-supersets` scrape. Every year you want scraped needs a key here with at least one credential.
- `ACTIVE_PLACEMENT_YEAR` is the fallback year for operations.
- `DEFAULT_PLACEMENT_YEAR` is the year assigned to new users until they pick one.

Without `--year`, an update scrapes every year present in `SUPERSET_CREDENTIALS_BY_YEAR`. To scrape one year:

```bash
cd app
uv run main.py update --year 202627
```

Email ingestion reads the year from a recipient alias such as `placement+202627@example.com`. An unread email with no valid year alias goes to `ACTIVE_PLACEMENT_YEAR` unless `--year` sets another fallback.

### Step 6: Run the bot

The bot server handles user commands. The scheduler runs scraping and broadcasting on a timer. Run both for a complete setup.

```bash
cd app

python main.py bot                  # bot server, foreground
python main.py scheduler            # scheduled jobs, foreground

python main.py bot --daemon         # bot server, background
python main.py scheduler --daemon   # scheduled jobs, background
```

Daemon control:

```bash
python main.py status               # both daemons
python main.py stop bot             # stop the bot daemon
python main.py stop scheduler
```

One-off runs, useful for testing:

```bash
python main.py update               # fetch and process updates
python main.py send --telegram      # send unsent notices via Telegram
python main.py send --web           # send unsent notices via Web Push
python main.py send --both
python main.py                      # update + send (legacy)
```

### Step 7: Test the setup

```bash
cd app
pytest
```

### Step 8: Manage users

Users register and unsubscribe through the bot. Admin commands require your Telegram user ID in `ADMIN_TELEGRAM_USER_IDS`.

### Step 9: Deploy

The full guide is in [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md). On a VPS, run both daemons:

```bash
cd app
python main.py bot --daemon
python main.py scheduler --daemon
python main.py status
```

Or supervise them with PM2:

```bash
npm install -g pm2
pm2 start main.py --name superset-bot --interpreter python3.12 -- bot
pm2 start main.py --name superset-scheduler --interpreter python3.12 -- scheduler
pm2 save
pm2 startup
```

Scheduled scraping and broadcasting run inside `python main.py scheduler`. The workflow files under `.github/workflows/` are disabled (`.legacy`).

## Project structure

```
placement-alerts-superset-telegram-notification-bot/
├── app/
│   ├── clients/     # External clients (SuperSet, Google Groups, Telegram, DB)
│   ├── core/        # Settings, logging, LLM helpers, daemon utilities
│   ├── data/        # JSON fixtures and seed data
│   ├── model/       # Pydantic document models
│   ├── runners/     # Update and notification runners
│   ├── scripts/     # One-off migration scripts
│   ├── servers/     # Bot, webhook, and scheduler servers
│   ├── services/    # Business logic
│   ├── tests/       # pytest suite
│   ├── main.py      # CLI entry point
│   ├── pyproject.toml
│   └── requirements.txt
├── docs/            # Architecture, config, database, deployment docs
├── .github/workflows/
└── README.md
```

## Documentation

- [ARCHITECTURE.md](./docs/ARCHITECTURE.md)
- [CONFIGURATION.md](./docs/CONFIGURATION.md)
- [DATABASE.md](./docs/DATABASE.md)
- [NOTICES_AND_JOBS.md](./docs/NOTICES_AND_JOBS.md)
- [OFFICIAL_SCRAPER.md](./docs/OFFICIAL_SCRAPER.md)
- [STATS.md](./docs/STATS.md)
- [DEPLOYMENT.md](./docs/DEPLOYMENT.md)
- [API.md](./docs/API.md)
- [TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md)
- [DEVELOPMENT.md](./docs/DEVELOPMENT.md)

## Logging

Logs live in `logs/` at the repo root. Foreground runs print to the console and append to `logs/superset_bot.log`. The bot daemon logs to `logs/superset_bot.log` and captures stdout in `logs/bot.log`; the scheduler daemon logs to `logs/scheduler.log`. Set `LOG_LEVEL` to `DEBUG`, `INFO`, `WARNING`, or `ERROR`.

## Roadmap

- Support placement portals beyond SuperSet
- Alert filters by company or role
- Web form for user registration

## Contributing

Pull requests are welcome.

## License

[GPL-3.0](./LICENSE)
