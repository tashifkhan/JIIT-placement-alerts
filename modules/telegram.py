import dotenv
import os
import re
import time
import requests
from .database import MongoDBManager
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

dotenv.load_dotenv()


class TelegramBot:
    def __init__(self):
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
        self.db_manager = MongoDBManager()
        self.bot = (
            Bot(token=self.TELEGRAM_BOT_TOKEN) if self.TELEGRAM_BOT_TOKEN else None
        )

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(project_root, "output")

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        self.markdown_file = os.path.join(output_dir, "formatted_job_posts.md")

    # Bot Command Handlers
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        chat_id = update.effective_chat.id

        # Store user information in database
        success, message = self.db_manager.add_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )

        if success:
            if "reactivated" in message.lower():
                welcome_text = f"Welcome back {user.first_name}! 👋\n\n"
                welcome_text += "Your subscription has been reactivated!\n"
                welcome_text += (
                    "You'll now receive job posting updates automatically.\n\n"
                )
            else:
                welcome_text = f"Hello {user.first_name}! 👋\n\n"
                welcome_text += "Welcome to SuperSet Placement Notifications Bot!\n"
                welcome_text += "You'll receive job posting updates automatically.\n\n"

            welcome_text += "Commands:\n"
            welcome_text += "/start - Register for notifications\n"
            welcome_text += "/stop - Stop receiving notifications\n"
            welcome_text += "/status - Check your subscription status"
        else:
            if "already exists and is active" in message:
                welcome_text = f"Hi {user.first_name}! 👋\n\n"
                welcome_text += "You're already registered and active for SuperSet placement notifications.\n"
                welcome_text += (
                    "You'll continue receiving job posting updates automatically.\n\n"
                )
                welcome_text += "Use /status to check your subscription details."
            else:
                welcome_text = f"Hello {user.first_name}! 👋\n\n"
                welcome_text += (
                    "There was an issue with your registration. Please try again.\n"
                )
                welcome_text += f"Error: {message}"

        await update.message.reply_text(welcome_text)
        print(f"User {user.id} (@{user.username}) started the bot - {message}")

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
        print(f"User {user.id} (@{user.username}) stopped the bot")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user = update.effective_user

        user_data = self.db_manager.get_user_by_id(user.id)

        # Debug logging
        print(f"Status check for user {user.id} (@{user.username})")
        print(f"User data found: {user_data is not None}")
        if user_data:
            print(f"User is_active: {user_data.get('is_active', 'not set')}")
            print(f"User data: {user_data}")

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
        print(f"Status response sent to user {user.id}")

    def test_connection(self):
        """Test if Telegram bot is configured correctly"""
        try:
            if not self.TELEGRAM_BOT_TOKEN:
                print("TELEGRAM_BOT_TOKEN not set in .env file")
                return False

            if not self.TELEGRAM_CHAT_ID:
                print("TELEGRAM_CHAT_ID not set in .env file")
                return False

            return True

        except Exception as e:
            print(f"Error testing Telegram connection: {e}")
            return False

    def send_message(self, message, parse_mode="MarkdownV2"):
        """Send a single message to Telegram"""
        try:
            if not self.TELEGRAM_BOT_TOKEN or not self.TELEGRAM_CHAT_ID:
                print("Error: Telegram bot token or chat ID not configured")
                return False

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
                print(
                    f"Message sent successfully (length: {len(formatted_message)} chars)"
                )
                return True
            else:
                print(f"Failed to send message. Status code: {response.status_code}")
                print(f"Response: {response.text}")

                # if MarkdownV2 fails
                if parse_mode == "MarkdownV2":
                    print("Retrying with plain text...")
                    return self.send_message(message, parse_mode=None)

                return False

        except Exception as e:
            print(f"Error sending Telegram message: {e}")
            # fallback plain text
            if parse_mode == "MarkdownV2":
                print("Retrying with plain text...")
                return self.send_message(message, parse_mode=None)

            return False

    def send_message_html(self, message):
        """Send message using HTML formatting (more reliable than Markdown)"""
        try:
            if not self.TELEGRAM_BOT_TOKEN or not self.TELEGRAM_CHAT_ID:
                print("Error: Telegram bot token or chat ID not configured")
                return False

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
                print(
                    f"HTML message sent successfully (length: {len(html_message)} chars)"
                )
                return True

            else:
                print(
                    f"Failed to send HTML message. Status code: {response.status_code}"
                )
                print(f"Response: {response.text}")

                payload["parse_mode"] = None
                payload["text"] = message
                response = requests.post(url, json=payload)
                return response.status_code == 200

        except Exception as e:
            print(f"Error sending HTML Telegram message: {e}")
            return False

    def send_new_posts_from_db(self):
        """Send new posts to all registered users"""
        return self.send_new_posts_to_all_users()

    def send_markdown_file(self):
        """Legacy method - now redirects to database-based sending"""
        print("Using database-based post sending instead of markdown file...")
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
        # Convert headers to bold
        text = re.sub(r"^##\s+(.*?)$", r"<b>\1</b>", text, flags=re.MULTILINE)
        text = re.sub(r"^###\s+(.*?)$", r"<b>\1</b>", text, flags=re.MULTILINE)

        # Convert bold text
        text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)

        # Convert italic text
        text = re.sub(r"_(.*?)_", r"<i>\1</i>", text)

        # Convert blockquotes
        text = re.sub(r"^>\s+(.*?)$", r"<i>\1</i>", text, flags=re.MULTILINE)

        # Convert code blocks (though Telegram has limited support)
        text = re.sub(r"`(.*?)`", r"<code>\1</code>", text)

        return text

    def get_database_stats(self):
        """Get and display database statistics"""
        try:
            stats = self.db_manager.get_posts_stats()
            print("\n📊 Database Statistics:")
            print(f"   Total posts: {stats.get('total_posts', 0)}")
            print(f"   Sent to Telegram: {stats.get('sent_to_telegram', 0)}")
            print(f"   Pending to send: {stats.get('pending_to_send', 0)}")

            post_types = stats.get("post_types", [])
            if post_types:
                print("\n   Post types distribution:")
                for pt in post_types:
                    print(f"     - {pt['_id']}: {pt['count']}")

            return stats

        except Exception as e:
            print(f"Error getting database stats: {e}")
            return {}

    def is_post_already_sent(self, post_id):
        """Check if a specific post has already been sent to Telegram"""
        try:
            post = self.db_manager.collection.find_one({"_id": post_id})
            if post:
                return post.get("sent_to_telegram", False)

            return False

        except Exception as e:
            print(f"Error checking if post was sent: {e}")
            return False

    def get_send_status_summary(self):
        """Get a summary of sending status for all posts"""
        try:
            stats = self.db_manager.get_posts_stats()
            print("\n📊 Send Status Summary:")
            print(f"   Total posts: {stats.get('total_posts', 0)}")
            print(f"   Already sent: {stats.get('sent_to_telegram', 0)}")
            print(f"   Pending to send: {stats.get('pending_to_send', 0)}")
            return stats
        except Exception as e:
            print(f"Error getting send status summary: {e}")
            return {}

    def validate_and_send_post(self, post):
        """Validate a post and send it if it hasn't been sent already"""
        try:
            post_id = post["_id"]
            post_title = post.get("title", "No Title")
            post_content = post.get("content", "")

            if not post_content.strip():
                print(f"⚠️  Skipping post with empty content: {post_title[:50]}...")
                return False, "Empty content"

            current_post = self.db_manager.collection.find_one({"_id": post_id})
            if not current_post:
                print(f"⚠️  Post no longer exists in database: {post_title[:50]}...")
                return False, "Post not found"

            sent_status = current_post.get("sent_to_telegram")
            if sent_status is True:
                print(f"⚠️  Post already marked as sent, skipping: {post_title[:50]}...")
                return False, "Already sent"

            print(f"Sending post: {post_title[:50]}...")

            success = False
            if len(post_content) > 4000:
                chunks = self.split_long_message(post_content)
                chunks_sent = 0

                for j, chunk in enumerate(chunks, 1):
                    print(f"  Sending chunk {j}/{len(chunks)}...")
                    if self.send_message_html(chunk):
                        chunks_sent += 1
                        time.sleep(1)  # Rate limiting between chunks
                    else:
                        print(f"  ❌ Failed to send chunk {j}/{len(chunks)}")
                        break

                success = chunks_sent == len(chunks)

                if not success and chunks_sent > 0:
                    print(f"  ⚠️  Partial send: {chunks_sent}/{len(chunks)} chunks sent")
                    return False, f"Partial send: {chunks_sent}/{len(chunks)} chunks"
            else:
                success = self.send_message_html(post_content)

            if success:

                update_result = self.db_manager.collection.update_one(
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
                    print(f"✅ Post sent and marked in database")
                    return True, "Success"
                else:
                    print(
                        f"⚠️  Post was sent but may have been marked as sent by another process"
                    )

                    current_status = self.db_manager.collection.find_one(
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
                print(f"❌ Failed to send post: {post_title[:50]}...")
                return False, "Send failed"

        except Exception as e:
            print(f"❌ Exception while processing post: {e}")
            return False, f"Exception: {str(e)}"

    def broadcast_to_all_users(self, message, parse_mode="HTML"):
        """Broadcast a message to all registered users"""
        try:
            users = self.db_manager.get_all_users()
            if not users:
                print("No users found to broadcast to")
                return False

            successful_sends = 0
            failed_sends = 0

            print(f"Broadcasting to {len(users)} users...")

            for user in users:
                try:
                    user_id = user.get("user_id")
                    username = user.get("username", "Unknown")

                    # Send message directly to user
                    url = f"https://api.telegram.org/bot{self.TELEGRAM_BOT_TOKEN}/sendMessage"
                    payload = {
                        "chat_id": user_id,
                        "text": message,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    }

                    response = requests.post(url, json=payload)

                    if response.status_code == 200:
                        successful_sends += 1
                        print(f"✅ Sent to user {user_id} (@{username})")
                    else:
                        failed_sends += 1
                        print(
                            f"❌ Failed to send to user {user_id} (@{username}): {response.text}"
                        )

                        # If user blocked the bot, deactivate them
                        if "blocked by the user" in response.text.lower():
                            self.db_manager.deactivate_user(user_id)
                            print(f"Deactivated user {user_id} (blocked bot)")

                    # Rate limiting
                    time.sleep(0.1)

                except Exception as e:
                    failed_sends += 1
                    print(
                        f"❌ Error sending to user {user.get('user_id', 'Unknown')}: {e}"
                    )

            print(f"Broadcast complete: {successful_sends} sent, {failed_sends} failed")
            return successful_sends > 0

        except Exception as e:
            print(f"Error in broadcast: {e}")
            return False

    def send_new_posts_to_all_users(self):
        """Send new posts to all registered users instead of just one chat"""
        try:
            unsent_posts = self.db_manager.get_unsent_posts()

            if not unsent_posts:
                print("No new posts to send")
                return True

            users = self.db_manager.get_all_users()
            if not users:
                print("No users registered for notifications")
                return False

            print(f"Found {len(unsent_posts)} new posts to send to {len(users)} users")

            successful_posts = 0

            for post in unsent_posts:
                post_content = post.get("content", "")
                if not post_content.strip():
                    continue

                # Convert to HTML format
                html_message = self.convert_markdown_to_html(post_content)

                # Broadcast this post to all users
                if self.broadcast_to_all_users(html_message):
                    # Mark as sent only if successfully sent to at least some users
                    self.db_manager.mark_as_sent(post["_id"])
                    successful_posts += 1
                    print(
                        f"✅ Post broadcasted and marked as sent: {post.get('title', 'No Title')[:50]}..."
                    )
                else:
                    print(
                        f"❌ Failed to broadcast post: {post.get('title', 'No Title')[:50]}..."
                    )

                # Rate limiting between posts
                time.sleep(2)

            print(
                f"Broadcast summary: {successful_posts}/{len(unsent_posts)} posts sent successfully"
            )
            return successful_posts > 0

        except Exception as e:
            print(f"Error in send_new_posts_to_all_users: {e}")
            return False

    def start_bot_server(self):
        """Start the bot server to handle user interactions"""
        try:
            if not self.TELEGRAM_BOT_TOKEN:
                print("TELEGRAM_BOT_TOKEN not configured")
                return False

            application = Application.builder().token(self.TELEGRAM_BOT_TOKEN).build()

            # Add command handlers
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("stop", self.stop_command))
            application.add_handler(CommandHandler("status", self.status_command))

            print("Bot server starting...")
            application.run_polling(drop_pending_updates=True)

        except Exception as e:
            print(f"Error starting bot server: {e}")
            return False

    def get_user_stats(self):
        """Get and display user statistics"""
        try:
            stats = self.db_manager.get_users_stats()
            print("\n👥 User Statistics:")
            print(f"   Total users: {stats.get('total_users', 0)}")
            print(f"   Active users: {stats.get('active_users', 0)}")
            print(f"   Inactive users: {stats.get('inactive_users', 0)}")
            return stats
        except Exception as e:
            print(f"Error getting user stats: {e}")
            return {}

    def run(self):
        """Main method to run Telegram functionality"""
        print("SuperSet Telegram Bot - Send Mode")
        print("1. Testing Telegram connection...")

        if not self.test_connection():
            print(
                "Please configure your Telegram bot token and chat ID in the .env file"
            )
            print("To get a bot token: Message @BotFather on Telegram")
            print("To get your chat ID: Message @userinfobot on Telegram")
            return False

        self.get_database_stats()
        self.get_user_stats()
        self.get_send_status_summary()

        print("\n2. Sending new job posts to all registered users...")
        result = self.send_new_posts_to_all_users()

        if result:
            print("\n✅ Telegram broadcasting completed successfully!")

            print("\nUpdated statistics:")
            self.get_send_status_summary()
            self.get_user_stats()

        else:
            print("\n❌ Telegram broadcasting failed!")

        return result
