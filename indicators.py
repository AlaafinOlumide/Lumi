import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def bollinger_bands(df: pd.DataFrame, period: int = 20, std_mult: float = 2.0):
    mid = sma(df["close"], period)
    std = df["close"].rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    gain_series = pd.Series(gain, index=df.index)
    loss_series = pd.Series(loss, index=df.index)
    avg_gain = gain_series.rolling(period).mean()
    avg_loss = loss_series.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi_values = 100 - (100 / (1 + rs))
    return rsi_values


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    lowest_low = df["low"].rolling(k_period).min()
    highest_high = df["high"].rolling(k_period).max()
    stoch_k = 100 * (df["close"] - lowest_low) / (highest_high - lowest_low)
    stoch_d = stoch_k.rolling(d_period).mean()
    return stoch_k, stoch_d


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def engulfing_pattern(df: pd.DataFrame) -> str | None:
    """
    Simple 2-candle engulfing detector.
    Returns "bullish", "bearish", or None.
    """
    if len(df) < 2:
        return None

    c1 = df.iloc[-2]
    c2 = df.iloc[-1]

    # Bullish engulfing
    if (
        c1["close"] < c1["open"]
        and c2["close"] > c2["open"]
        and c2["close"] > c1["open"]
        and c2["open"] < c1["close"]
    ):
        return "bullish"

    # Bearish engulfing
    if (
        c1["close"] > c1["open"]
        and c2["close"] < c2["open"]
        and c2["open"] > c1["close"]
        and c2["close"] < c1["open"]
    ):
        return "bearish"

    return None