"""Use case (application layer): deletes a professional; the appointments already made stay. Her login
to the app, if she had one, is removed too: it would point to nobody.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from agenda_core.application import get_item, remove_access
from agenda_core.ports import Dependencies


def delete_professional(deps: Dependencies, owner: str, id: str) -> None:
    get_item(deps.repo, owner, "professional", id)
    for access in deps.repo.list_accesses(owner):
        if access.professional_id == id:
            remove_access(deps, owner, access)
    deps.repo.delete(owner, "professional", id)
