import os
import time
import pytz
import requests
import numpy as np
from datetime import datetime
from core.telegram import send_telegram_message
from core.signals import generate_signal


# ============================================================
# 1. SAFELY LOAD ENVIRONMENT VARIABLES
#    If Render fails to load them, fallback to your real keys.
# ============================================================

TD_API_KEY = os.environ.get("TD_API_KEY")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# FALLBACKS (your real keys)
if not TD_API_KEY:
    TD_API_KEY = "9ab283d3938d4a19b5481f72fa53df6b"

if not BOT_TOKEN:
    BOT_TOKEN = "7950450689:AAGPfU9IR7kgrX9eWEE2216tV4YQT8gKGqM"

if not CHAT_ID:
    CHAT_ID = "1302419329"


# ============================================================
# CONFIGURATION
# ============================================================

SYMBOL = "XAU/USD"
TIMEZONE = pytz.timezone("Europe/London")
LOOP_SECONDS = 60

TRADING_WINDOWS = [
    ("23:00", "04:30"),
    ("07:00", "11:00"),
    ("12:00", "16:30")
]


# ============================================================
# HELPER: CHECK IF CURRENT TIME IS IN TRADING WINDOW
# ============================================================

def in_trading_window():
    now = datetime.now(TIMEZONE).time()
    for start, end in TRADING_WINDOWS:
        start_t = datetime.strptime(start, "%H:%M").time()
        end_t = datetime.strptime(end, "%H:%M").time()

        if start_t <= now <= end_t:
            return True
    return False


# ============================================================
# HELPER: GET DATA FROM TWELVE DATA
# ============================================================

def get_data(interval, bars=200):
    url = (
        f"https://api.twelvedata.com/time_series"
        f"?symbol={SYMBOL.replace('/', '')}"
        f"&interval={interval}"
        f"&apikey={TD_API_KEY}"
        f"&outputsize={bars}"
    )

    r = requests.get(url).json()

    if "status" in r and r["status"] == "error":
        print(f"❌ Twelve Data error ({interval}): {r}")
        return None

    if "values" not in r:
        print(f"❌ No values returned for {interval}: {r}")
        return None

    return r["values"]


# ============================================================
# MAIN LOOP
# ============================================================

print("🔥 Lumi Full Engine Loaded — Starting...")

while True:
    now = datetime.now(TIMEZONE)

    # Heartbeat
    print(f"{now} | INFO | Lumi heartbeat 💡")

    # Check if candle closed (minute divisible by 5)
    if now.minute % 5 != 0:
        print("Not an M5 close; waiting.")
        time.sleep(LOOP_SECONDS)
        continue

    print("M5 close detected — fetching data & evaluating signal...")

    # --------------------------------------------------------
    # Fetch TF data
    # --------------------------------------------------------

    data_5m = get_data("5min")
    data_15m = get_data("15min")
    data_1h = get_data("1h")

    if data_5m is None or data_15m is None or data_1h is None:
        print("TA Fetch Error — data unavailable.")
        time.sleep(LOOP_SECONDS)
        continue

    # --------------------------------------------------------
    # Generate Trading Signal
    # --------------------------------------------------------

    signal = generate_signal(data_5m, data_15m, data_1h)

    if not signal:
        print("No signal — filters not satisfied.")
    else:
        print(f"🔥 SIGNAL: {signal}")
        send_telegram_message(BOT_TOKEN, CHAT_ID, signal)

    time.sleep(LOOP_SECONDS)