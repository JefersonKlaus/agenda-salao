"""Use case (application layer): the salon's clients, by name. Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from agenda_core.application import sorted_by_name
from agenda_core.domain.models import Client
from agenda_core.ports import Dependencies


def list_clients(deps: Dependencies, owner: str) -> list[Client]:
    return sorted_by_name(deps.repo.list_clients(owner))
