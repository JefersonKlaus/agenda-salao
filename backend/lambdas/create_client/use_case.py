"""Use case (application layer): registers a client without booking (booking registers her too).
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any, Mapping

from agenda_core.domain.errors import ValidationError
from agenda_core.domain.models import Client
from agenda_core.ports import Dependencies


def create_client(deps: Dependencies, owner: str, payload: Mapping[str, Any]) -> Client:
    client = Client.from_input(payload)
    existing = deps.repo.get_client(owner, client.phone)
    if existing:
        raise ValidationError(f"esse telefone já é de {existing.name}")
    deps.repo.save_client(owner, client)
    return client
