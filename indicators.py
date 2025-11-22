
import numpy as np
import requests

API_KEY = "9ab283d3938d4a19b5481f72fa53df6b"

def compute_indicators(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&apikey={API_KEY}&outputsize=50"
    r = requests.get(url).json()

    closes = np.array([float(x["close"]) for x in r["values"][::-1]])
    if len(closes) < 20:
        return {"trend": "neutral", "momentum": "weak"}

    ma20 = closes[-20:].mean()
    ma5 = closes[-5:].mean()

    trend = "bullish" if ma5 > ma20 else "bearish"
    momentum = "strong" if abs(ma5 - ma20) > 0.3 else "weak"

    return {"trend": trend, "momentum": momentum}
