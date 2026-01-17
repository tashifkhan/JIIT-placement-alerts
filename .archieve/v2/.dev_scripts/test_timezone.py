from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import time


def _format_ms_epoch_to_ist(ms, fmt="%B %d, %Y at %I:%M %p %Z"):
    if not ms:
        return "Not specified"
    try:
        ts = float(ms) / 1000.0
        dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
        ist = dt_utc.astimezone(ZoneInfo("Asia/Kolkata"))
        return ist.strftime(fmt)
    except Exception as e:
        return f"Error: {e}"


def _fmt_dt_simulated(val):
    # Simulation of the logic inside notice_formater.py
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(str(val))
        if dt.tzinfo is None:
            # This is the change we made: treat naive as IST
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))

        return dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime(
            "%B %d, %Y at %I:%M %p %Z"
        )
    except Exception as e:
        return str(e)


def test():
    print("--- Epoch Test ---")
    now_ms = int(time.time() * 1000)
    print(f"Current Epoch (ms): {now_ms}")
    print(f"Formatted IST: {_format_ms_epoch_to_ist(now_ms)}")

    print("\n--- Naive ISO String Test ---")
    naive_iso = "2023-10-27T10:00:00"
    print(f"Input: {naive_iso}")
    formatted = _fmt_dt_simulated(naive_iso)
    print(f"Formatted: {formatted}")

    if "10:00 AM IST" in formatted:
        print("PASS: Naive string treated as IST")
    else:
        print("FAIL: Naive string NOT treated as IST")


if __name__ == "__main__":
    test()
