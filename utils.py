import os
import requests
import pytz
from datetime import datetime


def now_london():
    return datetime.now(pytz.timezone("Europe/London"))


def in_trading_window(now, windows):
    for start, end in windows:
        t1 = datetime.strptime(start, "%H:%M").time()
        t2 = datetime.strptime(end, "%H:%M").time()
        if t1 <= now.time() <= t2:
            return True
    return False


def get_session_name(now):
    h = now.hour
    if 23 <= h or h < 4:
        return "Asia"
    if 7 <= h < 11:
        return "London"
    if 12 <= h < 16:
        return "NY"
    return "Other"


def fetch_twelvedata(symbol, interval):
    api_key = os.getenv("TD_API_KEY")
    if api_key is None:
        return None

    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&apikey={api_key}&outputsize=200"
    try:
        res = requests.get(url, timeout=10).json()
        if "status" in res and res["status"] == "error":
            return None

        df = res.get("values")
        if df is None:
            return None

        import pandas as pd
        df = pd.DataFrame(df)
        df = df.astype(float)
        df = df.iloc[::-1]  # oldest -> newest
        return df

    except:
        return None


def is_red_news():
    """Fake placeholder — always return False but keep structure."""
    return False


def last_close(df):
    return df["close"].values[-1]


def candle_is_bullish(df, i=-1):
    return df["close"].values[i] > df["open"].values[i]


def candle_is_bearish(df, i=-1):
    return df["close"].values[i] < df["open"].values[i]