import os
import time
import logging
from datetime import datetime

import requests
import numpy as np
import pytz


# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("lumi")


# -----------------------------
# Config
# -----------------------------

# You can override these via Render environment variables if you want
TIMEZONE_NAME = os.getenv("LUMI_TZ", "Europe/London")
LOOP_SECONDS = int(os.getenv("LUMI_LOOP_SECONDS", "60"))  # heartbeat interval in seconds


def get_now_local():
    """Return timezone-aware datetime in configured timezone."""
    try:
        tz = pytz.timezone(TIMEZONE_NAME)
    except Exception:
        tz = pytz.timezone("Europe/London")
    return datetime.now(tz)


# -----------------------------
# Core Lumi logic (placeholder)
# -----------------------------

def run_lumi_cycle():
    """
    One unit of Lumi's work.

    This is where you will eventually:
      - fetch data from APIs (requests)
      - process arrays, signals, stats (numpy)
      - send messages/alerts (e.g. Telegram, Discord, etc.)

    Right now it just logs a heartbeat and current time.
    """
    now_local = get_now_local()
    logger.info("Lumi heartbeat 💡 | Local time: %s", now_local.isoformat())

    # Example placeholder computations using numpy so the import isn't "wasted"
    # (Safe to remove when you add real logic.)
    x = np.array([1, 2, 3])
    _ = np.mean(x)  # just to show numpy is in use

    # If you later call an API, it might look like this:
    #
    # response = requests.get("https://api.example.com/ping", timeout=10)
    # logger.info("API status: %s", response.status_code)


# -----------------------------
# Main loop
# -----------------------------

def main_loop():
    logger.info("Lumi started ✅ | TZ=%s | LOOP_SECONDS=%s", TIMEZONE_NAME, LOOP_SECONDS)

    while True:
        try:
            run_lumi_cycle()
        except Exception as e:
            logger.exception("Unexpected error in Lumi cycle: %s", e)

        # Sleep between cycles so the worker stays alive but not spammy
        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Lumi stopped manually (KeyboardInterrupt).")
    except Exception as e:
        logger.exception("Fatal error in Lumi main: %s", e)
        raise