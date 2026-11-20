"""Use case (application layer): removes a login: that person can no longer get in. Her professional
(and its appointments) stays, without access. Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from agenda_core.application import remove_access
from agenda_core.domain.errors import NotFound
from agenda_core.ports import Dependencies


def delete_access(deps: Dependencies, owner: str, id: str) -> None:
    access = next((a for a in deps.repo.list_accesses(owner) if a.id == id), None)
    if access is None:
        raise NotFound("acesso não encontrado")
    remove_access(deps, owner, access)
