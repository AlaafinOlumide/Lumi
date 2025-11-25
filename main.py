# main.py

import os
import time
import logging
import datetime as dt
from typing import List, Tuple, Optional, Dict

import pytz
import requests
import pandas as pd
from dotenv import load_dotenv

from core.engine import TradingEngine, Signal


# ---------- Logging setup ----------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("Lumi")


# ---------- ENV & config ----------

load_dotenv()

TZ_NAME = os.getenv("TZ", "Europe/London")
LOOP_SECONDS = int(os.getenv("LOOP_SECONDS", "60"))

TD_API_KEY = os.getenv("TD_API_KEY", "")
TD_BASE_URL = "https://api.twelvedata.com/time_series"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# SYMBOLS: comma-separated, e.g. "XAU/USD,USD/JPY"
raw_symbols = os.getenv("SYMBOLS", "XAU/USD")
SYMBOLS: List[str] = [s.strip() for s in raw_symbols.split(",") if s.strip()]

# TRADING_WINDOWS: e.g. "23:00-04:30,07:00-11:00,12:00-16:30"
raw_windows = os.getenv(
    "TRADING_WINDOWS",
    "23:00-04:30,07:00-11:00,12:00-16:30",
)
TRADING_WINDOWS: List[Tuple[str, str]] = []
for w in raw_windows.split(","):
    w = w.strip()
    if not w:
        continue
    start, end = w.split("-")
    TRADING_WINDOWS.append((start.strip(), end.strip()))

TZ = pytz.timezone(TZ_NAME)


# ---------- Telegram ----------

def send_telegram_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping message: %s", text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.error("Telegram error: %s | %s", r.status_code, r.text)
    except Exception as exc:
        logger.error("Telegram request failed: %s", exc)


# ---------- Time helpers ----------

def in_trading_window(now: dt.datetime) -> bool:
    """
    now: tz-aware in TZ
    """
    current_time = now.time()
    for start_str, end_str in TRADING_WINDOWS:
        start_h, start_m = map(int, start_str.split(":"))
        end_h, end_m = map(int, end_str.split(":"))
        start_t = dt.time(start_h, start_m)
        end_t = dt.time(end_h, end_m)

        if start_t <= end_t:
            # Same-day window
            if start_t <= current_time <= end_t:
                return True
        else:
            # Cross-midnight window, e.g. 23:00–04:30
            if current_time >= start_t or current_time <= end_t:
                return True
    return False


def is_m5_close(now: dt.datetime) -> bool:
    """
    Run loop once per minute; treat any timestamp with minute%5==0
    as the M5 close moment.
    """
    return now.minute % 5 == 0


# ---------- Data fetching (Twelve Data) ----------

def fetch_ohlc(
    symbol: str,
    interval: str,
    outputsize: int,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLC from Twelve Data and return ascending DataFrame with:

    columns: ["datetime", "open", "high", "low", "close"]
    datetime: tz-aware (TZ)
    """
    if not TD_API_KEY:
        logger.error("TD_API_KEY not set — cannot fetch data.")
        return None

    params = {
        "symbol": symbol,
        "interval": interval,
        "apikey": TD_API_KEY,
        "outputsize": outputsize,
        "order": "desc",  # latest first
    }

    try:
        r = requests.get(TD_BASE_URL, params=params, timeout=10)
        data = r.json()

        if "status" in data and data["status"] == "error":
            logger.error(
                "Twelve Data error (%s, %s): code=%s, message=%s",
                symbol,
                interval,
                data.get("code"),
                data.get("message"),
            )
            return None

        values = data.get("values")
        if not values:
            logger.error("No 'values' in Twelve Data response (%s, %s).", symbol, interval)
            return None

        df = pd.DataFrame(values)
        # Columns from Twelve Data: datetime, open, high, low, close, volume
        df["datetime"] = pd.to_datetime(df["datetime"])
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)

        # Convert to TZ and sort ascending
        df["datetime"] = df["datetime"].dt.tz_localize("UTC").dt.tz_convert(TZ)
        df = df.sort_values("datetime").reset_index(drop=True)

        return df

    except Exception as exc:
        logger.exception("Error fetching Twelve Data for %s (%s): %s", symbol, interval, exc)
        return None


# ---------- Main trading loop ----------

def format_signal_message(sig: Signal) -> str:
    direction_emoji = "🟢 BUY" if sig.direction == "BUY" else "🔴 SELL"
    msg = (
        f"*Lumi A3 Pro + PPSS Signal*\n"
        f"Symbol: `{sig.symbol}`\n"
        f"Direction: {direction_emoji}\n"
        f"Entry: `{sig.entry:.3f}`\n"
        f"SL: `{sig.sl:.3f}`\n"
        f"TP: `{sig.tp:.3f}`\n"
        f"Confidence: `{sig.confidence:.1f}` / 100\n"
        f"Timeframe: `{sig.timeframe_entry}`\n"
        f"Reason: {sig.reason}\n"
        f"Time: `{sig.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}`"
    )
    return msg


def format_tp_sl_message(sig: Signal, hit: str, price: float, now: dt.datetime) -> str:
    flag = "🎯 TP HIT" if hit == "TP" else "⛔ SL HIT"
    msg = (
        f"*{flag}*\n"
        f"Symbol: `{sig.symbol}`\n"
        f"Direction: `{sig.direction}`\n"
        f"Entry: `{sig.entry:.3f}`\n"
        f"SL: `{sig.sl:.3f}`\n"
        f"TP: `{sig.tp:.3f}`\n"
        f"Hit price: `{price:.3f}`\n"
        f"Opened at: `{sig.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}`\n"
        f"Closed at: `{now.strftime('%Y-%m-%d %H:%M:%S %Z')}`"
    )
    return msg


def main() -> None:
    engine = TradingEngine()
    logger.info(
        "Lumi A3 Pro + PPSS started 🔥 | TZ=%s | LOOP_SECONDS=%s | SYMBOLS=%s | WINDOWS=%s",
        TZ_NAME,
        LOOP_SECONDS,
        SYMBOLS,
        TRADING_WINDOWS,
    )

    # In-memory tracking of open signals for TP/SL alerts
    open_signals: Dict[str, Signal] = {}

    while True:
        now = dt.datetime.now(TZ)
        logger.info("Lumi heartbeat 💡 | Local time: %s", now.isoformat(timespec="seconds"))

        if not in_trading_window(now):
            logger.info("Not inside allowed trading window — sleeping.")
            time.sleep(LOOP_SECONDS)
            continue

        if is_m5_close(now):
            logger.info("M5 close detected — fetching data & evaluating signals...")
            for symbol in SYMBOLS:
                m5 = fetch_ohlc(symbol, "5min", outputsize=120)
                m15 = fetch_ohlc(symbol, "15min", outputsize=120)
                h1 = fetch_ohlc(symbol, "1h", outputsize=240)

                if m5 is None or m15 is None or h1 is None:
                    logger.info("Skipping %s — missing data.", symbol)
                    continue

                sig = engine.evaluate(symbol, m5, m15, h1, now)
                if sig is not None:
                    # Send entry alert
                    send_telegram_message(format_signal_message(sig))
                    # Track for TP/SL alerts (overwrite any existing one for this symbol)
                    open_signals[symbol] = sig
                else:
                    logger.info("No signal for %s this M5 close.", symbol)

        # TP/SL monitoring for open signals
        if open_signals:
            for symbol, sig in list(open_signals.items()):
                # Use latest M5 close as proxy for current price
                m5 = fetch_ohlc(symbol, "5min", outputsize=10)
                if m5 is None or m5.empty:
                    continue
                last_price = float(m5["close"].iloc[-1])
                hit = engine.check_tp_sl_hit(last_price, sig, buffer_points=0.0)
                if hit:
                    logger.info("%s %s hit for %s at price %.3f", symbol, hit, symbol, last_price)
                    send_telegram_message(format_tp_sl_message(sig, hit, last_price, now))
                    del open_signals[symbol]

        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    main()