"""Use case (application layer): gives an appointment to another professional (same day, time and service).
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from agenda_core.application import check_slot, get_item
from agenda_core.domain.errors import NotFound, ValidationError
from agenda_core.domain.models import APPOINTMENT_ID_RE, Appointment, parse_date
from agenda_core.ports import Dependencies


def change_appointment_professional(deps: Dependencies, owner: str, id: str,
                                    payload: Mapping[str, Any]) -> Appointment:
    if not isinstance(id, str) or not APPOINTMENT_ID_RE.match(id):
        raise NotFound("agendamento não encontrado")
    appt = deps.repo.get_appointment(owner, id)
    if appt is None:
        raise NotFound("agendamento não encontrado")
    prof = get_item(deps.repo, owner, "professional", payload.get("professional_id"))
    if prof.id == appt.professional_id:
        raise ValidationError("o agendamento já é com essa profissional")
    if appt.service_id not in prof.services:
        raise ValidationError("essa profissional não faz esse serviço")
    check_slot(deps.repo, owner, parse_date(appt.date), appt.start_min, appt.duration_min, prof)
    moved = replace(appt, professional_id=prof.id, professional_name=prof.name)
    deps.repo.change_appointment_professional(owner, appt, moved)   # swaps the locks atomically
    return moved
