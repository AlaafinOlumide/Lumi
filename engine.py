# core/engine.py

import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
import datetime as dt

import numpy as np
import pandas as pd

logger = logging.getLogger("Lumi")


@dataclass
class Signal:
    symbol: str
    direction: str         # "BUY" or "SELL"
    entry: float
    sl: float
    tp: float
    confidence: float      # 0–100
    reason: str
    timeframe_entry: str   # e.g. "M5"
    created_at: dt.datetime


@dataclass
class RiskConfig:
    atr_period: int = 14
    atr_sl_multiplier: float = 1.5   # SL distance = ATR * multiplier
    rr: float = 2.0                  # TP = entry ± (SL_distance * rr)


class TradingEngine:
    """
    Lumi A3 Pro + PPSS confluence engine

    - Uses **A3 Pro** for higher-timeframe trend + volatility filter (H1 & M15).
    - Uses **PPSS** (BB + RSI + Stoch + candle) on M5 for sniper entries.
    - Only fires when both agree on direction.
    """

    def __init__(
        self,
        risk_config: Optional[RiskConfig] = None,
    ) -> None:
        self.risk = risk_config or RiskConfig()

    # ---------- Public API ----------

    def evaluate(
        self,
        symbol: str,
        m5_df: pd.DataFrame,
        m15_df: pd.DataFrame,
        h1_df: pd.DataFrame,
        now: dt.datetime,
    ) -> Optional[Signal]:
        """
        Evaluate all confluence and return a Signal or None.

        Expected columns in each df: ["open", "high", "low", "close", "datetime"]
        (datetime must be tz-aware and ascending)
        """
        try:
            if len(m5_df) < 60 or len(m15_df) < 60 or len(h1_df) < 60:
                logger.info("Not enough data for %s — need at least 60 candles per TF.", symbol)
                return None

            # Make copies so we don't mutate caller data
            m5 = m5_df.copy()
            m15 = m15_df.copy()
            h1 = h1_df.copy()

            # Compute indicators
            self._add_indicators(m5)
            self._add_indicators(m15)
            self._add_indicators(h1)

            # Get latest rows
            last_m5 = m5.iloc[-1]
            last_m15 = m15.iloc[-1]
            last_h1 = h1.iloc[-1]

            # A3 Pro (trend & volatility)
            a3_trend, a3_conf, a3_reason = self._a3_pro_signal(h1, m15)

            if a3_trend is None:
                logger.info("A3 Pro: No clear trend for %s — skipping.", symbol)
                return None

            # PPSS entry (M5)
            ppss_dir, ppss_conf, ppss_reason = self._ppss_signal(m5)

            if ppss_dir is None:
                logger.info("PPSS: No setup on M5 for %s.", symbol)
                return None

            # Confluence: directions must match
            if ppss_dir != a3_trend:
                logger.info(
                    "No confluence for %s — A3=%s, PPSS=%s.",
                    symbol, a3_trend, ppss_dir
                )
                return None

            direction = ppss_dir

            # Build risk: SL/TP from M5 ATR
            atr = m5["atr"].iloc[-1]
            if not np.isfinite(atr) or atr <= 0:
                logger.info("Invalid ATR for %s — skipping.", symbol)
                return None

            entry = float(last_m5["close"])
            sl, tp = self._build_sl_tp(entry, atr, direction)

            # Combine confidences (simple weighted average)
            total_conf = float(
                0.6 * a3_conf +
                0.4 * ppss_conf
            )

            reason = f"A3Pro+PPSS {direction} | A3: {a3_reason} | PPSS: {ppss_reason}"

            signal = Signal(
                symbol=symbol,
                direction=direction,
                entry=entry,
                sl=sl,
                tp=tp,
                confidence=round(total_conf, 1),
                reason=reason,
                timeframe_entry="M5",
                created_at=now,
            )

            logger.info(
                "Signal %s: %s @ %.3f | SL=%.3f | TP=%.3f | conf=%.1f | %s",
                symbol,
                direction,
                entry,
                sl,
                tp,
                signal.confidence,
                reason,
            )

            return signal

        except Exception as exc:
            logger.exception("Engine evaluation error for %s: %s", symbol, exc)
            return None

    # ---------- TP / SL helpers (for alerts in main loop) ----------

    @staticmethod
    def check_tp_sl_hit(
        current_price: float,
        signal: Signal,
        buffer_points: float = 0.0,
    ) -> Optional[str]:
        """
        Check if current_price has hit TP or SL for a given signal.

        Returns:
            "TP" | "SL" | None
        """
        if signal.direction == "BUY":
            if current_price >= signal.tp - buffer_points:
                return "TP"
            if current_price <= signal.sl + buffer_points:
                return "SL"
        else:  # SELL
            if current_price <= signal.tp + buffer_points:
                return "TP"
            if current_price >= signal.sl - buffer_points:
                return "SL"
        return None

    # ---------- Internal indicator builders ----------

    def _add_indicators(self, df: pd.DataFrame) -> None:
        """
        Adds all indicators used by both A3 Pro and PPSS in-place.
        Required columns: open, high, low, close
        """
        closes = df["close"]

        # Trend SMAs
        df["sma_fast"] = closes.rolling(20).mean()
        df["sma_slow"] = closes.rolling(50).mean()

        # ATR
        self._add_atr(df, period=self.risk.atr_period)

        # Bollinger Bands (PPSS)
        window = 20
        std_mult = 2.0
        mid = closes.rolling(window).mean()
        std = closes.rolling(window).std()
        df["bb_mid"] = mid
        df["bb_upper"] = mid + std_mult * std
        df["bb_lower"] = mid - std_mult * std

        # RSI 14
        df["rsi"] = self._rsi(closes, period=14)

        # Stochastic %K / %D (9,3)
        self._add_stochastic(df, k_period=9, d_period=3)

    def _add_atr(self, df: pd.DataFrame, period: int) -> None:
        high = df["high"]
        low = df["low"]
        close = df["close"]

        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = tr.rolling(period).mean()

    def _rsi(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)

        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()

        rs = avg_gain / (avg_loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _add_stochastic(self, df: pd.DataFrame, k_period: int, d_period: int) -> None:
        low_min = df["low"].rolling(k_period).min()
        high_max = df["high"].rolling(k_period).max()
        k = 100 * (df["close"] - low_min) / (high_max - low_min + 1e-9)
        d = k.rolling(d_period).mean()
        df["stoch_k"] = k
        df["stoch_d"] = d

    # ---------- A3 Pro (trend + volatility) ----------

    def _a3_pro_signal(
        self,
        h1: pd.DataFrame,
        m15: pd.DataFrame,
    ) -> Tuple[Optional[str], float, str]:
        """
        A3 Pro trend + volatility filter.

        Returns:
            (direction, confidence(0-100), reason)
        """
        last_h1 = h1.iloc[-1]
        last_m15 = m15.iloc[-1]

        # Trend direction from SMAs
        def dir_from_sma(row):
            if np.isnan(row["sma_fast"]) or np.isnan(row["sma_slow"]):
                return None
            if row["sma_fast"] > row["sma_slow"]:
                return "BUY"
            if row["sma_fast"] < row["sma_slow"]:
                return "SELL"
            return None

        trend_h1 = dir_from_sma(last_h1)
        trend_m15 = dir_from_sma(last_m15)

        if trend_h1 is None or trend_m15 is None:
            return None, 0.0, "SMAs not ready"

        if trend_h1 != trend_m15:
            return None, 0.0, f"Trend mismatch H1={trend_h1}, M15={trend_m15}"

        direction = trend_h1

        # Volatility filter via ATR on H1
        atr_series = h1["atr"].dropna()
        if len(atr_series) < 20:
            return direction, 60.0, f"{direction} | ATR sample too small"

        atr_now = atr_series.iloc[-1]
        atr_med = atr_series.rolling(20).median().iloc[-1]

        if not np.isfinite(atr_now) or atr_now <= 0:
            return None, 0.0, "Invalid ATR"

        # Accept if ATR is between 0.6x and 2.0x its 20-period median
        lower = 0.6 * atr_med
        upper = 2.0 * atr_med

        if not (lower <= atr_now <= upper):
            return None, 0.0, f"ATR outside range [{lower:.3f}, {upper:.3f}] (now {atr_now:.3f})"

        # Confidence from trend alignment and ATR "niceness"
        atr_score = max(0.0, 1.0 - abs(atr_now - atr_med) / (atr_med + 1e-9))
        conf = 70.0 + 30.0 * atr_score

        reason = f"{direction} | H1 & M15 trend aligned | ATR ok (now={atr_now:.3f}, med={atr_med:.3f})"
        return direction, conf, reason

    # ---------- PPSS (M5) ----------

    def _ppss_signal(self, m5: pd.DataFrame) -> Tuple[Optional[str], float, str]:
        """
        PPSS logic on M5 using:
        - Bollinger Bands (20,2)
        - RSI 14
        - Stochastic 9,3
        - Simple candle pattern
        """
        last = m5.iloc[-1]
        prev = m5.iloc[-2]

        close = last["close"]
        open_ = last["open"]
        bb_up = last["bb_upper"]
        bb_lo = last["bb_lower"]
        rsi = last["rsi"]
        k = last["stoch_k"]
        k_prev = prev["stoch_k"]

        if any(np.isnan([bb_up, bb_lo, rsi, k, k_prev])):
            return None, 0.0, "Indicators not ready on M5"

        # --- BUY setup ---
        buy_confluences = 0
        buy_reasons = []

        # 1) Price at / below lower band (mean-reversion entry)
        if close <= bb_lo * 1.01:
            buy_confluences += 1
            buy_reasons.append("close near/below lower BB")

        # 2) RSI oversold
        if rsi < 32:
            buy_confluences += 1
            buy_reasons.append(f"RSI oversold ({rsi:.1f})")

        # 3) Stoch turning up from oversold
        if k < 25 and k > k_prev:
            buy_confluences += 1
            buy_reasons.append(f"Stoch K rising from low ({k_prev:.1f}→{k:.1f})")

        # 4) Bullish candle (engulf or strong body)
        if self._is_bullish_reversal_candle(prev, last):
            buy_confluences += 1
            buy_reasons.append("bullish reversal candle")

        # --- SELL setup ---
        sell_confluences = 0
        sell_reasons = []

        if close >= bb_up * 0.99:
            sell_confluences += 1
            sell_reasons.append("close near/above upper BB")

        if rsi > 68:
            sell_confluences += 1
            sell_reasons.append(f"RSI overbought ({rsi:.1f})")

        if k > 75 and k < k_prev:
            sell_confluences += 1
            sell_reasons.append(f"Stoch K falling from high ({k_prev:.1f}→{k:.1f})")

        if self._is_bearish_reversal_candle(prev, last):
            sell_confluences += 1
            sell_reasons.append("bearish reversal candle")

        # Decide
        min_conf_factors = 2  # require at least 2/4 confluences

        if buy_confluences >= min_conf_factors and sell_confluences == 0:
            conf = 60 + 10 * buy_confluences
            return "BUY", float(conf), "; ".join(buy_reasons)

        if sell_confluences >= min_conf_factors and buy_confluences == 0:
            conf = 60 + 10 * sell_confluences
            return "SELL", float(conf), "; ".join(sell_reasons)

        return None, 0.0, "No clean PPSS setup"

    def _is_bullish_reversal_candle(self, prev: pd.Series, last: pd.Series) -> bool:
        # Bullish body
        if last["close"] <= last["open"]:
            return False
        body_last = abs(last["close"] - last["open"])
        body_prev = abs(prev["close"] - prev["open"])

        # Engulf or strong body vs previous
        if last["close"] > prev["open"] and last["open"] < prev["close"]:
            return True
        if body_last > body_prev * 1.3 and last["low"] < prev["low"]:
            return True
        return False

    def _is_bearish_reversal_candle(self, prev: pd.Series, last: pd.Series) -> bool:
        if last["close"] >= last["open"]:
            return False
        body_last = abs(last["close"] - last["open"])
        body_prev = abs(prev["close"] - prev["open"])

        if last["close"] < prev["open"] and last["open"] > prev["close"]:
            return True
        if body_last > body_prev * 1.3 and last["high"] > prev["high"]:
            return True
        return False

    # ---------- Risk / SL-TP ----------

    def _build_sl_tp(self, entry: float, atr: float, direction: str) -> Tuple[float, float]:
        sl_dist = self.risk.atr_sl_multiplier * atr
        tp_dist = sl_dist * self.risk.rr

        if direction == "BUY":
            sl = entry - sl_dist
            tp = entry + tp_dist
        else:
            sl = entry + sl_dist
            tp = entry - tp_dist

        return float(sl), float(tp)