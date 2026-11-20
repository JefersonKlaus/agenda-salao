"""Use case (application layer): marks an appointment as paid by the client, or undoes it.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from agenda_core.application import get_appointment
from agenda_core.domain.errors import ValidationError
from agenda_core.domain.models import Appointment
from agenda_core.ports import Dependencies


def set_appointment_payment(deps: Dependencies, owner: str, id: str, payload: Mapping[str, Any]) -> Appointment:
    paid = payload.get("paid")
    if not isinstance(paid, bool):
        raise ValidationError("pago: envie true ou false")
    appt = get_appointment(deps.repo, owner, id)
    updated = replace(appt, paid=paid)
    if updated != appt:
        deps.repo.update_appointment(owner, appt, updated)
    return updated
