"""Use case (application layer): books an appointment, if the time is free (atomic lock in the database).
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any, Mapping

from agenda_core.application import check_active, check_slot, service_and_professional
from agenda_core.domain.models import Appointment, Client, new_id, parse_client, parse_date, parse_time
from agenda_core.ports import Dependencies


def book_appointment(deps: Dependencies, owner: str, payload: Mapping[str, Any]) -> Appointment:
    """Only the manager books (handler.py), also at times that already passed, to record what happened."""
    day, start = parse_date(payload.get("date")), parse_time(payload.get("start"))
    client_name, phone = parse_client(payload)
    service, prof = service_and_professional(deps.repo, owner, payload.get("service_id"),
                                             payload.get("professional_id"))
    check_active(service)
    check_slot(deps.repo, owner, day, start, service.duration_min, prof)
    date = day.isoformat()
    appt = Appointment(f"{date}_{start // 60:02d}{start % 60:02d}_{new_id()}", date,
                       payload["start"], service.duration_min, prof.id, prof.name, service.id,
                       service.name, service.price_cents, client_name, phone,
                       commission_cents=prof.commission_for(service.id, service.price_cents))
    deps.repo.create_appointment(owner, appt)
    deps.repo.save_client(owner, Client(phone, client_name))       # registers her, or keeps her name up to date
    return appt
