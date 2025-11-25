from __future__ import annotations

from datetime import datetime, time
import os

import pytz
from dotenv import load_dotenv

load_dotenv()

TZ_NAME = os.getenv("TZ_NAME", "Europe/London")
LOCAL_TZ = pytz.timezone(TZ_NAME)

# Trading windows as (start_str, end_str) in local time
TRADING_WINDOWS = [
    ("23:00", "04:30"),  # Asia
    ("07:00", "11:00"),  # London open
    ("12:00", "16:30"),  # NY overlap
]


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_trading_window(dt: datetime) -> bool:
    """
    Handles both normal and overnight windows (e.g. 23:00–04:30).
    """
    t = dt.time()
    for start_str, end_str in TRADING_WINDOWS:
        start_t = parse_hhmm(start_str)
        end_t = parse_hhmm(end_str)

        if start_t <= end_t:
            # simple same-day window
            if start_t <= t <= end_t:
                return True
        else:
            # overnight window, e.g. 23:00–04:30
            if t >= start_t or t <= end_t:
                return True
    return False


def detect_session(dt: datetime) -> str:
    """
    Rough session label for logging.
    """
    t = dt.time()

    if time(23, 0) <= t or t <= time(4, 30):
        return "Asia"
    if time(7, 0) <= t <= time(11, 0):
        return "London"
    if time(12, 0) <= t <= time(16, 30):
        return "New York"
    return "Off-hours"


def is_new_m5_close(last_minute: int | None, dt: datetime) -> tuple[bool, int | None]:
    """
    Returns (is_new_close, updated_last_minute).
    A new M5 close is when minute % 5 == 0 and != last_minute.
    """
    m = dt.minute
    if m % 5 != 0:
        return False, last_minute
    if last_minute == m:
        return False, last_minute
    return True, m