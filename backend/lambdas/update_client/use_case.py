"""Use case (application layer): changes a client's name. The phone is her key and stays; the
appointments keep the name they were booked with (like the price).
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any, Mapping

from agenda_core.domain.errors import NotFound
from agenda_core.domain.models import Client
from agenda_core.ports import Dependencies


def update_client(deps: Dependencies, owner: str, phone: str, payload: Mapping[str, Any]) -> Client:
    if deps.repo.get_client(owner, phone) is None:
        raise NotFound("cliente não encontrada")
    client = Client.from_input({**payload, "phone": phone})
    deps.repo.save_client(owner, client)
    return client
