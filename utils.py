
import requests

def get_price(symbol):
    url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey=9ab283d3938d4a19b5481f72fa53df6b"
    r = requests.get(url).json()
    return float(r["price"])

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
