"""Use case (application layer): gives an appointment to another professional (same day, time and service).
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from agenda_core.application import check_slot, get_appointment, get_item
from agenda_core.domain.errors import ValidationError
from agenda_core.domain.models import Appointment, parse_date
from agenda_core.ports import Dependencies


def change_appointment_professional(deps: Dependencies, owner: str, id: str,
                                    payload: Mapping[str, Any]) -> Appointment:
    appt = get_appointment(deps.repo, owner, id)
    prof = get_item(deps.repo, owner, "professional", payload.get("professional_id"))
    if prof.id == appt.professional_id:
        raise ValidationError("o agendamento já é com essa profissional")
    if appt.service_id not in prof.services:
        raise ValidationError("essa profissional não faz esse serviço")
    check_slot(deps.repo, owner, parse_date(appt.date), appt.start_min, appt.duration_min, prof)
    moved = replace(appt, professional_id=prof.id, professional_name=prof.name,      # hers now: her commission
                    commission_cents=prof.commission_for(appt.service_id, appt.price_cents))
    deps.repo.change_appointment_professional(owner, appt, moved)   # swaps the locks atomically
    return moved
