import numpy as np
import pandas as pd


def compute_rsi(close, period=14):
    delta = np.diff(close)
    gain = np.maximum(delta, 0)
    loss = np.maximum(-delta, 0)

    avg_gain = pd.Series(gain).ewm(alpha=1/period).mean()
    avg_loss = pd.Series(loss).ewm(alpha=1/period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return np.append([50], rsi.values)


def compute_stochastic(high, low, close, k=14, d=3):
    lowest = pd.Series(low).rolling(k).min()
    highest = pd.Series(high).rolling(k).max()
    stoch_k = 100 * ((close - lowest) / (highest - lowest))
    stoch_d = stoch_k.rolling(d).mean()
    return stoch_k.fillna(50).values, stoch_d.fillna(50).values


def compute_bollinger(close, period=20, std=2):
    mid = pd.Series(close).rolling(period).mean()
    sd = pd.Series(close).rolling(period).std()
    upper = mid + std * sd
    lower = mid - std * sd
    return mid.fillna(method="bfill").values, upper.fillna(method="bfill").values, lower.fillna(method="bfill").values


def compute_ma(close, period):
    return pd.Series(close).rolling(period).mean().fillna(method="bfill").values


def compute_atr(high, low, close, period=14):
    tr = np.maximum(high[1:], close[:-1])
    tr = np.maximum(tr - low[1:], high[1:] - close[:-1])
    atr = pd.Series(tr).rolling(period).mean().fillna(method="bfill")
    return np.append([atr.iloc[0]], atr.values)