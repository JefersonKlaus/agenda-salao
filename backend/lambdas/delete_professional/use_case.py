"""Use case (application layer): deletes a professional; the appointments already made stay.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from agenda_core.application import get_item
from agenda_core.ports import Dependencies


def delete_professional(deps: Dependencies, owner: str, id: str) -> None:
    get_item(deps.repo, owner, "professional", id)
    deps.repo.delete(owner, "professional", id)
