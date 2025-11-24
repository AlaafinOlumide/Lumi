import os
import time
import json
import logging
from datetime import datetime, time as dt_time

import pytz
import requests

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger("lumi")

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
TZ_NAME = os.getenv("TZ", "Europe/London")
LOOP_SECONDS = int(os.getenv("LOOP_SECONDS", "60"))

# Default to XAU/USD for forex (Twelve Data style)
SYMBOL = os.getenv("SYMBOL", "XAU/USD")

# Default trading windows: Asia (partial), London, NY
TRADING_WINDOWS_RAW = os.getenv(
    "TRADING_WINDOWS",
    "23:00-04:30,07:00-11:00,12:00-16:30",
)

TD_API_KEY = os.getenv("TD_API_KEY")


# -----------------------------------------------------------------------------
# Helpers: trading windows & time
# -----------------------------------------------------------------------------
def parse_trading_windows(raw: str):
    """
    Parse TRADING_WINDOWS string into list of (start_str, end_str, start_time, end_time).
    Example: "23:00-04:30,07:00-11:00" -> [
        ('23:00','04:30', time(23,0), time(4,30)),
        ('07:00','11:00', time(7,0), time(11,0))
    ]
    """
    windows = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            continue
        start_str, end_str = [p.strip() for p in part.split("-", 1)]
        try:
            sh, sm = [int(x) for x in start_str.split(":")]
            eh, em = [int(x) for x in end_str.split(":")]
            start_t = dt_time(hour=sh, minute=sm)
            end_t = dt_time(hour=eh, minute=em)
            windows.append((start_str, end_str, start_t, end_t))
        except Exception as e:
            log.error(f"Error parsing trading window '{part}': {e}")
    return windows


TRADING_WINDOWS = parse_trading_windows(TRADING_WINDOWS_RAW)


def in_trading_window(now_local: datetime) -> bool:
    """
    Check if now_local is within any configured trading window.
    Handles windows that cross midnight (e.g. 23:00-04:30).
    """
    t = now_local.time()
    for start_str, end_str, start_t, end_t in TRADING_WINDOWS:
        if start_t <= end_t:
            # Normal same-day window, e.g. 07:00-11:00
            if start_t <= t < end_t:
                return True
        else:
            # Window crosses midnight, e.g. 23:00-04:30
            if t >= start_t or t < end_t:
                return True
    return False


def is_m5_close(now_local: datetime) -> bool:
    """
    We run once per minute. Treat any time where minute % 5 == 0 as an M5 close.
    """
    return now_local.minute % 5 == 0


# -----------------------------------------------------------------------------
# Twelve Data integration
# -----------------------------------------------------------------------------
def fetch_td_candles(symbol: str, interval: str, outputsize: int = 100):
    """
    Fetch OHLC candles from Twelve Data time_series endpoint.

    :param symbol: e.g. "XAU/USD"
    :param interval: e.g. "1h", "15min", "5min"
    :param outputsize: number of candles
    :return: list of candle dicts (latest first, per Twelve Data spec) or None
    """
    if not TD_API_KEY:
        log.error("TD_API_KEY not set in environment; cannot fetch market data.")
        return None

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "timezone": TZ_NAME,
        "apikey": TD_API_KEY,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
    except Exception as e:
        log.error(f"HTTP request error ({interval}): {e}")
        return None

    if resp.status_code != 200:
        snippet = resp.text[:300].replace("\n", " ")
        log.error(
            f"HTTP status error ({interval}): {resp.status_code} | Body snippet: {snippet}"
        )
        return None

    try:
        data = resp.json()
    except Exception as e:
        snippet = resp.text[:200].replace("\n", " ")
        log.error(f"JSON parse error ({interval}): {e} | Raw body: {snippet}")
        return None

    # Twelve Data error-style response
    if isinstance(data, dict) and data.get("status") == "error":
        code = data.get("code")
        message = data.get("message")
        log.error(
            f"Twelve Data error ({interval}): status=error, code={code}, message={message}"
        )
        return None

    values = data.get("values")
    if not values:
        snippet = json.dumps(data)[:300]
        log.error(
            f"Data fetch error ({interval}): no 'values' field in response. "
            f"Response snippet: {snippet}"
        )
        return None

    return values


def fetch_all_timeframes(symbol: str):
    """
    Fetch 1h, 15m, 5m data from Twelve Data.

    Returns dict {
        '1h': [...],
        '15m': [...],
        '5m': [...]
    } or None if any critical timeframe fails.
    """
    timeframes = {
        "1h": "1h",
        "15m": "15min",
        "5m": "5min",
    }

    result = {}
    ok = True

    for label, interval in timeframes.items():
        candles = fetch_td_candles(symbol, interval)
        if candles is None:
            log.info(f"TA Fetch Error ({label}): no data returned.")
            ok = False
        else:
            result[label] = candles

    if not ok:
        return None
    return result


# -----------------------------------------------------------------------------
# Signal logic (placeholder for now)
# -----------------------------------------------------------------------------
def evaluate_signal(all_candles: dict):
    """
    Placeholder for Lumi's trade logic.

    all_candles = {
        '1h': [...],
        '15m': [...],
        '5m': [...]
    }

    Returns tuple: (signal, reason)
    signal: 'BUY', 'SELL', or 'NONE'
    """
    # TODO: Plug in your PPSS / Lumi strategy here.
    # For now, always return no signal.
    return "NONE", "Strategy placeholder – no signal generated."


def maybe_check_for_signal(now_local: datetime):
    """
    Called when we are inside trading hours and at an M5 close.
    This does:
      1. Fetch data from Twelve Data for 1h/15m/5m
      2. Run evaluate_signal (currently a placeholder)
      3. Log what happened (later you can plug Telegram etc.)
    """
    log.info("M5 close detected — fetching data & evaluating signal...")

    all_candles = fetch_all_timeframes(SYMBOL)
    if all_candles is None:
        # fetch_all_timeframes already logged detailed errors.
        log.info("No signal — data unavailable or filters not satisfied.")
        return

    signal, reason = evaluate_signal(all_candles)
    if signal == "NONE":
        log.info(f"No signal — {reason}")
    else:
        # In future you can add Telegram alerts here.
        log.info(f"Signal detected: {signal} | Reason: {reason}")


# -----------------------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------------------
def main():
    tz = pytz.timezone(TZ_NAME)

    log.info(
        f"Lumi started with full Trade Engine 🔥"
    )
    log.info(
        f"Config: TZ={TZ_NAME}, LOOP_SECONDS={LOOP_SECONDS}, SYMBOL={SYMBOL}, "
        f"TRADING_WINDOWS={[ (w[0], w[1]) for w in TRADING_WINDOWS ]}"
    )

    while True:
        now_local = datetime.now(tz)

        # Heartbeat
        log.info(f"Lumi heartbeat 💡 | Local time: {now_local.isoformat()}")

        # If outside trading windows, just idle
        if not in_trading_window(now_local):
            log.info("Outside trading windows; idle.")
        else:
            # Inside trading windows – check if this is an M5 close
            if is_m5_close(now_local):
                maybe_check_for_signal(now_local)
            else:
                log.info("Not an M5 close; waiting.")

        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Lumi stopped manually.")