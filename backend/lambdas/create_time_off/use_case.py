"""Use case (application layer): registers an absence and returns her appointments inside it (to be moved or cancelled).
The manager registers anyone's; an employee only her own. Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any, Mapping, Optional

from agenda_core.application import check_own_absence, get_item
from agenda_core.domain.models import Appointment, TimeOff
from agenda_core.domain.scheduling import overlaps
from agenda_core.ports import Dependencies


def create_time_off(deps: Dependencies, owner: str, payload: Mapping[str, Any], manager: bool = True,
                    professional_id: Optional[str] = None) -> tuple[TimeOff, list[Appointment]]:
    """The appointments inside the absence still exist: someone has to move or cancel them."""
    time_off = TimeOff.from_input(payload)
    check_own_absence(time_off, manager, professional_id)
    get_item(deps.repo, owner, "professional", time_off.professional_id)
    deps.repo.save_time_off(owner, time_off)
    affected = [a for a in deps.repo.appointments_between(owner, time_off.first_day, time_off.last_day)
                if a.professional_id == time_off.professional_id
                and overlaps(a.start_min, a.end_min, [time_off.interval_on(a.date)])]
    return time_off, sorted(affected, key=lambda a: (a.date, a.start))
