"""Use case (application layer): free start times of a professional for a service on a day.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any

from agenda_core.application import check_active, salon_settings, service_and_professional
from agenda_core.domain.models import parse_date
from agenda_core.domain.scheduling import away_intervals, busy_intervals, free_slots
from agenda_core.ports import Dependencies


def get_availability(deps: Dependencies, owner: str, date: Any, service_id: Any, professional_id: Any,
                     include_past: bool = False) -> list[str]:
    """For booking (the manager's). Only times still ahead, unless `include_past` (?include_past=true):
    then also the ones that already passed, to record what happened."""
    day = parse_date(date)
    service, prof = service_and_professional(deps.repo, owner, service_id, professional_id)
    check_active(service)
    busy = (busy_intervals(deps.repo.appointments_on_day(owner, date), prof.id)
            + away_intervals(deps.repo.time_off_between(owner, date, date), prof.id, date))
    now = None if include_past else deps.now()
    return free_slots(salon_settings(deps.repo, owner), day, service.duration_min, busy, now, prof)
