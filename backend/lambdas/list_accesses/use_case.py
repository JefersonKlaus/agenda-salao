"""Use case (application layer): the logins the manager created in the app, by name.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from agenda_core.application import sorted_by_name
from agenda_core.domain.models import Access
from agenda_core.ports import Dependencies


def list_accesses(deps: Dependencies, owner: str) -> list[Access]:
    return sorted_by_name(deps.repo.list_accesses(owner))
