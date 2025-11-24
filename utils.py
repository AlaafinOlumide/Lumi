import requests
import numpy as np

TD_KEY = "9ab283d3938d4a19b5481f72fa53df6b"
BOT_TOKEN = "7950450689:AAGPfU9IR7kgrX9eWEE2216tV4YQT8gKGqM"
CHAT_ID = "1302419329"

# ----------------------------
# TELEGRAM
# ----------------------------
def send_telegram_message(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

# ----------------------------
# PRICE FETCHING
# ----------------------------
def get_price(symbol, interval):
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&apikey={TD_KEY}&outputsize=200"
        data = requests.get(url, timeout=10).json()
        values = data["values"]

        close = np.array([float(v["close"]) for v in reversed(values)])
        return {"close": close}

    except:
        return None

# ----------------------------
# INDICATORS
# ----------------------------
def get_ema(data, length):
    prices = data["close"]
    ema = []
    k = 2 / (length + 1)
    ema_val = prices[0]
    for p in prices:
        ema_val = p * k + ema_val * (1 - k)
        ema.append(ema_val)
    return np.array(ema)

def get_rsi(data, length=14):
    prices = data["close"]
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:length])
    avg_loss = np.mean(losses[:length])

    rsi = []
    for i in range(len(prices)):
        if i < length:
            rsi.append(50)
        else:
            avg_gain = (avg_gain * (length - 1) + gains[i - 1]) / length
            avg_loss = (avg_loss * (length - 1) + losses[i - 1]) / length

            rs = avg_gain / (avg_loss + 1e-6)
            rsi.append(100 - (100 / (1 + rs)))

    return np.array(rsi)

def get_stochastic(data, k_period=14, d_period=3):
    closes = data["close"]
    k_vals = []
    for i in range(len(closes)):
        if i < k_period:
            k_vals.append(50)
        else:
            window = closes[i - k_period:i]
            low = np.min(window)
            high = np.max(window)
            k_vals.append((closes[i] - low) / (high - low + 1e-6) * 100)
    k_vals = np.array(k_vals)
    d_vals = np.convolve(k_vals, np.ones(d_period)/d_period, mode="same")
    return k_vals, d_vals

def get_bollinger(data, length=20, mult=2):
    closes = data["close"]
    ma = np.convolve(closes, np.ones(length)/length, mode="same")
    std = np.array([np.std(closes[max(0, i-length):i+1]) for i in range(len(closes))])
    upper = ma + std * mult
    lower = ma - std * mult
    return upper, ma, lower

# ----------------------------
# NEWS RATING
# ----------------------------
def fetch_news_rating(symbol):
    # Mock system (FMP key is None so we simulate)
    # You can plug real FMP Calendar here later
    return "low"