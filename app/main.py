#!/usr/bin/env python3
"""
SuperSet Telegram Notification Bot - Main CLI Entry Point

Unified CLI for running servers and scripts.

Usage:
    python main.py bot                     # Run Telegram bot server (commands only)
    python main.py scheduler               # Run scheduler server (scheduled jobs only)
    python main.py webhook                 # Run webhook/API server
    python main.py update                  # Fetch and process updates
    python main.py send --telegram         # Send unsent notices via Telegram
    python main.py send --web              # Send unsent notices via Web Push
    python main.py send --both             # Send via both channels
    python main.py official                # Update official placement data
    python main.py stop [bot|scheduler]    # Stop a running daemon
    python main.py status [name]           # Check status of daemons

Legacy Support:
    python main.py                         # Runs update + send (backward compatible)
"""

import argparse
import sys
import os
import logging

# Add app directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import get_settings, setup_logging, set_daemon_mode, safe_print
from core.daemon import daemonize, get_daemon_status, stop_daemon, is_running
from runners.update_runner import fetch_and_process_updates
from runners.notification_runner import send_updates


def cmd_bot(args):
    """Run Telegram bot server (without scheduler)"""
    from servers.bot_server import create_bot_server

    # Daemonize first if requested (before any other init)
    if args.daemon:
        daemonize("bot")
        get_settings.cache_clear()  # Force reload settings in daemon process
        set_daemon_mode(True)

        # Re-setup logging for the daemon process
        # The parent's handlers are invalid after fork/dup2
        # We need to force a re-initialization
        logging.root.handlers = []  # clear existing handlers
        setup_logging(get_settings())
        logging.getLogger().info(
            "Daemon process fully started and logging re-initialized"
        )

    settings = get_settings()
    server = create_bot_server(settings=settings, daemon_mode=args.daemon)
    server.run()


def cmd_scheduler(args):
    """Run scheduler server (scheduled jobs only)"""
    from servers.scheduler_server import create_scheduler_server

    # Daemonize first if requested (before any other init)
    if args.daemon:
        daemonize("scheduler")
        get_settings.cache_clear()  # Force reload settings in daemon process
        set_daemon_mode(True)

        # Re-setup logging for the daemon process
        logging.root.handlers = []  # clear existing handlers
        setup_logging(get_settings())
        logging.getLogger().info(
            "Daemon process fully started and logging re-initialized"
        )

    settings = get_settings()
    server = create_scheduler_server(settings=settings, daemon_mode=args.daemon)
    server.run()


def cmd_webhook(args):
    """Run webhook server"""
    import uvicorn
    from servers.webhook_server import create_app

    app = create_app()
    safe_print(f"Starting webhook server at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


def cmd_update_supersets(args):
    """Fetch and process updates from SuperSet"""
    result = fetch_and_process_updates()
    safe_print(f"SuperSet update complete: {result}")
    return result


def cmd_update_emails(args):
    """
    Fetch and process BOTH placement offers AND general notices from Emails.

    Orchestrator pattern:
    1. Get all unread email IDs
    2. For each email:
       a. Fetch content (don't mark read yet)
       b. Try PlacementService - if placement offer, process & save
       c. If NOT placement offer, try EmailNoticeService
       d. Mark as read after processing
    """
    from services.database_service import DatabaseService
    from services.placement_service import PlacementService
    from services.placement_notification_formatter import PlacementNotificationFormatter
    from services.google_groups_client import GoogleGroupsClient

    from services.email_notice_service import EmailNoticeService
    from services.placement_policy_service import PlacementPolicyService

    logger = logging.getLogger(__name__)
    safe_print("Starting email updates (placement offers + general notices)...")

    # Create shared dependencies
    db = DatabaseService()
    email_client = GoogleGroupsClient()
    policy_service = PlacementPolicyService(db_service=db)

    # Create services (without email_client - we'll orchestrate manually)
    notification_formatter = PlacementNotificationFormatter(db_service=db)
    placement_service = PlacementService(
        db_service=db,
        notification_formatter=notification_formatter,
        # NOTE: No email_client - we handle fetching ourselves
    )

    notice_service = EmailNoticeService(
        email_client=email_client,  # For its processing logic
        db_service=db,
        policy_service=policy_service,
    )

    logger.info("Created services for orchestrated email processing")

    # ─────────────────────────────────────────────────────────────────────────
    # Orchestrated Processing
    # ─────────────────────────────────────────────────────────────────────────
    safe_print("\n━━━ Fetching Unread Emails ━━━")
    try:
        email_ids = email_client.get_unread_message_ids()
    except Exception as e:
        safe_print(f"Error fetching email IDs: {e}")
        db.close_connection()
        return {"error": str(e)}

    safe_print(f"Found {len(email_ids)} unread emails")

    placement_count = 0
    notice_count = 0
    skipped_count = 0

    for e_id in email_ids:
        try:
            # 1. Fetch email content (without marking read)
            email_data = email_client.fetch_email(e_id, mark_as_read=False)
            if not email_data:
                safe_print(f"Failed to fetch email {e_id}, skipping")
                continue

            subject = email_data.get("subject", "Unknown")
            safe_print(f"\n📧 Processing: {subject[:60]}...")

            processed = False

            # 2. Try PlacementService first
            offer = placement_service.process_email(email_data)
            if offer:
                # It's a placement offer - save it
                safe_print(f"  ✓ Placement offer detected: {offer.company}")
                offer_data = offer.model_dump()

                try:
                    result = db.save_placement_offers([offer_data])
                    events = result.get("events", [])

                    # Create notifications
                    if events and notification_formatter:
                        notification_formatter.process_events(events, save_to_db=True)

                    placement_count += 1
                    processed = True
                except Exception as e:
                    safe_print(f"  ⚠ Error saving placement: {e}")

            # 3. If not a placement offer, try EmailNoticeService
            if not processed:
                notice_doc = notice_service.process_single_email(email_data)
                if notice_doc:
                    safe_print(f"  ✓ Notice detected: {notice_doc.type}")
                    try:
                        success, _ = db.save_notice(notice_doc.model_dump())
                        if success:
                            notice_count += 1
                            processed = True
                    except Exception as e:
                        safe_print(f"  ⚠ Error saving notice: {e}")
                else:
                    safe_print(f"  ○ Not relevant (skipped)")
                    skipped_count += 1
                    processed = True  # Mark as processed so we mark it read

            # 4. Mark as read (only if we successfully processed or determined irrelevant)
            if processed:
                email_client.mark_as_read(e_id)

        except Exception as e:
            safe_print(f"  ✗ Error processing email {e_id}: {e}")
            # Don't mark as read - will retry next time

    # ─────────────────────────────────────────────────────────────────────────
    # Summary & Cleanup
    # ─────────────────────────────────────────────────────────────────────────
    db.close_connection()

    combined_result = {
        "emails_processed": len(email_ids),
        "placements": placement_count,
        "notices": notice_count,
        "skipped": skipped_count,
    }
    safe_print(f"\n━━━ Email Update Complete ━━━")
    safe_print(f"  Placements: {placement_count}")
    safe_print(f"  Notices: {notice_count}")
    safe_print(f"  Skipped: {skipped_count}")
    return combined_result


def cmd_update(args):
    """Fetch and process updates from BOTH SuperSet and Emails"""
    safe_print("Starting FULL update (SuperSet + Emails)...")

    # Run SuperSet updates
    ss_result = cmd_update_supersets(args)

    # Run Email updates
    email_result = cmd_update_emails(args)

    safe_print("Full update sequence completed.")

    # Return combined result with all step statuses (like v2's run_update)
    return {
        "notices": ss_result.get("notices", 0) if isinstance(ss_result, dict) else 0,
        "jobs": ss_result.get("jobs", 0) if isinstance(ss_result, dict) else 0,
        "placements": email_result if email_result else False,
    }


def cmd_send(args):
    """Send unsent notices"""
    telegram = args.telegram or args.both
    web = args.web or args.both

    if not telegram and not web:
        safe_print("Error: Must specify --telegram, --web, or --both")
        sys.exit(1)

    if args.fetch:
        safe_print("Fetching new data (SuperSet + Emails)...")
        # Run full update to include placement emails
        cmd_update(args)

    result = send_updates(telegram=telegram, web=web)
    safe_print(f"Send complete: {result}")
    return result


def cmd_official(args):
    """Update official placement data"""
    from services.official_placement_service import OfficialPlacementService
    from services.database_service import DatabaseService

    db_service = None
    if not args.dry_run:
        db_service = DatabaseService()

    service = OfficialPlacementService(db_service=db_service)

    try:
        if args.dry_run:
            safe_print("Scraping official placement data (Dry Run)...")
            data = service.scrape()
        else:
            safe_print("Scraping and updating official placement data...")
            data = service.scrape_and_save()

        if db_service:
            db_service.close_connection()

        return data

    except Exception as e:
        safe_print(f"Error updating official placement: {e}")
        if db_service:
            db_service.close_connection()
        return None


def cmd_legacy(args):
    """Legacy mode: update + send (backward compatible with v2's main.py)"""
    safe_print("Running in legacy mode (update + send telegram)...")

    # Fetch updates (SuperSet + Emails, matching v2's run_update behavior)
    fetch_result = cmd_update(args)
    safe_print(f"Fetch: {fetch_result}")

    # Send via telegram
    send_result = send_updates(telegram=True, web=False)
    safe_print(f"Send: {send_result}")

    return {
        "fetch": fetch_result,
        "send": send_result,
    }


def cmd_stop(args):
    """Stop a running daemon (bot or scheduler)"""
    name = args.name
    if name not in ["bot", "scheduler"]:
        safe_print(f"Unknown daemon: {name}. Use 'bot' or 'scheduler'")
        sys.exit(1)

    if not is_running(name):
        safe_print(f"Daemon '{name}' is not running")
        return

    status = get_daemon_status(name)
    safe_print(f"Stopping {name} daemon (PID: {status['pid']})...")

    if stop_daemon(name):
        safe_print(f"Daemon '{name}' stopped successfully")
    else:
        safe_print(f"Failed to stop daemon '{name}'")
        sys.exit(1)


def cmd_status(args):
    """Show status of daemons"""
    names = [args.name] if args.name else ["bot", "scheduler"]

    for name in names:
        status = get_daemon_status(name)
        if status["running"]:
            safe_print(f"✓ {name}: running (PID: {status['pid']})")
        else:
            safe_print(f"✗ {name}: not running")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="""
SuperSet Telegram Notification Bot CLI
======================================

A unified CLI for managing placement notifications from SuperSet portal
and email sources. Supports multiple notification channels (Telegram, Web Push)
with dependency injection architecture for testability.
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMMANDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  SERVERS:
    bot                 Run interactive Telegram bot server (commands only)
    scheduler           Run scheduled update jobs server
    webhook             Run FastAPI webhook/REST API server

  DAEMON CONTROL:
    stop                Stop a running daemon (bot or scheduler)
    status              Show status of daemons

  DATA COLLECTION:
    update              Full update: SuperSet + Email placement data + Email notices
    update-supersets    Fetch notices/jobs from SuperSet portal (supports multiple accounts)
    update-emails       Fetch placement offers + general notices from emails (uses LLM)
    official            Scrape official JIIT placement website

  NOTIFICATIONS:
    send                Send unsent notices via Telegram/Web Push

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   # Start the Telegram bot in background (daemon mode)
  python main.py bot -d

  # Start the scheduler in background
  python main.py scheduler -d

  # Check status of all daemons
  python main.py status

  # Stop the bot daemon
  python main.py stop bot

  # Start webhook server on custom port
  python main.py webhook --port 8080

  # Full update cycle: fetch from all sources + send to Telegram
  python main.py send --telegram --fetch

  # Update only from SuperSet portal  
  python main.py update-supersets

  # Update only from placement emails (LLM-powered extraction)
  python main.py update-emails

  # Send pending notifications via both channels
  python main.py send --both

  # Verbose mode for debugging
  python main.py -v update
        """,
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Run in daemon mode (suppress stdout)",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Command to run",
    )

    # Bot command
    bot_parser = subparsers.add_parser(
        "bot",
        help="Run Telegram bot server (commands only, no scheduler)",
    )
    bot_parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Daemon mode",
    )

    # Scheduler command
    scheduler_parser = subparsers.add_parser(
        "scheduler",
        help="Run scheduler server for automated updates",
    )
    scheduler_parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Daemon mode",
    )

    # Webhook command
    webhook_parser = subparsers.add_parser(
        "webhook",
        help="Run webhook server",
    )
    webhook_parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host",
    )
    webhook_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port",
    )
    webhook_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    # Update command
    update_parser = subparsers.add_parser(
        "update",
        help="Fetch updates",
    )

    # Send command
    send_parser = subparsers.add_parser(
        "send",
        help="Send notifications",
    )
    send_parser.add_argument(
        "--telegram",
        action="store_true",
        help="Via Telegram",
    )
    send_parser.add_argument(
        "--web",
        action="store_true",
        help="Via Web Push",
    )
    send_parser.add_argument(
        "--both",
        action="store_true",
        help="Via both",
    )
    send_parser.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch first",
    )

    # Official command
    official_parser = subparsers.add_parser("official", help="Update official data")
    official_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without saving to database",
    )

    # Update Supersets command
    subparsers.add_parser(
        "update-supersets",
        help="Fetch and process updates from SuperSet",
    )

    # Update Emails command (placement offers + general notices)
    subparsers.add_parser(
        "update-emails",
        help="Fetch and process placement offers + general notices from emails",
    )

    # Stop daemon command
    stop_parser = subparsers.add_parser(
        "stop",
        help="Stop a running daemon",
    )
    stop_parser.add_argument(
        "name",
        choices=["bot", "scheduler"],
        help="Name of daemon to stop",
    )

    # Status command
    status_parser = subparsers.add_parser(
        "status",
        help="Show daemon status",
    )
    status_parser.add_argument(
        "name",
        nargs="?",
        choices=["bot", "scheduler"],
        help="Name of daemon (shows all if not specified)",
    )

    args = parser.parse_args()

    # Setup - set daemon mode BEFORE logging so it takes effect
    settings = get_settings()

    # Check daemon from global parser OR subparser (bot/scheduler)
    if args.daemon:
        set_daemon_mode(True)

    setup_logging(settings)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Dispatch command
    try:
        if args.command == "bot":
            cmd_bot(args)
        elif args.command == "scheduler":
            cmd_scheduler(args)
        elif args.command == "webhook":
            cmd_webhook(args)
        elif args.command == "update":
            cmd_update(args)
        elif args.command == "send":
            cmd_send(args)
        elif args.command == "official":
            cmd_official(args)
        elif args.command == "update-supersets":
            cmd_update_supersets(args)
        elif args.command == "update-emails":
            cmd_update_emails(args)
        elif args.command == "stop":
            cmd_stop(args)
        elif args.command == "status":
            cmd_status(args)
        else:
            # Legacy mode - no command specified
            cmd_legacy(args)

    except KeyboardInterrupt:
        safe_print("\nInterrupted by user")
        sys.exit(0)

    except Exception as e:
        logging.getLogger().error(f"Command failed: {e}", exc_info=True)
        safe_print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
