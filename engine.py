import numpy as np
from indicators import (
    compute_rsi,
    compute_stochastic,
    compute_bollinger,
    compute_ma,
    compute_atr,
)
from utils import last_close, candle_is_bullish, candle_is_bearish


def generate_signal(m5, m15, h1):
    """Full Lumi A3 Pro Trade Engine"""

    close = m5["close"].values
    high = m5["high"].values
    low = m5["low"].values

    # Indicators
    rsi = compute_rsi(close)
    stoch_k, stoch_d = compute_stochastic(high, low, close)
    bb_mid, bb_upper, bb_lower = compute_bollinger(close)
    ma20 = compute_ma(close, 20)
    atr = compute_atr(high, low, close)

    last = -1

    # Trend filter (1H)
    h1_close = h1["close"].values
    h1_ma = compute_ma(h1_close, 50)

    trend_up = h1_close[last] > h1_ma[last]
    trend_down = h1_close[last] < h1_ma[last]

    # Confluences
    bullish_score = 0
    bearish_score = 0

    # RSI (oversold / overbought)
    if rsi[last] < 30:
        bullish_score += 1
    if rsi[last] > 70:
        bearish_score += 1

    # Stochastic
    if stoch_k[last] < 20 and stoch_d[last] < 20:
        bullish_score += 1
    if stoch_k[last] > 80 and stoch_d[last] > 80:
        bearish_score += 1

    # Price vs Bollinger
    price = close[last]
    if price <= bb_lower[last]:
        bullish_score += 1
    if price >= bb_upper[last]:
        bearish_score += 1

    # MA pullback
    if price < ma20[last] and trend_up:
        bullish_score += 1
    if price > ma20[last] and trend_down:
        bearish_score += 1

    # Final scoring
    buy_conf = bullish_score * 20
    sell_conf = bearish_score * 20

    # Entry logic
    if buy_conf >= 60 and trend_up:
        direction = "BUY"
        entry = price
        sl = entry - (atr[last] * 1.5)
        tp = entry + (atr[last] * 2.2)
        return {
            "direction": direction,
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "confidence": buy_conf,
        }

    if sell_conf >= 60 and trend_down:
        direction = "SELL"
        entry = price
        sl = entry + (atr[last] * 1.5)
        tp = entry - (atr[last] * 2.2)
        return {
            "direction": direction,
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "confidence": sell_conf,
        }

    return None