"""Use case (application layer): lists the salon's professionals, by name.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from agenda_core.application import sorted_by_name
from agenda_core.domain.models import Professional
from agenda_core.ports import Dependencies


def list_professionals(deps: Dependencies, owner: str) -> list[Professional]:
    return sorted_by_name(deps.repo.list_items(owner, "professional"))
