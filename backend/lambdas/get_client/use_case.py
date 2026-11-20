"""Use case (application layer): a client and her history: every appointment (newest first), what she
already paid, what is open (already happened, not paid: to charge) and what is still ahead.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any

from agenda_core.domain.errors import NotFound
from agenda_core.domain.models import parse_date
from agenda_core.domain.scheduling import is_past
from agenda_core.ports import Dependencies


def get_client(deps: Dependencies, owner: str, phone: str) -> dict[str, Any]:
    client = deps.repo.get_client(owner, phone)
    if client is None:
        raise NotFound("cliente não encontrada")
    now = deps.now()
    history = sorted(deps.repo.client_appointments(owner, phone), key=lambda a: (a.date, a.start), reverse=True)
    happened = [a for a in history if is_past(parse_date(a.date), a.start_min, now)]
    open_ones = [a for a in happened if not a.paid]
    return {"client": client.to_dict(),
            "totals": {"visits": len(happened), "paid": sum(a.price_cents for a in history if a.paid),
                       "open": sum(a.price_cents for a in open_ones),
                       "upcoming": sum(a.price_cents for a in history if not a.paid and a not in happened)},
            "open": [a.to_dict() for a in sorted(open_ones, key=lambda a: (a.date, a.start))],
            "appointments": [a.to_dict() for a in history]}
