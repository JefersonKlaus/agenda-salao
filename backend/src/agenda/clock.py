"""The salon's clock. Every date and time in the agenda is Brasília time, whatever the time zone of
the machine running the code (AWS and many containers run in UTC, which is 3 hours ahead)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Brasília is UTC-3 all year round (no daylight saving time since 2019). Avoids depending on tzdata.
BRASILIA_TZ = timezone(timedelta(hours=-3))


def salon_now() -> datetime:
    """The current date and time in Brasília, without tzinfo (like every time in the agenda)."""
    return datetime.now(BRASILIA_TZ).replace(tzinfo=None)
