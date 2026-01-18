# SuperSet Telegram Notification Bot

A modular, service-oriented notification system designed to aggregate placement updates from multiple sources (SuperSet portal, emails, official website) and distribute them via Telegram and Web Push channels.

## System Architecture

The application follows a clean, modular architecture emphasizing separation of concerns and dependency injection.

### High-Level Overview

```
[ Data Sources ]       [ Application Core ]       [ Storage ]       [ Notification Channels ]
      |                        |                      |                        |
  SuperSet Portal  --->  SupersetClientService        |                        |
      |                        |                      |                        |
    Emails         --->   PlacementService   --->  MongoDB  --->   TelegramService
      |                        |                      |                        |
 Official Website  ---> OfficialPlacementService      |                  WebPushService
```

### Dependency Injection

Dependencies are composed at the entry point (`main.py`) rather than being instantiated within services. This pattern improves testability and decouples components.

**Example Wiring:**

```python
# main.py
db_service = DatabaseService()
telegram_service = TelegramService()
notification_service = NotificationService(db_service, telegram_service)
```

## Service Documentation

The application logic is distributed across specialized services located in the `app/services/` directory.

## Email Processing Architecture (New)

The system employs a **Sequential Orchestrator Pattern** to process emails safely and reliably.

### Data Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Google IMAP   │────▶│   Orchestrator   │────▶│    MongoDB      │
│   (Gmail)       │     │   (main.py)      │     │   Database      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
          ┌─────────────────┐   ┌─────────────────────┐
          │ PlacementService│   │ EmailNoticeService  │
          │ (LLM Pipeline)  │   │ (LLM Pipeline)      │
          └─────────────────┘   └─────────────────────┘
```

### Sequential Processing Strategy

To prevent data loss during crashes, the system processes emails one by one:

1.  **Fetch IDs**: Get all unread email IDs (without marking them read).
2.  **Iterate**: For each email ID:
    a. **Fetch Content**: Retrieve subject/body.
    b. **Process (Placement)**: `PlacementService` checks if it's a placement offer. - _If Match_: Extract & Save Offer → **Mark as Read**.
    c. **Process (Notice)**: If not a placement, `EmailNoticeService` checks if it's a general notice. - _If Match_: Extract & Save Notice → **Mark as Read**.
    d. **Skip**: If neither, mark as read to avoid reprocessing.

**Key Rule**: an email is marked as read **ONLY AFTER** it has been successfully saved to the database or determined irrelevant.

---

## Service Documentation

The application logic is distributed across specialized services located in the `app/services/` directory.

### 1. DatabaseService (`services/database_service.py`)

**Role:** The core persistence layer abstraction.
**Responsibilities:**

- Manages MongoDB connections.
- Provides CRUD operations for Notices, Jobs, Placement Offers, and Users.
- Handles "upsert" logic to prevent duplicate data while allowing updates.
- **Key Feature:** The `save_placement_offers` method returns structured "events" (e.g., `new_offer`, `update_offer`) used by other services to trigger notifications.

### 2. GoogleGroupsClient (`services/google_groups_client.py`)

**Role:** IMAP Client abstraction.
**Responsibilities:**

- Fetches unread emails from Google Groups/Gmail.
- Provides granular methods: `get_unread_message_ids`, `fetch_email`, `mark_as_read`.
- Parses email bodies (HTML/Text) and extracts forwarded headers (e.g., "Date: ...").

### 3. PlacementService (`services/placement_service.py`)

**Role:** Intelligence layer for **Placement Offers**.
**Responsibilities:**

- **Pipeline:** LangGraph-based workflow.
- **Classification:** Identifies emails containing Placement Results/offers.
- **Extraction:** Extracts Company Name, Roles, Packages, and Student Lists.
- **Output:** structured `PlacementOffer` objects.

### 4. EmailNoticeService (`services/email_notice_service.py`)

**Role:** Intelligence layer for **General Notices**.
**Responsibilities:**

- **Pipeline:** LangGraph-based workflow.
- **Classification:** Identifies non-offer notices (Hackathons, Webinars, Shortlists, etc.).
- **Categories:**
  - `internship_noc`: **NEW** Extracts lists of students joining internships.
  - `announcement`, `hackathon`, `job_posting`, `shortlisting`, `update`, `webinar`.
- **Formatting:** Uses `NoticeFormatterService` to format content consistently.

### 5. PlacementNotificationFormatter (`services/placement_notification_formatter.py`)

**Role:** Bridge between structured data and user messages.
**Responsibilities:**

- Consumes "events" (New Offer, Update Offer).
- Formats messages with emojis, bold text, and lists.
- Handles logic for "New Students Added" vs "Package Update".

### 6. NoticeFormatterService (`services/notice_formatter_service.py`)

**Role:** Content enhancement for notices.
**Responsibilities:**

- Formats `EmailNoticeService` results.
- Handles `internship_noc` formatting (grouping students by company).

### 7. SupersetClientService (`services/superset_client.py`)

**Role:** Interface for the SuperSet placement portal.
**Responsibilities:**

- Authenticates with SuperSet.
- Scrapes Notices and Job Profiles.

### 8. AdminTelegramService (`services/admin_telegram_service.py`)

**Role:** Administrative interface for the bot.
**Responsibilities:**

- Handles "sudos" (admin) commands.
- Provides system statistics and user management via Telegram.
- Broadcasts announcements to all users.

### 9. PlacementStatsCalculatorService (`services/placement_stats_calculator_service.py`)

**Role:** Analytics engine.
**Responsibilities:**

- Computes aggregated placement statistics.
- Generates branch-wise, company-wise, and overall placement reports.
- Used for generating the "Stats" view in the frontend.

### 10. NotificationService (`services/notification_service.py`)

**Role:** Dispatcher.
**Responsibilities:**

- Polls for unsent notices.
- Dispatches to Telegram and Web Push.

### 11. TelegramService (`services/telegram_service.py`)

**Role:** Telegram API wrapper.
**Responsibilities:**

- Sends text messages and documents/media to the configured Telegram channel/chat.
- Handles message chunking for long content.
- Manages bot commands and updates.

### 12. WebPushService (`services/web_push_service.py`)

**Role:** Web Push Notification handler.
**Responsibilities:**

- Sends VAPID-signed push notifications to subscribed browser clients.

---

## CLI Command Reference

The application is controlled via a unified CLI entry point `main.py`.

**Usage:** `python main.py [COMMAND] [OPTIONS]`

| Command            | Description                                                         | Options                                                                                                                                 |
| :----------------- | :------------------------------------------------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------- |
| `update`           | **Full Update**: SuperSet + Emails (Placements + Notices).          | `-v, --verbose`: Enable debug logging.                                                                                                  |
| `update-emails`    | **Email Update**: Fetches Placements + General Notices from emails. | None                                                                                                                                    |
| `update-supersets` | **Portal Update**: Fetches notices from SuperSet portal.            | None                                                                                                                                    |
| `send`             | Sending engine (dispatch pending messages).                         | `--telegram`: Send via Telegram.<br>`--web`: Send via Web Push.<br>`--both`: Send via both.<br>`--fetch`: Run an update before sending. |
| `bot`              | Starts the Telegram Bot server (long-polling).                      | `--daemon`: Runs in background mode.                                                                                                    |
| `webhook`          | Starts the FastAPI Webhook server.                                  | `--port [PORT]`: Specify port (default 8000).                                                                                           |
| `official`         | Runs the official website scraper.                                  | None                                                                                                                                    |

## Configuration

Configuration is managed via environment variables (file: `.env`).

**Required Variables:**

- **Database:**
  - `MONGO_CONNECTION_STR`: MongoDB connection URI.

- **Telegram:**
  - `TELEGRAM_BOT_TOKEN`: API Token from @BotFather.
  - `TELEGRAM_CHAT_ID`: Channel or Chat ID to broadcast messages to.

- **SuperSet Credentials:**
  - `CSE_EMAIL`, `CSE_ENCRYPTION_PASSWORD`: Login for CSE account.
  - `ECE_EMAIL`, `ECE_ENCRYPTION_PASSWORD`: Login for ECE account.

- **Email Intelligence:**
  - `PLCAMENT_EMAIL`: Gmail address to monitor for placement emails.
  - `PLCAMENT_APP_PASSWORD`: Gmail App Password (IMAP access).
  - `GOOGLE_API_KEY`: API Key for Google Gemini (used for LLM extraction).

## Database Schema

The application uses MongoDB with the following collections:

1.  **Notices:** Stores all notifications (from SuperSet, Emails, etc.).
    - Fields: `id`, `title`, `content`, `source`, `sent_to_telegram` (bool).
2.  **PlacementOffers:** Stores structured data extraction from emails.
    - Fields: `company`, `role`, `package`, `students_selected` (Array).
3.  **Jobs:** Stores structured job postings from SuperSet.
4.  **OfficialPlacementData:** Stores scraped statistics from the official website.
5.  **Users:** Stores subscriber information for Web Push.

## Development Setup

1.  **Prerequisites:** Python 3.9+, MongoDB.
2.  **Install Dependencies:**
    ```bash
    uv sync
    # OR
    pip install -r requirements.txt
    ```
3.  **Setup Environment:**
    Copy `.env.example` to `.env` and fill in credentials.
4.  **Run:**
    ```bash
    python main.py update-emails
    ```
