"""Use case (application layer): absences (sick, travelling...) that touch a period (?from=&to=).
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any

from agenda_core.application import MAX_TIME_OFF_RANGE_DAYS, check_period
from agenda_core.domain.models import TimeOff
from agenda_core.ports import Dependencies


def list_time_off(deps: Dependencies, owner: str, first: Any, last: Any) -> list[TimeOff]:
    check_period(first, last, MAX_TIME_OFF_RANGE_DAYS)
    return sorted(deps.repo.time_off_between(owner, first, last), key=lambda t: (t.first_day, t.start or ""))
