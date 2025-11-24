import os
import time
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from datetime import datetime, time as dtime
import pytz
import numpy as np
import requests

# =========================
# CONFIG
# =========================

TZ_NAME = "Europe/London"
LOOP_SECONDS = 60  # main loop heartbeat in seconds
SYMBOL = "XAU/USD"
TD_BASE_URL = "https://api.twelvedata.com/time_series"

# Trading windows in local time (Europe/London)
TRADING_WINDOWS = [
    ("07:00", "11:00"),   # London morning
    ("12:00", "16:30"),   # London/NY overlap
]

# Minimum candles required for indicators
MIN_H1_CANDLES = 60
MIN_M15_CANDLES = 60
MIN_M5_CANDLES = 100

# =========================
# LOGGING
# =========================

logger = logging.getLogger("Lumi")
logger.setLevel(logging.INFO)

handler = logging.StreamHandler()
formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
handler.setFormatter(formatter)
logger.handlers.clear()
logger.addHandler(handler)


# =========================
# DATA TYPES
# =========================

@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class SignalResult:
    direction: Optional[str]  # "LONG", "SHORT", or None
    reason: str
    extra: dict


# =========================
# TIME HELPERS
# =========================

LOCAL_TZ = pytz.timezone(TZ_NAME)


def now_local() -> datetime:
    """Get timezone-aware datetime in Lumi's local timezone."""
    return datetime.now(LOCAL_TZ)


def parse_time_str(t: str) -> dtime:
    h, m = t.split(":")
    return dtime(int(h), int(m))


def is_in_trading_window(now: datetime) -> bool:
    local_t = now.time()
    for start_str, end_str in TRADING_WINDOWS:
        start = parse_time_str(start_str)
        end = parse_time_str(end_str)
        if start <= local_t <= end:
            return True
    return False


def is_last_10_minutes_of_hour(now: datetime) -> bool:
    return now.minute >= 50


def is_m5_close(now: datetime) -> bool:
    """
    Fire on M5 closes:
    e.g., 07:05, 07:10, 07:15, ...
    With LOOP_SECONDS=60 this is good enough.
    """
    return now.minute % 5 == 0


# =========================
# TELEGRAM
# =========================

def get_telegram_config() -> Tuple[Optional[str], Optional[str]]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    return token, chat_id


def send_telegram_message(text: str) -> None:
    token, chat_id = get_telegram_config()
    if not token or not chat_id:
        logger.info("Telegram not configured; skipping alert.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(
                f"Telegram send error: status={resp.status_code}, body={resp.text}"
            )
    except Exception as e:
        logger.exception(f"Telegram send exception: {e}")


# =========================
# MARKET DATA (TWELVE DATA)
# =========================

def fetch_candles(
    symbol: str,
    interval: str,
    outputsize: int = 200,
) -> Optional[List[Candle]]:
    """
    Fetch candles from Twelve Data. Returns list ordered oldest -> newest.
    Requires TD_API_KEY in env.
    """
    api_key = os.getenv("TD_API_KEY")
    if not api_key:
        logger.error("TD_API_KEY not set in environment; cannot fetch market data.")
        return None

    params = {
        "symbol": symbol,
        "interval": interval,      # e.g. "1h", "15min", "5min"
        "outputsize": outputsize,
        "apikey": api_key,
        "timezone": TZ_NAME,
        "order": "desc",           # latest first, will reverse later
    }

    try:
        resp = requests.get(TD_BASE_URL, params=params, timeout=10)
    except Exception as e:
        logger.error(f"Data fetch error ({interval}): exception={e}")
        return None

    if resp.status_code != 200:
        logger.error(
            f"Data fetch error ({interval}): HTTP {resp.status_code} | body={resp.text}"
        )
        return None

    data = resp.json()
    if "values" not in data:
        logger.error(f"Data fetch error ({interval}): no 'values' field in response.")
        return None

    candles: List[Candle] = []
    for item in data["values"]:
        try:
            ts = LOCAL_TZ.localize(
                datetime.strptime(item["datetime"], "%Y-%m-%d %H:%M:%S")
            )
            candles.append(
                Candle(
                    timestamp=ts,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item.get("volume", 0.0)),
                )
            )
        except Exception:
            # Skip malformed entries
            continue

    # reverse to oldest -> newest
    candles.reverse()

    if not candles:
        logger.error(f"Data fetch error ({interval}): parsed 0 candles.")
        return None

    return candles


# =========================
# INDICATORS (NUMPY)
# =========================

def to_np(candles: List[Candle]):
    closes = np.array([c.close for c in candles], dtype=float)
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    return closes, highs, lows


def ema(series: np.ndarray, period: int) -> np.ndarray:
    if len(series) < period:
        return np.array([])
    alpha = 2 / (period + 1)
    ema_values = np.zeros_like(series)
    ema_values[0] = series[0]
    for i in range(1, len(series)):
        ema_values[i] = alpha * series[i] + (1 - alpha) * ema_values[i - 1]
    return ema_values


def rsi(series: np.ndarray, period: int = 14) -> np.ndarray:
    if len(series) <= period:
        return np.array([])

    deltas = np.diff(series)
    seed = deltas[:period]
    gain = np.mean(seed[seed > 0]) if np.any(seed > 0) else 0
    loss = -np.mean(seed[seed < 0]) if np.any(seed < 0) else 1e-9

    rs = gain / loss
    rsi_series = np.zeros_like(series)
    rsi_series[:period] = 100 - (100 / (1 + rs))

    avg_gain = gain
    avg_loss = loss

    for i in range(period, len(series)):
        delta = deltas[i - 1]
        gain_val = max(delta, 0)
        loss_val = -min(delta, 0)

        avg_gain = (avg_gain * (period - 1) + gain_val) / period
        avg_loss = (avg_loss * (period - 1) + loss_val) / period

        rs = avg_gain / (avg_loss + 1e-9)
        rsi_series[i] = 100 - (100 / (1 + rs))

    return rsi_series


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    if len(closes) <= period:
        return np.array([])

    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    trs = np.array(trs)
    atr_values = np.zeros_like(trs)
    atr_values[period - 1] = np.mean(trs[:period])
    for i in range(period, len(trs)):
        atr_values[i] = (atr_values[i - 1] * (period - 1) + trs[i]) / period
    return atr_values


# =========================
# SIGNAL LOGIC (OPTION A)
# =========================

def compute_signal(
    h1_candles: List[Candle],
    m15_candles: List[Candle],
    m5_candles: List[Candle],
) -> SignalResult:
    """
    Option A: Simple trend-follow + momentum + key level logic,
    not too strict to avoid signal starvation.
    """

    if (
        len(h1_candles) < MIN_H1_CANDLES
        or len(m15_candles) < MIN_M15_CANDLES
        or len(m5_candles) < MIN_M5_CANDLES
    ):
        return SignalResult(
            direction=None,
            reason="Not enough historical candles for robust analysis.",
            extra={"h1": len(h1_candles), "m15": len(m15_candles), "m5": len(m5_candles)},
        )

    # --- H1 Context ---
    h1_closes, h1_highs, h1_lows = to_np(h1_candles)
    h1_ema50 = ema(h1_closes, 50)
    if len(h1_ema50) == 0:
        return SignalResult(direction=None, reason="H1 EMA50 not available.", extra={})
    h1_trend_up = h1_closes[-1] > h1_ema50[-1]
    h1_trend_down = h1_closes[-1] < h1_ema50[-1]

    # --- M15 Bias ---
    m15_closes, m15_highs, m15_lows = to_np(m15_candles)
    m15_ema20 = ema(m15_closes, 20)
    if len(m15_ema20) == 0:
        return SignalResult(direction=None, reason="M15 EMA20 not available.", extra={})
    m15_trend_up = m15_closes[-1] > m15_ema20[-1]
    m15_trend_down = m15_closes[-1] < m15_ema20[-1]

    # --- M5 Trigger ---
    m5_closes, m5_highs, m5_lows = to_np(m5_candles)
    last5 = m5_candles[-1]
    prev5 = m5_candles[-2]

    m5_ema20 = ema(m5_closes, 20)
    if len(m5_ema20) == 0:
        return SignalResult(direction=None, reason="M5 EMA20 not available.", extra={})

    m5_atr14 = atr(m5_highs, m5_lows, m5_closes, 14)
    if len(m5_atr14) == 0:
        return SignalResult(direction=None, reason="M5 ATR14 not available.", extra={})
    current_atr = m5_atr14[-1]

    # Candle characteristics
    body = abs(last5.close - last5.open)
    range_ = last5.high - last5.low if last5.high > last5.low else 1e-9
    body_ratio = body / range_
    bullish = last5.close > last5.open
    bearish = last5.close < last5.open

    if current_atr <= 0:
        return SignalResult(direction=None, reason="ATR is zero or negative.", extra={})

    # Key pseudo-level: recent M15 high/low over last ~24 candles
    m15_recent = m15_candles[-24:]
    recent_high = max(c.high for c in m15_recent)
    recent_low = min(c.low for c in m15_recent)

    price = last5.close

    distance_to_high = recent_high - price
    distance_to_low = price - recent_low

    near_high = distance_to_high < 1.5 * current_atr
    near_low = distance_to_low < 1.5 * current_atr

    # =========================
    # LONG SETUP
    # =========================
    long_ok = (
        h1_trend_up
        and m15_trend_up
        and bullish
        and body_ratio > 0.4
        and price > m5_ema20[-1]  # with micro trend
        and (near_low or distance_to_low < 2.5 * current_atr)
    )

    # =========================
    # SHORT SETUP
    # =========================
    short_ok = (
        h1_trend_down
        and m15_trend_down
        and bearish
        and body_ratio > 0.4
        and price < m5_ema20[-1]
        and (near_high or distance_to_high < 2.5 * current_atr)
    )

    if long_ok and not short_ok:
        return SignalResult(
            direction="LONG",
            reason="H1 & M15 uptrend + strong bullish M5 candle near recent support.",
            extra={
                "price": price,
                "recent_low": recent_low,
                "atr": current_atr,
                "body_ratio": body_ratio,
            },
        )

    if short_ok and not long_ok:
        return SignalResult(
            direction="SHORT",
            reason="H1 & M15 downtrend + strong bearish M5 candle near recent resistance.",
            extra={
                "price": price,
                "recent_high": recent_high,
                "atr": current_atr,
                "body_ratio": body_ratio,
            },
        )

    return SignalResult(
        direction=None,
        reason="Filters not satisfied for either clean LONG or SHORT.",
        extra={
            "h1_trend_up": bool(h1_trend_up),
            "h1_trend_down": bool(h1_trend_down),
            "m15_trend_up": bool(m15_trend_up),
            "m15_trend_down": bool(m15_trend_down),
            "bullish_m5": bool(bullish),
            "bearish_m5": bool(bearish),
            "body_ratio": body_ratio,
        },
    )


# =========================
# TRADE ENGINE LOOP
# =========================

def run_trade_engine(last_bar_key: Optional[str]) -> Optional[str]:
    """
    Option A engine:
    - Only runs on M5 closes.
    - Skips last 10 minutes of each hour.
    - Respects trading windows.
    - Fetches H1, M15, M5 from Twelve Data.
    - Evaluates and sends Telegram alerts on signals.
    """
    now = now_local()

    # 1) Trading window filter
    if not is_in_trading_window(now):
        logger.info("Outside trading windows; idle.")
        return last_bar_key

    # 2) Last 10 minutes filter
    if is_last_10_minutes_of_hour(now):
        logger.info("Inside last 10 minutes of hour; skipping trade checks.")
        return last_bar_key

    # 3) M5 close filter
    if not is_m5_close(now):
        logger.info("Not an M5 close; waiting.")
        return last_bar_key

    # Prevent duplicate work on same bar
    bar_key = now.strftime("%Y-%m-%d %H:%M")
    if bar_key == last_bar_key:
        logger.info("M5 bar already processed; waiting for next bar.")
        return last_bar_key

    logger.info("M5 close detected — fetching data & evaluating signal...")

    # 4) Fetch candles
    h1 = fetch_candles(SYMBOL, "1h", outputsize=MIN_H1_CANDLES + 20)
    if not h1:
        logger.info("TA Fetch Error (1h): no data returned.")
        return last_bar_key

    m15 = fetch_candles(SYMBOL, "15min", outputsize=MIN_M15_CANDLES + 20)
    if not m15:
        logger.info("TA Fetch Error (15m): no data returned.")
        return last_bar_key

    m5 = fetch_candles(SYMBOL, "5min", outputsize=MIN_M5_CANDLES + 20)
    if not m5:
        logger.info("TA Fetch Error (5m): no data returned.")
        return last_bar_key

    # 5) Compute signal
    signal = compute_signal(h1, m15, m5)

    if signal.direction is None:
        logger.info(f"No signal — {signal.reason}")
        return bar_key  # processed this bar

    # 6) Build alert text
    last5 = m5[-1]
    text_lines = [
        "*Lumi Trade Signal* 🔔",
        "",
        f"Pair: `{SYMBOL}`",
        f"Direction: *{signal.direction}*",
        "",
        f"Reason: {signal.reason}",
        "",
        f"Time (local): {last5.timestamp.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"Details: `{signal.extra}`",
    ]
    msg = "\n".join(text_lines)

    logger.info(f"Signal generated: {signal.direction} | reason={signal.reason}")
    send_telegram_message(msg)

    return bar_key


# =========================
# MAIN LOOP
# =========================

def main():
    logger.info("Lumi started with full Trade Engine 🔥")
    logger.info(
        f"Config: TZ={TZ_NAME}, LOOP_SECONDS={LOOP_SECONDS}, SYMBOL={SYMBOL}, "
        f"TRADING_WINDOWS={TRADING_WINDOWS}"
    )

    last_bar_key: Optional[str] = None

    while True:
        try:
            now = now_local()
            logger.info(
                f"Lumi heartbeat 💡 | Local time: {now.isoformat(timespec='seconds')}"
            )

            last_bar_key = run_trade_engine(last_bar_key)

        except Exception as e:
            logger.exception(f"Main loop error: {e}")

        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    main()