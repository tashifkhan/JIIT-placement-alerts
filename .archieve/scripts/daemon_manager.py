#!/usr/bin/env python3
"""
Daemon Management Script for SuperSet Telegram Bot

This script provides easy commands to manage the bot daemon:
- start: Start the bot in daemon mode
- stop: Stop the daemon
- restart: Restart the daemon
- status: Check daemon status
- logs: Show recent logs
"""

import os
import sys
import subprocess
import signal
import time
import argparse
from pathlib import Path


class DaemonManager:
    def __init__(self):
        self.project_root = Path(__file__).parent
        self.pid_file = self.project_root / "superset_bot.pid"
        self.log_file = self.project_root / "logs" / "superset_bot.log"
        self.app_script = self.project_root / "app.py"

    def start(self):
        """Start the daemon"""
        if self.is_running():
            print("❌ Daemon is already running!")
            return False

        print("🚀 Starting SuperSet Bot daemon...")

        # Start the daemon process
        try:
            process = subprocess.Popen(
                [sys.executable, str(self.app_script), "-d"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Save PID
            with open(self.pid_file, "w") as f:
                f.write(str(process.pid))

            # Wait a moment to see if process started successfully
            time.sleep(2)

            if self.is_running():
                print(f"✅ Daemon started successfully (PID: {process.pid})")
                print(f"📋 Log file: {self.log_file}")
                print("💡 Use 'python daemon_manager.py logs' to view logs")
                return True
            else:
                print("❌ Failed to start daemon")
                return False

        except Exception as e:
            print(f"❌ Error starting daemon: {e}")
            return False

    def stop(self):
        """Stop the daemon"""
        if not self.is_running():
            print("⚠️  Daemon is not running")
            return True

        pid = self.get_pid()
        if pid:
            try:
                print(f"🛑 Stopping daemon (PID: {pid})...")
                os.kill(pid, signal.SIGTERM)

                # Wait for graceful shutdown
                for i in range(10):
                    if not self.is_running():
                        break
                    time.sleep(1)

                # Force kill if still running
                if self.is_running():
                    print("💥 Force killing daemon...")
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(1)

                # Clean up PID file
                if self.pid_file.exists():
                    self.pid_file.unlink()

                print("✅ Daemon stopped successfully")
                return True

            except ProcessLookupError:
                print("✅ Daemon was already stopped")
                if self.pid_file.exists():
                    self.pid_file.unlink()
                return True
            except Exception as e:
                print(f"❌ Error stopping daemon: {e}")
                return False

        return False

    def restart(self):
        """Restart the daemon"""
        print("🔄 Restarting daemon...")
        self.stop()
        time.sleep(2)
        return self.start()

    def status(self):
        """Check daemon status"""
        if self.is_running():
            pid = self.get_pid()
            print(f"✅ Daemon is running (PID: {pid})")

            # Show log file info
            if self.log_file.exists():
                stat = self.log_file.stat()
                size = stat.st_size
                mtime = time.ctime(stat.st_mtime)
                print(f"📋 Log file: {self.log_file}")
                print(f"📊 Log size: {size} bytes")
                print(f"🕐 Last modified: {mtime}")
            else:
                print("⚠️  Log file not found")
        else:
            print("❌ Daemon is not running")

    def show_logs(self, lines=50):
        """Show recent logs"""
        if not self.log_file.exists():
            print("❌ Log file not found")
            return

        try:
            # Use tail to show last N lines
            result = subprocess.run(
                ["tail", "-n", str(lines), str(self.log_file)],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                print(f"📋 Last {lines} lines from {self.log_file}:")
                print("-" * 60)
                print(result.stdout)
            else:
                print("❌ Error reading log file")

        except Exception as e:
            print(f"❌ Error showing logs: {e}")

    def is_running(self):
        """Check if daemon is running"""
        pid = self.get_pid()
        if pid:
            try:
                os.kill(pid, 0)  # Check if process exists
                return True
            except (ProcessLookupError, PermissionError):
                return False
        return False

    def get_pid(self):
        """Get daemon PID from file"""
        if self.pid_file.exists():
            try:
                with open(self.pid_file, "r") as f:
                    return int(f.read().strip())
            except (ValueError, IOError):
                return None
        return None


def main():
    parser = argparse.ArgumentParser(description="SuperSet Bot Daemon Manager")
    parser.add_argument(
        "command",
        choices=["start", "stop", "restart", "status", "logs"],
        help="Command to execute",
    )
    parser.add_argument(
        "--lines",
        "-n",
        type=int,
        default=50,
        help="Number of log lines to show (for logs command)",
    )

    args = parser.parse_args()

    manager = DaemonManager()

    if args.command == "start":
        success = manager.start()
    elif args.command == "stop":
        success = manager.stop()
    elif args.command == "restart":
        success = manager.restart()
    elif args.command == "status":
        manager.status()
        success = True
    elif args.command == "logs":
        manager.show_logs(args.lines)
        success = True

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
