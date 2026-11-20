"""Use case (application layer): cancels an appointment and frees its time.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from agenda_core.application import get_appointment
from agenda_core.domain.errors import NotFound
from agenda_core.domain.models import Appointment
from agenda_core.ports import Dependencies


def cancel_appointment(deps: Dependencies, owner: str, id: str) -> Appointment:
    get_appointment(deps.repo, owner, id)
    appt = deps.repo.cancel_appointment(owner, id)
    if appt is None:
        raise NotFound("agendamento não encontrado")
    return appt
