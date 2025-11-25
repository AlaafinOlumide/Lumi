import os
import time
import logging
from datetime import datetime
from typing import List, Tuple, Optional

import requests
import pandas as pd
import pytz
from dotenv import load_dotenv

# =========================
#  Bootstrap & Config
# =========================

load_dotenv()

# Core config
TZ_NAME = os.getenv("TZ", "Europe/London")
LOOP_SECONDS = int(os.getenv("LOOP_SECONDS", "60"))
SYMBOL = os.getenv("SYMBOL", "XAU/USD")

# Trading windows (local TZ)
#   23:00–04:30  → Asia / overnight
#   07:00–11:00  → London
#   12:00–16:30  → New York
TRADING_WINDOWS: List[Tuple[str, str]] = [
    ("23:00", "04:30"),
    ("07:00", "11:00"),
    ("12:00", "16:30"),
]

# Twelve Data
TD_API_KEY = os.getenv("TD_API_KEY", "").strip()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# =========================
#  Logging
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("lumi-a3-pro")


# =========================
#  Utilities
# =========================

def get_local_now() -> datetime:
    tz = pytz.timezone(TZ_NAME)
    return datetime.now(tz)


def is_time_in_window(now: datetime, start: str, end: str) -> bool:
    """
    Return True if `now` is inside [start, end], handling midnight-crossing windows.

    start / end are "HH:MM" strings in local time.
    Example crossing window: 23:00–04:30
    """
    now_t = now.time()
    start_t = datetime.strptime(start, "%H:%M").time()
    end_t = datetime.strptime(end, "%H:%M").time()

    # Normal window: e.g. 07:00–11:00
    if start_t < end_t:
        return start_t <= now_t <= end_t

    # Midnight-crossing window: e.g. 23:00–04:30
    return now_t >= start_t or now_t <= end_t


def inside_any_trading_window(now: datetime, windows: List[Tuple[str, str]]) -> bool:
    return any(is_time_in_window(now, s, e) for s, e in windows)


def is_m5_close(now: datetime, last_checked_bucket: Optional[datetime]) -> Tuple[bool, Optional[datetime]]:
    """
    Detect an M5 close using local time.

    We define an M5 bucket at e.g. 08:50, 08:55, 09:00...
    We trigger once per bucket using `last_checked_bucket`.
    """
    # Floor to minute
    bucket = now.replace(second=0, microsecond=0)

    # Only consider minutes that are multiples of 5
    if bucket.minute % 5 != 0:
        return False, last_checked_bucket

    # If we've already processed this bucket, skip
    if last_checked_bucket is not None and bucket <= last_checked_bucket:
        return False, last_checked_bucket

    return True, bucket


# =========================
#  Telegram
# =========================

def send_telegram_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram credentials missing; cannot send message.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            log.error("Telegram send error: %s | %s", resp.status_code, resp.text)
    except Exception as e:
        log.error("Telegram send exception: %s", e)


# =========================
#  Market Data (Twelve Data)
# =========================

def fetch_twelvedata_series(symbol: str, interval: str, outputsize: int = 200) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV from Twelve Data and return a DataFrame sorted by datetime ascending.
    """
    if not TD_API_KEY:
        log.error("TD_API_KEY not set; cannot fetch market data.")
        return None

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TD_API_KEY,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
    except Exception as e:
        log.error("Twelve Data exception (%s): %s", interval, e)
        return None

    status = data.get("status")
    if status == "error":
        log.error(
            "Twelve Data error (%s): status=%s, code=%s, message=%s",
            interval,
            data.get("status"),
            data.get("code"),
            data.get("message"),
        )
        return None

    values = data.get("values")
    if not values:
        log.error("Twelve Data error (%s): no 'values' field in response.", interval)
        return None

    df = pd.DataFrame(values)
    if "datetime" not in df.columns:
        log.error("Twelve Data error (%s): no 'datetime' column in values.", interval)
        return None

    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)

    # Convert numeric columns
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# =========================
#  Simple Strategy (Option 1)
# =========================

def evaluate_signal_5m(df_5m: pd.DataFrame) -> Optional[dict]:
    """
    Very simple SMA crossover + momentum filter on 5m data.

    This is intentionally light (Option 1) so it runs safely on Render.
    You can later upgrade this to your full PPSS logic.
    """
    if df_5m is None or df_5m.empty:
        return None

    if len(df_5m) < 25:
        # Not enough data
        return None

    closes = df_5m["close"].astype(float)

    fast = closes.rolling(5).mean()
    slow = closes.rolling(20).mean()

    # Last two values for cross detection
    prev_fast, prev_slow = fast.iloc[-2], slow.iloc[-2]
    curr_fast, curr_slow = fast.iloc[-1], slow.iloc[-1]
    curr_close = closes.iloc[-1]

    # Basic volatility filter: candle body must be > small threshold
    body = abs(curr_close - df_5m["open"].astype(float).iloc[-1])
    atr_like = (df_5m["high"] - df_5m["low"]).astype(float).rolling(14).mean().iloc[-1]
    if pd.isna(atr_like) or atr_like == 0:
        return None

    if body < 0.15 * atr_like:
        # Too small / choppy
        return None

    # Bullish cross
    if prev_fast < prev_slow and curr_fast > curr_slow:
        return {
            "direction": "buy",
            "price": curr_close,
            "reason": "5/20 SMA bullish cross with momentum",
        }

    # Bearish cross
    if prev_fast > prev_slow and curr_fast < curr_slow:
        return {
            "direction": "sell",
            "price": curr_close,
            "reason": "5/20 SMA bearish cross with momentum",
        }

    return None


def format_signal_message(symbol: str, signal: dict, now: datetime) -> str:
    direction = signal["direction"].upper()
    price = signal["price"]
    reason = signal.get("reason", "Strategy conditions met")

    ts = now.strftime("%Y-%m-%d %H:%M")
    return (
        f"🟢 *Lumi A3 Pro Signal*\n\n"
        f"*Symbol:* `{symbol}`\n"
        f"*Direction:* `{direction}`\n"
        f"*Price:* `{price:.2f}`\n"
        f"*Time:* `{ts} {TZ_NAME}`\n"
        f"*Reason:* {reason}"
    )


# =========================
#  Main Loop
# =========================

def main():
    log.info("Lumi A3 Pro started 🔥")
    log.info(
        "Config: TZ=%s, LOOP_SECONDS=%s, SYMBOL=%s, TRADING_WINDOWS=%s",
        TZ_NAME,
        LOOP_SECONDS,
        SYMBOL,
        TRADING_WINDOWS,
    )

    last_m5_bucket: Optional[datetime] = None

    while True:
        try:
            now = get_local_now()
            log.info("Lumi heartbeat 💡 | Local time: %s", now)

            # 1️⃣ Trading window check
            if not inside_any_trading_window(now, TRADING_WINDOWS):
                log.info("Not inside allowed trading window.")
                time.sleep(LOOP_SECONDS)
                continue

            # 2️⃣ M5 close detection
            m5_close, last_m5_bucket = is_m5_close(now, last_m5_bucket)
            if not m5_close:
                log.info("Not an M5 close; waiting.")
                time.sleep(LOOP_SECONDS)
                continue

            log.info("M5 close detected — fetching data & evaluating signal...")

            # 3️⃣ Fetch 5m data
            df_5m = fetch_twelvedata_series(SYMBOL, "5min", outputsize=200)
            if df_5m is None or df_5m.empty:
                log.info("TA Fetch Error (5m): no data returned.")
                time.sleep(LOOP_SECONDS)
                continue

            # 4️⃣ Evaluate strategy
            signal = evaluate_signal_5m(df_5m)

            if not signal:
                log.info("No signal — strategy conditions not met.")
            else:
                msg = format_signal_message(SYMBOL, signal, now)
                log.info("Signal generated: %s", msg.replace("\n", " | "))
                send_telegram_message(msg)

        except Exception as e:
            log.exception("Unexpected error in main loop: %s", e)

        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    main()