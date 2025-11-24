import numpy as np
from datetime import datetime
from utils import get_price, get_ema, get_rsi, get_stochastic, get_bollinger

def analyze_market_and_generate_signal(pair, news_severity):

    # HIGH NEWS → Still allow signals but lower confidence
    news_multiplier = {"low": 1.0, "medium": 0.85, "high": 0.65}

    # ---- FETCH ALL TIMEFRAMES ----
    h1 = get_price(pair, "1h")
    m15 = get_price(pair, "15min")
    m5 = get_price(pair, "5min")

    # Any failure
    if h1 is None or m15 is None or m5 is None:
        return None

    # ---- INDICATORS H1 ----
    h1_ema20 = get_ema(h1, 20)
    h1_rsi = get_rsi(h1)
    h1_trend_up = h1["close"][-1] > h1_ema20[-1]
    h1_trend_down = h1["close"][-1] < h1_ema20[-1]

    # ---- INDICATORS M15 ----
    m15_ema9 = get_ema(m15, 9)
    m15_align_up = m15["close"][-1] > m15_ema9[-1]
    m15_align_down = m15["close"][-1] < m15_ema9[-1]

    # ---- INDICATORS M5 ---- (entry timeframe)
    rsi = get_rsi(m5)
    k, d = get_stochastic(m5)
    upper, mid, lower = get_bollinger(m5)

    price = m5["close"][-1]

    # ---- BUY CRITERIA ----
    buy_conditions = [
        h1_trend_up,
        m15_align_up,
        rsi[-1] > 50,
        k[-1] < 30,
        price <= lower[-1],  # oversold + BB deviation
    ]

    buy_score = sum(buy_conditions) / len(buy_conditions)

    # ---- SELL CRITERIA ----
    sell_conditions = [
        h1_trend_down,
        m15_align_down,
        rsi[-1] < 50,
        k[-1] > 70,
        price >= upper[-1],  # overbought + BB deviation
    ]

    sell_score = sum(sell_conditions) / len(sell_conditions)

    # ---- CHOOSE TRADE ----
    direction = None
    confidence = 0

    if buy_score >= 0.55:  # reduced threshold so signals are frequent
        direction = "BUY"
        confidence = int(buy_score * 100 * news_multiplier[news_severity])
        sl = price - 2.0
        tp = price + 4.0

        return {
            "direction": direction,
            "confidence": confidence,
            "entry": price,
            "sl": sl,
            "tp": tp,
            "reason": f"BUY score: {buy_score:.2f}",
        }

    if sell_score >= 0.55:
        direction = "SELL"
        confidence = int(sell_score * 100 * news_multiplier[news_severity])
        sl = price + 2.0
        tp = price - 4.0

        return {
            "direction": direction,
            "confidence": confidence,
            "entry": price,
            "sl": sl,
            "tp": tp,
            "reason": f"SELL score: {sell_score:.2f}",
        }

    return None