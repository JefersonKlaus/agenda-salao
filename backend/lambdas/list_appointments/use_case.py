"""Use case (application layer): appointments of a day (?date=) or a period (?from=&to=, week and month views).
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Mapping

from agenda_core.application import check_period
from agenda_core.domain.models import Appointment, parse_date
from agenda_core.ports import Dependencies


def list_appointments(deps: Dependencies, owner: str, query: Mapping[str, str]) -> list[Appointment]:
    if "from" in query or "to" in query:
        first, last = query.get("from"), query.get("to")
        check_period(first, last)
        return sorted(deps.repo.appointments_between(owner, first, last),
                      key=lambda a: (a.date, a.start, a.professional_name))
    date = query.get("date")
    parse_date(date)
    return sorted(deps.repo.appointments_on_day(owner, date), key=lambda a: (a.start, a.professional_name))
