"""
Daemon Utilities for Unix Process Daemonization

Provides functions for:
- Forking processes into background (true Unix daemonization)
- PID file management for process tracking
- Daemon lifecycle management (start/stop/status)
"""

import os
import sys
import signal
import atexit
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# PID directory relative to the app directory
PID_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "pids"


def get_pid_file(name: str) -> Path:
    """Get the path to a PID file for a named daemon."""
    return PID_DIR / f"{name}.pid"


def write_pid_file(name: str) -> None:
    """Write the current process PID to a file."""
    PID_DIR.mkdir(parents=True, exist_ok=True)
    pid_file = get_pid_file(name)
    pid_file.write_text(str(os.getpid()))
    logger.info(f"Wrote PID {os.getpid()} to {pid_file}")

    # Register cleanup on exit
    atexit.register(lambda: cleanup_pid_file(name))


def cleanup_pid_file(name: str) -> None:
    """Remove the PID file for a named daemon."""
    pid_file = get_pid_file(name)
    if pid_file.exists():
        pid_file.unlink()
        logger.info(f"Removed PID file {pid_file}")


def read_pid_file(name: str) -> Optional[int]:
    """Read the PID from a daemon's PID file."""
    pid_file = get_pid_file(name)
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, IOError):
        return None


def is_running(name: str) -> bool:
    """Check if a daemon is currently running."""
    pid = read_pid_file(name)
    if pid is None:
        return False

    # Check if process exists
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks
        return True
    except OSError:
        # Process doesn't exist, clean up stale PID file
        cleanup_pid_file(name)
        return False


def stop_daemon(name: str) -> bool:
    """
    Stop a running daemon by sending SIGTERM.

    Returns:
        True if daemon was stopped, False if not running
    """
    pid = read_pid_file(name)
    if pid is None:
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        logger.info(f"Sent SIGTERM to {name} daemon (PID: {pid})")

        # Wait briefly for process to terminate
        import time

        for _ in range(10):  # Wait up to 1 second
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                # Process terminated
                cleanup_pid_file(name)
                return True

        # Process didn't terminate, try SIGKILL
        logger.warning(f"Process {pid} didn't terminate, sending SIGKILL")
        os.kill(pid, signal.SIGKILL)
        cleanup_pid_file(name)
        return True

    except OSError as e:
        logger.error(f"Error stopping daemon: {e}")
        cleanup_pid_file(name)
        return False


def daemonize(name: str) -> None:
    """
    Fork the current process into a true Unix daemon.

    This performs a double-fork to:
    1. Detach from the controlling terminal
    2. Become a session leader
    3. Prevent acquiring a controlling terminal
    4. Close all open file descriptors
    5. Redirect standard streams to log file/devnumm

    Args:
        name: Name of the daemon (for PID file)
    """
    # Check if already running
    if is_running(name):
        pid = read_pid_file(name)
        print(f"Daemon '{name}' is already running (PID: {pid})")
        sys.exit(1)

    # Flush standard streams ensuring buffers are written
    sys.stdout.flush()
    sys.stderr.flush()

    # First fork - detach from parent
    try:
        pid = os.fork()
        if pid > 0:
            # Parent process - allow it to exit cleanly
            print(f"Starting {name} daemon...")
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"First fork failed: {e}\n")
        sys.exit(1)

    # Decouple from parent environment
    os.chdir("/")
    os.setsid()  # Create new session
    os.umask(0)

    # Second fork - prevent acquiring controlling terminal
    try:
        pid = os.fork()
        if pid > 0:
            # First child - exit
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"Second fork failed: {e}\n")
        sys.exit(1)

    # Now we're in the daemon process!

    # Write PID file immediately so we have a record
    # (Doing this before complex logic ensures we have a handle)
    try:
        write_pid_file(name)
    except Exception as e:
        # If we can't write PID, we shouldn't run
        sys.stderr.write(f"Failed to write PID file: {e}\n")
        sys.exit(1)

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    # Open /dev/null for stdin
    try:
        si = open(os.devnull, "r")
        os.dup2(si.fileno(), sys.stdin.fileno())
    except Exception as e:
        pass  # Best effort

    # Redirect stdout/stderr to log file
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{name}.log"

    try:
        # Open log file in append mode
        so = open(log_file, "a+")
        se = open(log_file, "a+")

        # Dup stdout and stderr to the log file
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

        # Write immediate confirmation to raw stdout (now the file)
        sys.stdout.write(f"\n--- Daemon '{name}' started at {os.getpid()} ---\n")
        sys.stdout.flush()

    except Exception as e:
        # If logging fails, we are flying blind, but try to keep running
        pass

    # Close all other file descriptors (optional but recommended for robustness)
    # This prevents holding open ports/files from parent
    try:
        import resource

        maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
        if maxfd == resource.RLIM_INFINITY:
            maxfd = 1024

        # Iterate through all possible file descriptors and close them
        # Skip 0, 1, 2 (stdin, stdout, stderr)
        for fd in range(3, maxfd):
            try:
                os.close(fd)
            except OSError:
                pass
    except Exception:
        pass

    # Re-initialize logger for this process to ensure it picks up the new file handles
    # This will be done by the caller (main.py) calling setup_logging again

    # NOTE: Do NOT log here using 'logger', as the file descriptors
    # for the old handlers have been closed!
    pass


def get_daemon_status(name: str) -> dict:
    """
    Get the status of a daemon.

    Returns:
        Dict with 'running' (bool), 'pid' (int or None), 'pid_file' (str)
    """
    pid = read_pid_file(name)
    running = is_running(name)

    return {
        "name": name,
        "running": running,
        "pid": pid if running else None,
        "pid_file": str(get_pid_file(name)),
    }
