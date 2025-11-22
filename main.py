
import time, requests, json, pytz
from datetime import datetime
from indicators import compute_indicators
from news import get_news_risk
from utils import get_price, send_telegram

SYMBOL = "XAUUSD"
CHAT_ID = "1302419329"
BOT_TOKEN = "7950450689:AAGPfU9IR7kgrX9eWEE2216tV4YQT8gKGqM"
TZ = pytz.timezone("Europe/London")

def is_m5_close(now):
    return now.minute % 5 == 4 and now.second >= 50

def main_loop():
    send_telegram(BOT_TOKEN, CHAT_ID, "🚀 Bot V2 Full Logic Started")
    while True:
        now = datetime.now(TZ)
        if is_m5_close(now):
            try:
                price = get_price(SYMBOL)
                inds = compute_indicators(SYMBOL)
                news_risk = get_news_risk()

                signal = None
                if inds["trend"] == "bullish" and inds["momentum"] == "strong":
                    signal = "BUY"
                elif inds["trend"] == "bearish" and inds["momentum"] == "strong":
                    signal = "SELL"

                if signal:
                    msg = f"📈 *{signal}* | {SYMBOL}\nPrice: {price}"
                    if news_risk["level"] in ["HIGH","MEDIUM"]:
                        msg += f"\n⚠️ News Risk: {news_risk['level']} ({news_risk['event']})"
                    send_telegram(BOT_TOKEN, CHAT_ID, msg)
                else:
                    print(now, "| No signal")

            except Exception as e:
                print("Error:", e)

            time.sleep(20)
        time.sleep(1)

if __name__ == "__main__":
    main_loop()
