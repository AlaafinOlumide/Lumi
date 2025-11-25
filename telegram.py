import os
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


def send_telegram_message(text: str, parse_mode: str | None = "Markdown") -> None:
    """
    Send a text message to the configured Telegram chat.
    """
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram not configured – BOT_TOKEN or CHAT_ID missing.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    if parse_mode:
        data["parse_mode"] = parse_mode

    try:
        resp = requests.post(url, data=data, timeout=10)
        if not resp.ok:
            print(f"Telegram error: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Telegram send failed: {e}")