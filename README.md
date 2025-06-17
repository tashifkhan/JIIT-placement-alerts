# SuperSet Telegram Notification Bot

A bot that scrapes job postings from the SuperSet placement portal, saves them to MongoDB, enhances their formatting, and broadcasts them to all registered Telegram users. Eliminates the need to check the portal again and again.

## Features

- **User Registration**: Users can register via `/start` command to receive notifications
- **Automated Scraping**: Logs into SuperSet and extracts latest job postings
- **Precise Duplicate Detection**: Uses exact content matching to prevent duplicate posts
- **Enhanced Formatting**: Improves readability of job posts for Telegram
- **Database-Powered**: MongoDB-based storage for users and posts
- **Scheduled Broadcasting**: Runs automatically at 12 AM, 12 PM, and 6 PM IST
- **Multi-User Support**: Broadcasts to all registered users simultaneously
- **User Management**: Users can start/stop receiving notifications
- **Daemon Mode**: Run in background with comprehensive logging support

## Bot Commands

- `/start` - Register for job posting notifications
- `/stop` - Unsubscribe from notifications
- `/status` - Check your subscription status

## Prerequisites

- Python 3.11+
- MongoDB database
- Telegram Bot Token
- SuperSet portal credentials

## Setup Instructions

### Step 1: Clone the repository

```bash
git clone https://github.com/tashifkhan/SuperSet-telegram-notification-bot.git
cd SuperSet-telegram-notification-bot
```

### Step 2: Install dependencies

The project uses `uv` for dependency management. If you prefer pip:

```bash
# Install using pip
pip intall .

# OR using uv (recommended)
pip install uv
uv sync
```

### Step 3: Getting your Telegram credentials

#### Creating a Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow prompts to name your bot
4. BotFather will provide a bot token - copy this into your `.env` file

#### Finding your Chat ID

1. Method 1 - For personal use:

   - Message `@userinfobot` on Telegram
   - It will reply with your user_id - use this as your `TELEGRAM_CHAT_ID`

2. Method 2 - For channels/groups:
   - Add your bot to the channel/group as an admin
   - Send a message to the channel/group
   - Visit `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Find `"chat":{"id":-1001234567890}` in the response (note: group/channel IDs are negative numbers)

### Step 4: Setting up MongoDB

1. Create a free [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) account
2. Create a new cluster (free tier is sufficient)
3. Click "Connect" and select "Connect your application"
4. Copy the connection string and replace `<username>`, `<password>`, and `<dbname>` with your credentials
5. Paste the connection string into your `.env` file

### Step 5: Configure environment variables

Create a `.env` file in the project root:

```
# SuperSet Credentials
USER_ID=your_superset_email@example.com
PASSWORD=your_superset_password

# MongoDB
MONGO_CONNECTION_STR=mongodb+srv://username:password@cluster.mongodb.net/database

# Telegram Configuration
TELEGRAM_BOT_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ
TELEGRAM_CHAT_ID=your_chat_id
```

### Step 6: Running the Bot

#### Option 1: Bot Server with Scheduler (Recommended)

Start the bot server that handles user registration and runs scheduled jobs:

```bash
# Normal mode (with console output)
python app.py

# Daemon mode (background with logging)
python app.py -d
```

**Daemon Mode Features:**

- Runs in background (detached from terminal)
- All output logged to `logs/superset_bot.log`
- Perfect for production deployments
- Use `python daemon_manager.py status` to check if running

**Daemon Management:**

```bash
# Start daemon
python daemon_manager.py start

# Stop daemon
python daemon_manager.py stop

# Check status
python daemon_manager.py status

# View logs
python daemon_manager.py logs
```

This will:

- Start the Telegram bot server to handle user interactions
- Schedule automatic scraping and broadcasting 3 times a day (12 AM, 12 PM, 6 PM IST)
- Allow users to register via `/start` command

#### Option 2: One-time Run (Testing)

Run the scraping and notification process once:

```bash
python app.py --run-once
```

#### Option 3: Manual Components

Run individual components:

```bash
# Run only scraping
python -c "from main import run_scraping_only; run_scraping_only()"

# Run only formatting
python -c "from main import run_formatting_only; run_formatting_only()"

# Run only telegram sending
python -c "from main import run_telegram_only; run_telegram_only()"

# Run full pipeline once
python main.py
```

### Step 7: Testing the Setup

Run the test suite to verify everything is configured correctly:

```bash
python test_setup.py
```

### Step 8: User Management

#### View and manage users:

```bash
python manage_users.py
```

#### Bot Usage for Users:

1. Users find your bot on Telegram
2. Send `/start` to register for notifications
3. Send `/stop` to unsubscribe
4. Send `/status` to check subscription status

### Step 9: Deploy for Production

#### Option A: Local Server (Recommended for continuous operation)

1. Run the bot server on a VPS or local machine that stays online:

   ```bash
   python app.py
   ```

2. For production, use a process manager like PM2:
   ```bash
   npm install -g pm2
   pm2 start app.py --name superset-bot --interpreter python3
   ```

#### Option B: GitHub Actions (Limited - for periodic runs only)

Note: GitHub Actions has limitations for long-running bot servers. Use for scheduled jobs only.

1. Fork this repository to your GitHub account
2. Go to your repository's Settings > Secrets and variables > Actions
3. Add the following repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `MONGO_CONNECTION_STR`
   - `USER_ID` (your SuperSet email)
   - `PASSWORD` (your SuperSet password)

## Customizing GitHub Actions Schedule

The default schedule runs at 12 AM, 12 PM, and 6 PM IST. To modify:

1. Edit `.github/workflows/daily-run.yml`
2. Update the cron expressions in the `schedule` section
3. Remember GitHub Actions uses UTC time (IST is UTC+5:30)

Example for different times:

```yaml
schedule:
  # Run at 9:00 AM IST (3:30 AM UTC)
  - cron: "30 3 * * *"
  # Run at 3:00 PM IST (9:30 AM UTC)
  - cron: "30 9 * * *"
```

## Project Structure

```
SuperSet-telegram-notification-bot/
├── .github/workflows/        # GitHub Actions configuration
├── modules/                  # Core functionality
│   ├── database.py           # MongoDB interactions
│   ├── formatting.py         # Content enhancement
│   ├── telegram.py           # Telegram bot operations
│   └── webscraping.py        # Web scraping functionality
├── scripts/                  # Utility scripts
├── logs/                     # Log files (daemon mode)
├── app.py                    # Main bot server with scheduler
├── main.py                   # Core workflow orchestration
├── daemon_manager.py         # Daemon management utility
├── test_daemon.py            # Daemon functionality tests
├── DAEMON_GUIDE.md           # Detailed daemon mode documentation
├── requirements.txt          # Python dependencies
└── .env                      # Environment variables (create this)
```

## Documentation

- **[DAEMON_GUIDE.md](./DAEMON_GUIDE.md)** - Comprehensive daemon mode documentation
- **[user_guide.md](./user_guide.md)** - User interaction guide

## Logging

All operations are logged with timestamps and severity levels:

- **Normal mode**: Console + log file
- **Daemon mode**: Log file only (`logs/superset_bot.log`)

Log levels: INFO, WARNING, ERROR, DEBUG
│ ├── telegram.py # Telegram bot integration
│ └── webscraping.py # SuperSet scraping logic
├── scripts/ # Utility scripts
├── .env # Environment variables (create this)
├── main.py # Main entry point
└── README.md # Documentation

```

## Roadmap

- **MongoDB User Storage**: Store and manage user IDs in MongoDB if demand increases
- **User Management Form**: Build a web form to handle user registrations for the bot
- **VPS Hosting**: Host on a VPS for continuous operation and broadcast messaging
- **Multi-Portal Support**: Extend to other placement portals beyond SuperSet
- **Customizable Alerts**: Allow users to filter notifications by company/role
- **Analytics Dashboard**: Track job posting trends and application deadlines

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

[GLP 3](./LICENSE)
```
