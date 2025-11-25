import os
import time
import pytz
import requests
import numpy as np
from datetime import datetime, timedelta

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

SYMBOL = "XAU/USD"
TD_API_KEY = os.getenv("TD_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TZ = pytz.timezone("Europe/London")
LOOP_SECONDS = 60

TRADING_WINDOWS = [
    ("23:00", "04:30"),
    ("07:00", "11:00"),
    ("12:00", "16:30"),
]

# ---------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------

def log(msg):
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{now} | {msg}")

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except:
        pass

def fetch_td(symbol, interval, output="values"):
    if not TD_API_KEY:
        log("ERROR | TD_API_KEY not set")
        return None

    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&apikey={TD_API_KEY}&outputsize=200"
    r = requests.get(url).json()

    if "status" in r and r["status"] == "error":
        log(f"ERROR | Twelve Data error ({interval}): {r}")
        return None
    if output not in r:
        return None
    return r[output]

def is_m5_close():
    t = datetime.now(TZ)
    return t.minute % 5 == 0 and t.second < 3

def in_session():
    now = datetime.now(TZ).time()
    for start, end in TRADING_WINDOWS:
        t1 = datetime.strptime(start, "%H:%M").time()
        t2 = datetime.strptime(end, "%H:%M").time()
        if t1 <= now <= t2:
            return True
    return False

# ---------------------------------------------------------
# TECHNICAL INDICATORS
# ---------------------------------------------------------

def atr(high, low, close, period=14):
    trs = []
    for i in range(1, len(close)):
        tr = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
        trs.append(tr)
    return np.mean(trs[-period:])

def rsi(close, period=14):
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = np.mean(gain[-period:])
    avg_loss = np.mean(loss[-period:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1+rs))

# ---------------------------------------------------------
# STRATEGY LOGIC (OPTION A3 — FAST SNIPER)
# ---------------------------------------------------------

def evaluate_signal():
    # Fetch data
    h1 = fetch_td(SYMBOL, "1h")
    m15 = fetch_td(SYMBOL, "15min")
    m5 = fetch_td(SYMBOL, "5min")

    if not h1 or not m15 or not m5:
        return None

    # Convert
    def extract(data):
        close = np.array([float(v["close"]) for v in data])
        high = np.array([float(v["high"]) for v in data])
        low = np.array([float(v["low"]) for v in data])
        return close, high, low

    h1_close, h1_high, h1_low = extract(h1)
    m15_close, m15_high, m15_low = extract(m15)
    m5_close, m5_high, m5_low = extract(m5)

    # Indicators
    h1_rsi = rsi(h1_close)
    m15_rsi_val = rsi(m15_close)
    atr_val = atr(m5_high, m5_low, m5_close)
    last = m5_close[-1]
    prev = m5_close[-2]

    wick_top = m5_high[-1] - max(last, prev)
    wick_bottom = min(last, prev) - m5_low[-1]
    body = abs(last - prev)

    # -----------------------------------------------------
    # OPTION A3 — SIGNAL CONDITIONS (Fast, more entries)
    # -----------------------------------------------------

    # 1. Trend check (H1 direction)
    trend_up = h1_close[-1] > np.mean(h1_close[-20:])
    trend_down = h1_close[-1] < np.mean(h1_close[-20:])

    # 2. M15 momentum (more flexible than A1/A2)
    bullish_momentum = m15_close[-1] > np.mean(m15_close[-10:])
    bearish_momentum = m15_close[-1] < np.mean(m15_close[-10:])

    # 3. ATR threshold (reduced for A3)
    if atr_val < 0.40:  # A3 uses lighter filter
        return None

    # 4. Candle confirmation (looser wick rules)
    if wick_top > body * 2.5 or wick_bottom > body * 2.5:
        return None

    # 5. Signal logic
    # BUY
    if trend_up and bullish_momentum and last > prev:
        return {
            "dir": "BUY",
            "entry": last,
            "sl": last - (atr_val * 2),
            "tp": last + (atr_val * 4)
        }

    # SELL
    if trend_down and bearish_momentum and last < prev:
        return {
            "dir": "SELL",
            "entry": last,
            "sl": last + (atr_val * 2),
            "tp": last - (atr_val * 4)
        }

    return None

# ---------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------

log("Lumi started with full Option A3 Sniper Engine ⚡")

while True:
    try:
        now = datetime.now(TZ)
        log(f"Lumi heartbeat 💡 | Local time: {now.isoformat()}")

        if not in_session():
            log("Outside trading session.")
            time.sleep(LOOP_SECONDS)
            continue

        if not is_m5_close():
            log("Not an M5 close; waiting.")
            time.sleep(LOOP_SECONDS)
            continue

        log("M5 close detected — evaluating...")
        signal = evaluate_signal()

        if signal:
            msg = (
                f"🔥 LUMI SIGNAL (A3 FAST)\n"
                f"Pair: {SYMBOL}\n"
                f"Direction: {signal['dir']}\n"
                f"Entry: {signal['entry']}\n"
                f"SL: {signal['sl']}\n"
                f"TP: {signal['tp']}\n"
                f"Time: {now.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            log("SIGNAL SENT!")
            send_telegram(msg)
        else:
            log("No signal — conditions not met.")

    except Exception as e:
        log(f"ERROR | {e}")

    time.sleep(LOOP_SECONDS)