"""NSE market hours utility (IST-aware)."""
from datetime import datetime, time, timedelta, timezone

_IST = timezone(timedelta(hours=5, minutes=30))
_MARKET_OPEN = time(9, 15)
_MARKET_CLOSE = time(15, 30)


def ist_now() -> datetime:
    return datetime.now(_IST)


def is_market_open(dt: datetime | None = None) -> bool:
    """Return True if dt (default: now) falls within NSE trading hours.

    Trading hours: Mon–Fri, 09:15–15:30 IST.
    No holiday calendar — callers that need holiday awareness should extend this.
    """
    if dt is None:
        dt = ist_now()
    elif dt.tzinfo is not None:
        dt = dt.astimezone(_IST)
    if dt.weekday() >= 5:  # Sat=5, Sun=6
        return False
    t = dt.time()
    return _MARKET_OPEN <= t < _MARKET_CLOSE


def ist_date_str(dt: datetime | None = None) -> str:
    """ISO date string in IST, e.g. '2026-05-11'."""
    if dt is None:
        dt = ist_now()
    elif dt.tzinfo is not None:
        dt = dt.astimezone(_IST)
    return dt.date().isoformat()
