import time
import pytz
import logging
from datetime import datetime
from signals import analyze_market_and_generate_signal
from utils import send_telegram_message, fetch_news_rating

# CONFIG
TZ = pytz.timezone("Europe/London")
LOOP_SECONDS = 60
PAIR = "XAUUSD"
TELEGRAM_CHAT_ID = "1302419329"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

def is_m5_close(now):
    return now.minute % 5 == 0 and now.second < 3

def lumi_heartbeat(now):
    logging.info(f"Lumi heartbeat 💡 | Local time: {now.isoformat()}")

def main_loop():
    logging.info("Lumi started with full Trade Engine 🔥")

    while True:
        now = datetime.now(TZ)
        lumi_heartbeat(now)

        # Only evaluate on M5 close
        if is_m5_close(now):
            logging.info("M5 close detected — running market analysis...")

            # NEWS CHECK
            severity = fetch_news_rating(PAIR)
            logging.info(f"News severity: {severity}")

            # ANALYSE MARKET
            signal = analyze_market_and_generate_signal(PAIR, severity)

            if signal:
                msg = (
                    f"🚀 **LUMI SIGNAL** 🚀\n\n"
                    f"Pair: {PAIR}\n"
                    f"Direction: {signal['direction']}\n"
                    f"Confidence: {signal['confidence']}%\n"
                    f"Entry Zone: {signal['entry']}\n"
                    f"SL: {signal['sl']}\n"
                    f"TP: {signal['tp']}\n"
                    f"Reason: {signal['reason']}\n"
                    f"News Filter: {severity}\n"
                    f"Time: {now.strftime('%Y-%m-%d %H:%M')}"
                )
                send_telegram_message(msg)
                logging.info("Signal sent to Telegram.")
            else:
                logging.info("No signal this candle.")

        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    main_loop()