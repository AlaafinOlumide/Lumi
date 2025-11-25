import os
import time
import pytz
import logging
from datetime import datetime
from telegram import send_telegram_message
from engine import generate_signal
from utils import (
    fetch_twelvedata,
    now_london,
    is_red_news,
    in_trading_window,
    get_session_name,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

TZ = "Europe/London"
SYMBOL = "XAU/USD"
LOOP_SECONDS = 60
TW_1 = ("23:00", "04:30")
TW_2 = ("07:00", "11:00")
TW_3 = ("12:00", "16:30")
TRADING_WINDOWS = [TW_1, TW_2, TW_3]


def main():
    logging.info("Lumi A3 Pro started 🔥")

    while True:
        try:
            current_time = now_london()
            logging.info(f"Lumi heartbeat 💡 | Local time: {current_time}")

            # Session Check
            if not in_trading_window(current_time, TRADING_WINDOWS):
                logging.info("Not inside allowed trading window.")
                time.sleep(LOOP_SECONDS)
                continue

            # M5 close check (only run at XX:00,05,10,...)
            if current_time.minute % 5 != 0:
                logging.info("Not an M5 close; waiting.")
                time.sleep(LOOP_SECONDS)
                continue

            logging.info("M5 close detected — fetching data & evaluating…")

            # Fetch raw data
            m5 = fetch_twelvedata(SYMBOL, "5min")
            m15 = fetch_twelvedata(SYMBOL, "15min")
            h1 = fetch_twelvedata(SYMBOL, "1h")

            if m5 is None or m15 is None or h1 is None:
                logging.error("Data fetch failed — skipping candle.")
                time.sleep(LOOP_SECONDS)
                continue

            # Check news (warning only)
            red_warning = is_red_news()
            if red_warning:
                logging.info("⚠️ Red news event detected (warning only).")

            # Determine session
            session = get_session_name(current_time)

            # RUN SIGNAL ENGINE
            signal = generate_signal(m5, m15, h1)

            if signal is None:
                logging.info("No signal — conditions not satisfied.")
            else:
                direction = signal["direction"]
                confidence = signal["confidence"]
                entry = signal["entry"]
                sl = signal["sl"]
                tp = signal["tp"]

                msg = f"""
🔥 **LUMI A3 PRO SIGNAL**
Symbol: {SYMBOL}
Session: {session}
Direction: **{direction}**
Entry: {entry}
SL: {sl}
TP: {tp}
Confidence: **{confidence}%**
News Warning: {"YES" if red_warning else "NO"}

Engine: PPSS A3 Pro ✓
"""
                send_telegram_message(msg)
                logging.info("Signal sent to Telegram.")

        except Exception as e:
            logging.error(f"Runtime error: {e}")

        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    main()