import dotenv
import os
import re
import time
import logging
import requests
from datetime import datetime
from database import MongoDBManager
from config import safe_print
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from notice_formater import NoticeFormatter, Notice as LLMNotice, Job as LLMJob



dotenv.load_dotenv()


class TelegramBot:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
        self.db_manager = MongoDBManager()
        self.bot = (
            Bot(token=self.TELEGRAM_BOT_TOKEN) if self.TELEGRAM_BOT_TOKEN else None
        )
        self.logger.info("TelegramBot initialized")


    # Bot Command Handlers
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        chat_id = update.effective_chat.id

        # Store user information in database
        success, message = self.db_manager.add_user(
            user_id=user.id,
            chat_id=chat_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        welcome_text = []

        if success:
            if "reactivated" in message.lower():
                welcome_text.append(
                    f"Welcome back {user.first_name}! 👋\n\n"
                    "Your subscription has been reactivated!\n"
                    "You'll now receive job posting updates automatically.\n\n"
                )
            else:
                welcome_text.append(
                    f"Hello {user.first_name}! 👋\n\n"
                    "Welcome to SuperSet Placement Notifications Bot!\n"
                    "You'll receive job posting updates automatically.\n\n"
                )

            welcome_text.append(
                "<b>Commands:</b>\n"
                "  /start - Register for notifications\n"
                "  /stop - Stop receiving notifications\n"
                "  /status - Check your subscription status\n"
                "  /stats - Get Placement Statistics\n"
                "  /web - Get JIIT Suite Links\n\n"
            )

            welcome_text.append(
                "<i>btw...</i>\n"
                "here are some links you might wanna look at -\n"
                f"1. <a href='https://jiit-placement-updates.tashif.codes'>Placement Updates PWA</a>\n"
                f"2. <a href='https://jiit-timetable.tashif.codes'>Timetable</a>\n"
                f"3. <a href='https://sophos-autologin.tashif.codes'>Wifi (Sophos) Auto Login</a>\n"
                f"4. <a href='https://jportal.tashif.codes'>JPortal</a>"
            )

        else:
            if "already exists and is active" in message:
                welcome_text.append(
                    f"Hi {user.first_name}! 👋\n\n"
                    "You're already registered and active for SuperSet placement notifications.\n"
                    "You'll continue receiving job posting updates automatically.\n\n"
                )
                welcome_text += "Use /status to check your subscription details."
            else:
                welcome_text.append(
                    f"Hello {user.first_name}! 👋\n\n"
                    "There was an issue with your registration. Please try again.\n"
                )
                welcome_text.append(f"Error: {message}")

        await update.message.reply_text("".join(welcome_text), parse_mode="HTML",)
        safe_print(f"User {user.id} (@{user.username}) started the bot - {message}")

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop command"""
        user = update.effective_user

        success = self.db_manager.deactivate_user(user.id)

        if success:
            text = "You've been unsubscribed from SuperSet placement notifications.\n"
            text += "Use /start to subscribe again anytime."
        else:
            text = "There was an error unsubscribing you. Please try again."

        await update.message.reply_text(text)
        safe_print(f"User {user.id} (@{user.username}) stopped the bot")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user = update.effective_user

        user_data = self.db_manager.get_user_by_id(user.id)

        # Debug logging
        safe_print(f"Status check for user {user.id} (@{user.username})")
        safe_print(f"User data found: {user_data is not None}")
        if user_data:
            safe_print(f"User is_active: {user_data.get('is_active', 'not set')}")
            safe_print(f"User data: {user_data}")

        if user_data and user_data.get("is_active", False):
            text = "✅ You're subscribed to SuperSet placement notifications.\n"
            created_at = user_data.get("created_at")
            if created_at:
                text += f"Registered on: {created_at.strftime('%B %d, %Y')}\n"
            text += f"User ID: {user_data.get('user_id')}\n"
            text += f"Status: Active ✅"
        else:
            text = "❌ You're not subscribed to notifications.\n"
            if user_data:
                text += f"Found your account but it's marked as inactive.\n"
                text += f"User ID: {user_data.get('user_id')}\n"
            else:
                text += "No account found in our database.\n"
            text += "Use /start to subscribe."

        await update.message.reply_text(text)
        safe_print(f"Status response sent to user {user.id}")

    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command (admin only)"""
        user = update.effective_user
        chat_id = update.effective_chat.id

        try:
            stats = self.db_manager.get_placement_stats()

            if not stats or "error" in stats:
                msg = "❌ Unable to compute placement statistics."
                
                if isinstance(stats, dict) and stats.get("error"):
                    msg += f" Error: {stats.get('error')}"
                
                await update.message.reply_text(msg)
                

            text = "📊 Placement Statistics:\n\n"
            text += f"Placements processed: {stats.get('placements_count', 0)}\n"
            text += f"Total students placed: {stats.get('total_students_placed', 0)}\n"
            text += f"Average package: {stats.get('average_package', 0.0):.2f} LPA\n"
            text += f"Median package: {stats.get('median_package', 0.0):.2f} LPA\n"
            text += f"Highest package: {stats.get('highest_package', 0.0):.2f} LPA\n"
            text += f"Unique companies: {stats.get('unique_companies', 0)}\n\n"
            

            await update.message.reply_text(text)
            safe_print(f"{user.id} (@{user.username}) requested placement stats")

        except Exception as e:
            error_msg = f"Error getting placement statistics: {e}"
            await update.message.reply_text(f"❌ {error_msg}")
            safe_print(error_msg)


    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /users command (admin only)"""
        user = update.effective_user
        chat_id = update.effective_chat.id

        # Check if user is admin
        if str(chat_id) != self.TELEGRAM_CHAT_ID:
            await update.message.reply_text(
                "❌ This command is only available to administrators."
            )
            return

        try:
            users = self.db_manager.get_all_users()

            if not users:
                await update.message.reply_text("No users found in the database.")
                return

            text = "👥 User List:\n\n"
            for i, user_data in enumerate(users, 1):
                status = (
                    "✅ Active" if user_data.get("is_active", False) else "❌ Inactive"
                )
                username = user_data.get("username", "No username")
                first_name = user_data.get("first_name", "No name")
                last_name = user_data.get("last_name", "")
                user_id = user_data.get("user_id", "Unknown")

                text += f"{i}. {first_name} {last_name} (@{username})\n"
                text += f"   ID: {user_id}\n"
                text += f"   Status: {status}\n\n"

            await update.message.reply_text(text)
            safe_print(f"Admin {user.id} (@{user.username}) requested user list")

        except Exception as e:
            error_msg = f"Error getting user list: {e}"
            await update.message.reply_text(f"❌ {error_msg}")
            safe_print(error_msg)


    async def boo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /boo command (admin only) for broadcasting messages"""
        user = update.effective_user
        chat_id = update.effective_chat.id

        # Check if user is admin
        if str(chat_id) != self.TELEGRAM_CHAT_ID:
            await update.message.reply_text(
                "❌ This command is only available to administrators."
            )
            return

        # Get the full message text
        message_text = update.message.text.strip()

        # Remove the /boo command
        message_text = message_text.replace("/boo", "").strip()

        if not message_text:
            await update.message.reply_text(
                "❌ Please provide a message to send.\n"
                "Usage:\n"
                "- /boo broadcast <message> - Send to all users\n"
                "- /boo <chat_id> <message> - Send to specific user"
            )
            return

        # Check if it's a broadcast message
        if message_text.lower().startswith("broadcast"):
            # Remove "broadcast" from the message
            broadcast_message = message_text.replace("broadcast", "", 1).strip()
            if not broadcast_message:
                await update.message.reply_text(
                    "❌ Please provide a message to broadcast."
                )
                return

            # Send broadcast message
            success = self.broadcast_to_all_users(broadcast_message)
            if success:
                await update.message.reply_text("✅ Message broadcasted successfully!")
            else:
                await update.message.reply_text("❌ Failed to broadcast message.")
            return

        # Try to parse as targeted message
        try:
            # Split into chat_id and message
            parts = message_text.split(" ", 1)
            if len(parts) != 2:
                await update.message.reply_text(
                    "❌ Invalid format. Use:\n"
                    "- /boo broadcast <message> - Send to all users\n"
                    "- /boo <chat_id> <message> - Send to specific user"
                )
                return

            target_chat_id, target_message = parts

            # Send to specific user
            url = f"https://api.telegram.org/bot{self.TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": target_chat_id,
                "text": target_message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }

            response = requests.post(url, json=payload)

            if response.status_code == 200:
                await update.message.reply_text(
                    f"✅ Message sent to user {target_chat_id}"
                )
            else:
                error_msg = f"Failed to send message: {response.text}"
                await update.message.reply_text(f"❌ {error_msg}")
                safe_print(error_msg)

        except Exception as e:
            error_msg = f"Error sending message: {e}"
            await update.message.reply_text(f"❌ {error_msg}")
            safe_print(error_msg)

    async def scrapyyy_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle /scrapyyy command (admin only): run main.py workflow"""
        user = update.effective_user
        chat_id = update.effective_chat.id

        # Check if user is admin
        if str(chat_id) != self.TELEGRAM_CHAT_ID:
            await update.message.reply_text(
                "❌ This command is only available to administrators."
            )
            return

        await update.message.reply_text("⏳ Running main workflow (main.py)...")
        
        try:
            # call main.py's main to refresh data (scraping)
            from main import main as run_main_process

            # main() here is the scraper/orchestrator; try calling with daemon_mode
            try:
                result = run_main_process(daemon_mode=True)
            
            except TypeError:
                # fallback to calling without args
                result = run_main_process()

            if result == 0:
                await update.message.reply_text(
                    "✅ main.py workflow completed successfully!"
                )
            else:
                await update.message.reply_text(
                    f"⚠️ main.py workflow completed with issues (exit code: {result})"
                )
        
        except Exception as e:
            await update.message.reply_text(f"❌ Error running main.py workflow: {e}")

    async def logs_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /logs command (admin only): send last 100 lines of logs in formatted format"""
        user = update.effective_user
        chat_id = update.effective_chat.id

        # Check if user is admin
        if str(chat_id) != self.TELEGRAM_CHAT_ID:
            await update.message.reply_text(
                "❌ This command is only available to administrators."
            )
            return

        log_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "logs",
            "superset_bot.log",
        )
        if not os.path.exists(log_path):
            await update.message.reply_text("❌ Log file not found.")
            return

        try:
            with open(log_path, "r") as f:
                lines = f.readlines()
            last_lines = lines[-100:] if len(lines) >= 100 else lines

            # Split lines into chunks of up to 4000 chars (Telegram HTML limit)
            chunks = []
            current_chunk = []
            current_length = 0
            for line in last_lines:
                line_len = len(line)
                # +20 for <pre> tags and margin
                if current_length + line_len + 20 > 4000 and current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = []
                    current_length = 0
                current_chunk.append(line)
                current_length += line_len
            if current_chunk:
                chunks.append(current_chunk)

            for chunk_lines in chunks:
                chunk_text = "".join(chunk_lines)
                chunk_html = f"<pre>{self.escape_html(chunk_text)}</pre>"
                await update.message.reply_text(
                    chunk_html, parse_mode="HTML", disable_web_page_preview=True
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Error reading log file: {e}")

    @staticmethod
    def escape_html(text):
        """Escape HTML special characters for Telegram HTML parse mode"""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def test_connection(self):
        """Test if Telegram bot is configured correctly"""
        try:
            if not self.TELEGRAM_BOT_TOKEN:
                safe_print("TELEGRAM_BOT_TOKEN not set in .env file")
                return False

            if not self.TELEGRAM_CHAT_ID:
                safe_print("TELEGRAM_CHAT_ID not set in .env file")
                return False

            return True

        except Exception as e:
            safe_print(f"Error testing Telegram connection: {e}")
            return False

    def _ts_to_int(self, val):
        """Convert various MongoDB timestamp representations to int (milliseconds).

        Accepts int, float, numeric string, or dict like {'$numberLong': '12345'}.
        Returns 0 on failure.
        """
        try:
            if isinstance(val, (int, float)):
                return int(val)
            if isinstance(val, str) and val.isdigit():
                return int(val)
            if isinstance(val, dict):
                if "$numberLong" in val:
                    return int(val["$numberLong"])
                # common nested formats
                for k in ("$date", "value"):
                    if k in val:
                        try:
                            return int(val[k])
                        except Exception:
                            pass
            return 0
        
        except Exception:
            return 0

    def send_message(self, message, parse_mode="MarkdownV2"):
        """Send a message to Telegram, automatically splitting if too long"""
        try:
            if not self.TELEGRAM_BOT_TOKEN or not self.TELEGRAM_CHAT_ID:
                safe_print("Error: Telegram bot token or chat ID not configured")
                return False

            # Check if message needs to be split
            if len(message) > 4000:
                safe_print(
                    f"Message too long ({len(message)} chars), splitting into chunks..."
                )
                chunks = self.split_long_message(message, max_length=4000)
                chunks_sent = 0

                for i, chunk in enumerate(chunks, 1):
                    safe_print(
                        f"  Sending chunk {i}/{len(chunks)} ({len(chunk)} chars)..."
                    )
                    if self._send_single_message(chunk, parse_mode):
                        chunks_sent += 1
                        if i < len(chunks):  # Don't delay after the last chunk
                            time.sleep(1)  # Rate limiting between chunks
                    else:
                        safe_print(f"  ❌ Failed to send chunk {i}/{len(chunks)}")
                        break

                success = chunks_sent == len(chunks)
                if success:
                    safe_print(f"✅ All {len(chunks)} chunks sent successfully")
                else:
                    safe_print(
                        f"⚠️  Partial send: {chunks_sent}/{len(chunks)} chunks sent"
                    )
                return success
            
            else:
                # Single message, send normally
                return self._send_single_message(message, parse_mode)

        except Exception as e:
            safe_print(f"Error sending Telegram message: {e}")
            return False

    def _send_single_message(self, message, parse_mode="MarkdownV2"):
        """Send a single message chunk to Telegram"""
        try:
            url = f"https://api.telegram.org/bot{self.TELEGRAM_BOT_TOKEN}/sendMessage"

            if parse_mode == "MarkdownV2":
                formatted_message = self.convert_markdown_to_telegram(message)
            else:
                formatted_message = message

            payload = {
                "chat_id": self.TELEGRAM_CHAT_ID,
                "text": formatted_message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }

            response = requests.post(url, json=payload)

            if response.status_code == 200:
                safe_print(
                    f"Message sent successfully (length: {len(formatted_message)} chars)"
                )
                return True
            else:
                safe_print(
                    f"Failed to send message. Status code: {response.status_code}"
                )
                safe_print(f"Response: {response.text}")

                # if MarkdownV2 fails, retry with plain text
                if parse_mode == "MarkdownV2":
                    safe_print("Retrying with plain text...")
                    return self._send_single_message(message, "")

                return False

        except Exception as e:
            safe_print(f"Error sending single Telegram message: {e}")
            # fallback plain text
            if parse_mode == "MarkdownV2":
                safe_print("Retrying with plain text...")
                return self._send_single_message(message, "")

            return False

    def send_message_html(self, message):
        """Send message using HTML formatting, automatically splitting if too long"""
        try:
            if not self.TELEGRAM_BOT_TOKEN or not self.TELEGRAM_CHAT_ID:
                safe_print("Error: Telegram bot token or chat ID not configured")
                return False

            # Check if message needs to be split
            if len(message) > 4000:
                safe_print(
                    f"HTML message too long ({len(message)} chars), splitting into chunks..."
                )
                chunks = self.split_long_message(message, max_length=4000)
                chunks_sent = 0

                for i, chunk in enumerate(chunks, 1):
                    safe_print(
                        f"  Sending HTML chunk {i}/{len(chunks)} ({len(chunk)} chars)..."
                    )
                    if self._send_single_html_message(chunk):
                        chunks_sent += 1
                        if i < len(chunks):  # Don't delay after the last chunk
                            time.sleep(1)  # Rate limiting between chunks
                    else:
                        safe_print(f"  ❌ Failed to send HTML chunk {i}/{len(chunks)}")
                        break

                success = chunks_sent == len(chunks)
                if success:
                    safe_print(f"✅ All {len(chunks)} HTML chunks sent successfully")
                else:
                    safe_print(
                        f"⚠️  Partial HTML send: {chunks_sent}/{len(chunks)} chunks sent"
                    )
                return success
            else:
                # Single message, send normally
                return self._send_single_html_message(message)

        except Exception as e:
            safe_print(f"Error sending HTML Telegram message: {e}")
            return False

    def _send_single_html_message(self, message):
        """Send a single HTML message chunk to Telegram"""
        try:
            url = f"https://api.telegram.org/bot{self.TELEGRAM_BOT_TOKEN}/sendMessage"

            html_message = self.convert_markdown_to_html(message)

            payload = {
                "chat_id": self.TELEGRAM_CHAT_ID,
                "text": html_message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }

            response = requests.post(url, json=payload)

            if response.status_code == 200:
                safe_print(
                    f"HTML message sent successfully (length: {len(html_message)} chars)"
                )
                return True
            else:
                safe_print(
                    f"Failed to send HTML message. Status code: {response.status_code}"
                )
                safe_print(f"Response: {response.text}")

                # Fallback to plain text
                payload["parse_mode"] = ""
                payload["text"] = message
                response = requests.post(url, json=payload)
                return response.status_code == 200

        except Exception as e:
            safe_print(f"Error sending single HTML Telegram message: {e}")
            return False

    def send_new_posts_from_db(self):
        """Send new posts to all registered users"""
        return self.send_new_posts_to_all_users()

    def send_markdown_file(self):
        """Legacy method - now redirects to database-based sending"""
        safe_print("Using database-based post sending instead of markdown file...")
        return self.send_new_posts_from_db()

    def split_long_message(self, message, max_length=4000):
        """Split a long message into smaller chunks while preserving markdown formatting"""
        if len(message) <= max_length:
            return [message]

        chunks = []
        lines = message.split("\n")
        current_chunk = ""

        for line in lines:
            if len(current_chunk) + len(line) + 1 > max_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = line + "\n"

                else:
                    words = line.split(" ")
                    current_line = ""

                    for word in words:
                        if len(current_line) + len(word) + 1 > max_length:
                            if current_line:
                                chunks.append(current_line.strip())
                                current_line = word + " "

                            else:
                                chunks.append(word[:max_length])
                                current_line = ""
                        else:
                            current_line += word + " "
                    if current_line:
                        current_chunk = current_line + "\n"
            else:
                current_chunk += line + "\n"

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    def escape_markdown_v2(self, text):
        """Escape special characters for Telegram MarkdownV2"""

        escape_chars = [
            "_",
            "*",
            "[",
            "]",
            "(",
            ")",
            "~",
            "`",
            ">",
            "#",
            "+",
            "-",
            "=",
            "|",
            "{",
            "}",
            ".",
            "!",
        ]

        for char in escape_chars:
            text = text.replace(char, f"\\{char}")

        return text

    def convert_markdown_to_telegram(self, text):
        """Convert standard markdown to Telegram-compatible MarkdownV2"""
        # First, handle bold text
        text = text.replace("**", "*")

        # Convert ## headers to bold
        text = re.sub(r"^##\s+(.*?)$", r"*\1*", text, flags=re.MULTILINE)
        # Convert ### headers to bold
        text = re.sub(r"^###\s+(.*?)$", r"*\1*", text, flags=re.MULTILINE)

        # Handle blockquotes (> text) - convert to italic
        text = re.sub(r"^>\s+(.*?)$", r"_\1_", text, flags=re.MULTILINE)

        # Split text into parts to avoid escaping content inside markdown
        lines = text.split("\n")
        processed_lines = []

        for line in lines:
            if line.strip():
                if "*" in line or "_" in line or "`" in line:
                    processed_lines.append(line)
                else:
                    processed_lines.append(self.escape_markdown_v2(line))
            else:
                processed_lines.append(line)

        return "\n".join(processed_lines)

    def convert_markdown_to_html(self, text):
        """Convert markdown to HTML for Telegram"""
        if not text:
            return ""

        # Add an extra blank line after Deadline lines for readability
        # (ensures a visual separation before following sections)
        text = re.sub(r"(?m)^(.*Deadline:.*)$", r"\1\n", text)

        # Convert headers to bold
        text = re.sub(r"^##\s+(.*?)$", r"<b>\1</b>", text, flags=re.MULTILINE)
        text = re.sub(r"^###\s+(.*?)$", r"<b>\1</b>", text, flags=re.MULTILINE)

        # Convert bold text **...** -> <b>...</b>
        text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)

        # Convert italic text _..._ -> <i>...</i>
        text = re.sub(r"_(.*?)_", r"<i>\1</i>", text)

        # Convert blockquotes > ... -> italic
        text = re.sub(r"^>\s+(.*?)$", r"<i>\1</i>", text, flags=re.MULTILINE)

        # Convert inline code `...` -> <code>...</code>
        text = re.sub(r"`(.*?)`", r"<code>\1</code>", text)

        # Convert single *...* (italic) to <i>...</i> but avoid touching already converted **...**
        text = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*(?!\*)", r"<i>\1</i>", text)

        # Collapse excessive blank lines to maximum two, trim edges
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return text

    def get_database_stats(self):
        """Get and display database statistics"""
        try:
            stats = self.db_manager.get_notice_stats()
            safe_print("\n📊 Database Statistics:")
            safe_print(f"   Total posts: {stats.get('total_posts', 0)}")
            safe_print(f"   Sent to Telegram: {stats.get('sent_to_telegram', 0)}")
            safe_print(f"   Pending to send: {stats.get('pending_to_send', 0)}")

            post_types = stats.get("post_types", [])
            if post_types:
                safe_print("\n   Post types distribution:")
                for pt in post_types:
                    safe_print(f"     - {pt['_id']}: {pt['count']}")

            return stats

        except Exception as e:
            safe_print(f"Error getting database stats: {e}")
            return {}

    def is_post_already_sent(self, post_id):
        """Check if a specific post has already been sent to Telegram"""
        try:
            post = self.db_manager.notices_collection.find_one({"_id": post_id})
            if post:
                return post.get("sent_to_telegram", False)

            return False

        except Exception as e:
            safe_print(f"Error checking if post was sent: {e}")
            return False

    def get_send_status_summary(self):
        """Get a summary of sending status for all posts"""
        try:
            stats = self.db_manager.get_notice_stats()
            safe_print("\n📊 Send Status Summary:")
            safe_print(f"   Total posts: {stats.get('total_posts', 0)}")
            safe_print(f"   Already sent: {stats.get('sent_to_telegram', 0)}")
            safe_print(f"   Pending to send: {stats.get('pending_to_send', 0)}")
            return stats
        except Exception as e:
            safe_print(f"Error getting send status summary: {e}")
            return {}

    def validate_and_send_post(self, post):
        """Validate a post and send it if it hasn't been sent already"""
        try:
            post_id = post["_id"]
            post_title = post.get("title", "No Title")
            post_content = post.get("content", "")

            if not post_content.strip():
                safe_print(f"⚠️  Skipping post with empty content: {post_title[:50]}...")
                return False, "Empty content"

            current_post = self.db_manager.notices_collection.find_one({"_id": post_id})
            if not current_post:
                safe_print(
                    f"⚠️  Post no longer exists in database: {post_title[:50]}..."
                )
                return False, "Post not found"

            sent_status = current_post.get("sent_to_telegram")
            if sent_status is True:
                safe_print(
                    f"⚠️  Post already marked as sent, skipping: {post_title[:50]}..."
                )
                return False, "Already sent"

            safe_print(f"Sending post: {post_title[:50]}...")

            success = False
            if len(post_content) > 4000:
                chunks = self.split_long_message(post_content)
                chunks_sent = 0

                for j, chunk in enumerate(chunks, 1):
                    safe_print(f"  Sending chunk {j}/{len(chunks)}...")
                    if self.send_message_html(chunk):
                        chunks_sent += 1
                        time.sleep(1)  # Rate limiting between chunks
                    else:
                        safe_print(f"  ❌ Failed to send chunk {j}/{len(chunks)}")
                        break

                success = chunks_sent == len(chunks)

                if not success and chunks_sent > 0:
                    safe_print(
                        f"  ⚠️  Partial send: {chunks_sent}/{len(chunks)} chunks sent"
                    )
                    return False, f"Partial send: {chunks_sent}/{len(chunks)} chunks"
            else:
                success = self.send_message_html(post_content)

            if success:

                update_result = self.db_manager.notices_collection.update_one(
                    {
                        "_id": post_id,
                        "sent_to_telegram": {"$ne": True},
                    },
                    {
                        "$set": {
                            "sent_to_telegram": True,
                            "sent_at": time.time(),
                            "updated_at": time.time(),
                        }
                    },
                )

                if update_result.modified_count > 0:
                    safe_print(f"✅ Post sent and marked in database")
                    return True, "Success"
                else:
                    safe_print(
                        f"⚠️  Post was sent but may have been marked as sent by another process"
                    )

                    current_status = self.db_manager.notices_collection.find_one(
                        {"_id": post_id}
                    )

                    if (
                        current_status
                        and current_status.get("sent_to_telegram") is True
                    ):
                        return True, "Success (already marked)"

                    else:
                        return False, "Database marking failed"

            else:
                safe_print(f"❌ Failed to send post: {post_title[:50]}...")
                return False, "Send failed"

        except Exception as e:
            safe_print(f"❌ Exception while processing post: {e}")
            return False, f"Exception: {str(e)}"

    def broadcast_to_all_users(self, message, parse_mode="HTML"):
        """Broadcast a message to all registered users, automatically splitting if too long"""
        try:
            users = self.db_manager.get_all_users()
            if not users:
                safe_print("No users found to broadcast to")
                return False

            successful_sends = 0
            failed_sends = 0

            safe_print(f"Broadcasting to {len(users)} users...")

            # Check if message needs to be split
            message_chunks = []
            if len(message) > 4000:
                safe_print(
                    f"Message too long ({len(message)} chars), splitting for broadcast..."
                )
                message_chunks = self.split_long_message(message, max_length=4000)
                safe_print(f"Split into {len(message_chunks)} chunks")
            else:
                message_chunks = [message]

            for user in users:
                try:
                    user_id = user.get("user_id")
                    username = user.get("username", "Unknown")
                    user_success = True

                    # Send all chunks to this user
                    for chunk_index, chunk in enumerate(message_chunks, 1):
                        if len(message_chunks) > 1:
                            safe_print(
                                f"  Sending chunk {chunk_index}/{len(message_chunks)} to user {user_id} (@{username})"
                            )

                        url = f"https://api.telegram.org/bot{self.TELEGRAM_BOT_TOKEN}/sendMessage"
                        payload = {
                            "chat_id": user_id,
                            "text": chunk,
                            "parse_mode": parse_mode,
                            "disable_web_page_preview": True,
                        }

                        response = requests.post(url, json=payload)

                        if response.status_code == 200:
                            if len(message_chunks) == 1:
                                safe_print(f"✅ Sent to user {user_id} (@{username})")
                        else:
                            user_success = False
                            safe_print(
                                f"❌ Failed to send chunk {chunk_index} to user {user_id} (@{username}): {response.text}"
                            )

                            # If user blocked the bot, deactivate them
                            if "blocked by the user" in response.text.lower():
                                self.db_manager.deactivate_user(user_id)
                                safe_print(f"Deactivated user {user_id} (blocked bot)")
                            break  # Don't send remaining chunks to this user

                        # Rate limiting between chunks
                        if chunk_index < len(message_chunks):
                            time.sleep(0.3)

                    if user_success:
                        successful_sends += 1
                        if len(message_chunks) > 1:
                            safe_print(
                                f"✅ All chunks sent to user {user_id} (@{username})"
                            )
                    else:
                        failed_sends += 1

                    # Rate limiting between users
                    time.sleep(0.1)

                except Exception as e:
                    failed_sends += 1
                    safe_print(
                        f"❌ Error sending to user {user.get('user_id', 'Unknown')}: {e}"
                    )

            safe_print(
                f"Broadcast complete: {successful_sends} sent, {failed_sends} failed"
            )
            return successful_sends > 0

        except Exception as e:
            safe_print(f"Error in broadcast: {e}")
            return False

    def send_new_posts_to_all_users(self):
        """Send new posts to all registered users instead of just one chat"""
        try:
            # Use Notices collection now. Fetch all notices where sent_to_telegram != True
            cursor = self.db_manager.notices_collection.find(
                {"sent_to_telegram": {"$ne": True}}
            ).sort("createdAt", -1)
            unsent_notices = list(cursor)

            if not unsent_notices:
                safe_print("No new notices to send")
                return True

            users = self.db_manager.get_all_users()
            if not users:
                safe_print("No users registered for notifications")
                return False

            safe_print(
                f"Found {len(unsent_notices)} new notices to send to {len(users)} users"
            )

            # Load jobs for formatter
            try:
                # get some job listings from DB to help formatter match
                jobs_cursor = self.db_manager.jobs_collection.find()
                jobs = list(jobs_cursor)
            except Exception:
                jobs = []

            formatter = NoticeFormatter()

            successful_notices = 0

            for notice in unsent_notices:
                try:
                    # Ensure there's a formatted_message; if not, run formatter
                    formatted = notice.get("formatted_message", "")
                    if not formatted:
                        # Convert DB notice dict to LLM Notice model
                        try:
                            llm_notice = LLMNotice(**{
                                "id": notice.get("id"),
                                "title": notice.get("title", ""),
                                "content": notice.get("content", ""),
                                "author": notice.get("author", ""),
                                "updatedAt": self._ts_to_int(notice.get("updatedAt")),
                                "createdAt": self._ts_to_int(notice.get("createdAt")),
                            })
                        except Exception:
                            # Fallback minimal mapping
                            llm_notice = LLMNotice(
                                id=str(notice.get("id")),
                                title=notice.get("title", ""),
                                content=notice.get("content", ""),
                                author=notice.get("author", ""),
                                updatedAt=self._ts_to_int(notice.get("updatedAt")),
                                createdAt=self._ts_to_int(notice.get("createdAt")),
                            )

                        # Convert jobs from DB format to LLM Job models where possible
                        llm_jobs = []
                        for j in jobs:
                            try:
                                llm_jobs.append(LLMJob(**j))
                            except Exception:
                                # ignore bad job documents
                                continue

                        enriched = formatter.format_notice(llm_notice, llm_jobs)
                        formatted = enriched.get("formatted_message")

                        # Save formatted_message back to DB for future use
                        try:
                            self.db_manager.notices_collection.update_one(
                                {"_id": notice["_id"]},
                                {
                                    "$set": {
                                        "formatted_message": formatted,
                                        "updated_at": datetime.utcnow(),
                                    }
                                },
                            )
                        except Exception as e:
                            safe_print(f"Failed to save formatted_message: {e}")

                    if not formatted or not formatted.strip():
                        safe_print(
                            f"Skipping notice with empty formatted message: {notice.get('title','No Title')[:50]}..."
                        )
                        continue

                    # Post-process formatted string to improve readability and standardize fields
                    if formatted is None:
                        formatted = ""

                    # Normalize CLASS_X -> 10th and CLASS_XII -> 12th
                    # e.g. "CLASS_X Marks: 60.0 CGPA or equivalent" -> "10th: 60.0% (or equivalent)"
                    formatted = re.sub(
                        r"CLASS[_\s]*X(?:\s*Marks)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*CGPA(?:\s*or equivalent)?",
                        r"10th: \1%",
                        formatted,
                        flags=re.IGNORECASE,
                    )
                    formatted = formatted.replace("CLASS_X Marks:", "10th Marks:")

                    formatted = re.sub(
                        r"CLASS[_\s]*XII(?:\s*Marks)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*CGPA(?:\s*or equivalent)?",
                        r"12th: \1%",
                        formatted,
                        flags=re.IGNORECASE,
                    )
                    formatted = formatted.replace("CLASS_XII Marks:", "12th Marks:")

                    # UG marks -> "UG - Current CGPA requirement: x.y"
                    formatted = re.sub(
                        r"UG(?:\s*Marks)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*CGPA(?:\s*or equivalent)?",
                        r"Current CGPA requirement: \1",
                        formatted,
                        flags=re.IGNORECASE,
                    )
                    formatted = formatted.replace("UG Marks:", "Current CGPA requirement: ")


                    formatted = formatted.replace("CGPA or equivalent", "")


                    # Replace detailed CTC / Salary Package Details block with a concise Package Description
                    # If a CTC line is present (optionally followed by a parenthetical description),
                    # keep the CTC on one line, add two newlines, then add a Package Description block.
                    formatted = re.sub(
                        r"(?:\n|^)\s*(CTC\s*:\s*([0-9]+(?:\.[0-9]+)?\s*(?:LPA|lpa|Lakh|lakh|Lakhs|lakhs)?))(?:\s*\(.*?\))?(?:\n|$)",
                        r"\n\1\n\nPackage Description:\nCTC: \2\n",
                        formatted,
                        flags=re.IGNORECASE,
                    )

                    # Ensure spacing: convert multiple blank lines to a maximum of two, strip leading/trailing whitespace
                    formatted = re.sub(r"\n{3,}", "\n\n", formatted).strip()

                    # Use HTML send to preserve formatting where possible
                    html_message = self.convert_markdown_to_html(formatted)

                    if self.broadcast_to_all_users(html_message, parse_mode="HTML"):
                        # Mark notice as sent in Notices collection
                        try:
                            self.db_manager.notices_collection.update_one(
                                {"_id": notice["_id"], "sent_to_telegram": {"$ne": True}},
                                {
                                    "$set": {
                                        "sent_to_telegram": True,
                                        "sent_at": datetime.utcnow(),
                                        "updated_at": datetime.utcnow(),
                                    }
                                },
                            )
                        except Exception as e:
                            safe_print(f"Failed to mark notice as sent: {e}")

                        successful_notices += 1
                        safe_print(
                            f"✅ Notice broadcasted and marked as sent: {notice.get('title', 'No Title')[:50]}..."
                        )
                    else:
                        safe_print(
                            f"❌ Failed to broadcast notice: {notice.get('title', 'No Title')[:50]}..."
                        )

                    time.sleep(1)

                except Exception as e:
                    safe_print(f"Exception while sending notice {notice.get('id')}: {e}")

            safe_print(
                f"Broadcast summary: {successful_notices}/{len(unsent_notices)} notices sent successfully"
            )
            return successful_notices > 0

        except Exception as e:
            safe_print(f"Error in send_new_posts_to_all_users: {e}")
            return False

    async def web_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /web command"""
        safe_print("Web command received")
        text = (
            f"<b>Jaypee Tools:</b>\n"
            f"1. <a href='https://jiit-placement-updates.tashif.codes'>Placement Updates</a>\n"
            f"2. <a href='https://jiit-timetable.tashif.codes'>Timetable</a>\n"
            f"3. <a href='https://sophos-autologin.tashif.codes'>Wifi (Sophos) Auto Login</a>\n"
            f"4. <a href='https://jportal.tashif.codes'>JPortal</a>"
        )
        try:
            await update.message.reply_text(text, parse_mode="HTML")
        except Exception as e:
            safe_print(f"Error in web_command: {e}")

    def start_bot_server(self):
        """Start the bot server to handle user interactions"""
        try:
            if not self.TELEGRAM_BOT_TOKEN:
                safe_print("TELEGRAM_BOT_TOKEN not configured")
                return False

            application = Application.builder().token(self.TELEGRAM_BOT_TOKEN).build()

            # Add command handlers
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("stop", self.stop_command))
            application.add_handler(CommandHandler("status", self.status_command))
            application.add_handler(CommandHandler("stats", self.stats_command))
            application.add_handler(CommandHandler("users", self.users_command))
            application.add_handler(CommandHandler("boo", self.boo_command))
            application.add_handler(CommandHandler("fu", self.scrapyyy_command))
            application.add_handler(CommandHandler("logs", self.logs_command))
            application.add_handler(CommandHandler("web", self.web_command))

            safe_print("Bot server starting...")
            application.run_polling(drop_pending_updates=True)

        except Exception as e:
            safe_print(f"Error starting bot server: {e}")
            return False

    def get_user_stats(self):
        """Get and display user statistics"""
        try:
            stats = self.db_manager.get_users_stats()
            safe_print("\n👥 User Statistics:")
            safe_print(f"   Total users: {stats.get('total_users', 0)}")
            safe_print(f"   Active users: {stats.get('active_users', 0)}")
            safe_print(f"   Inactive users: {stats.get('inactive_users', 0)}")
            return stats
        except Exception as e:
            safe_print(f"Error getting user stats: {e}")
            return {}

    def run(self):
        """Main method to run Telegram functionality"""
        safe_print("SuperSet Telegram Bot - Send Mode")
        safe_print("1. Testing Telegram connection...")

        if not self.test_connection():
            safe_print(
                "Please configure your Telegram bot token and chat ID in the .env file"
            )
            safe_print("To get a bot token: Message @BotFather on Telegram")
            safe_print("To get your chat ID: Message @userinfobot on Telegram")
            return False

        self.get_database_stats()
        self.get_user_stats()
        self.get_send_status_summary()

        safe_print("\n2. Sending new job posts to all registered users...")
        result = self.send_new_posts_to_all_users()

        if result:
            safe_print("\n✅ Telegram broadcasting completed successfully!")

            safe_print("\nUpdated statistics:")
            self.get_send_status_summary()
            self.get_user_stats()

        else:
            safe_print("\n❌ Telegram broadcasting failed!")

        return result
