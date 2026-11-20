"""Use case (application layer): the month's money, from the appointments (cancelled ones are gone).
expected = everything booked in the month; paid = what clients already paid; pending = the rest;
commission = what the professionals earn for it (copied into each appointment when it was booked).
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

import calendar
import re
from typing import Any, Callable

from agenda_core.domain.errors import ValidationError
from agenda_core.domain.models import Appointment, parse_date
from agenda_core.domain.scheduling import is_past
from agenda_core.ports import Dependencies

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _amounts(appts: list[Appointment]) -> dict[str, int]:
    paid = sum(a.price_cents for a in appts if a.paid)
    expected = sum(a.price_cents for a in appts)
    return {"count": len(appts), "expected": expected, "paid": paid, "pending": expected - paid,
            "commission": sum(a.commission_cents for a in appts)}


def _by(appts: list[Appointment], key: Callable[[Appointment], str], name: Callable[[Appointment], str]) -> list[dict]:
    groups: dict[str, list[Appointment]] = {}
    for a in appts:
        groups.setdefault(key(a), []).append(a)
    rows = [{"id": k, "name": name(group[-1]), **_amounts(group)} for k, group in groups.items()]
    return sorted(rows, key=lambda r: (-r["expected"], r["name"].lower()))


def get_finance(deps: Dependencies, owner: str, month: Any) -> dict[str, Any]:
    match = _MONTH_RE.match(month) if isinstance(month, str) else None
    if not match:
        raise ValidationError("mês inválido: use AAAA-MM")
    year, number = int(match.group(1)), int(match.group(2))
    last_day = calendar.monthrange(year, number)[1]
    appts = deps.repo.appointments_between(owner, f"{month}-01", f"{month}-{last_day:02d}")
    now = deps.now()
    overdue = sorted((a for a in appts if not a.paid and is_past(parse_date(a.date), a.start_min, now)),
                     key=lambda a: (a.date, a.start, a.professional_name))
    return {"month": month, "totals": _amounts(appts),
            "by_professional": _by(appts, lambda a: a.professional_id, lambda a: a.professional_name),
            "by_service": _by(appts, lambda a: a.service_id, lambda a: a.service_name),
            "overdue": [a.to_dict() for a in overdue]}
