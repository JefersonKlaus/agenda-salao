"""Use case (application layer): deletes a service; the appointments already made stay.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from dataclasses import replace

from agenda_core.application import get_item
from agenda_core.ports import Dependencies


def delete_service(deps: Dependencies, owner: str, id: str) -> None:
    get_item(deps.repo, owner, "service", id)
    deps.repo.delete(owner, "service", id)
    for prof in deps.repo.list_items(owner, "professional"):     # nobody performs (or earns from) a service that is gone
        if id in prof.services or any(c.service_id == id for c in prof.commissions):
            deps.repo.save(owner, "professional", replace(prof, services=tuple(s for s in prof.services if s != id),
                                                          commissions=tuple(c for c in prof.commissions if c.service_id != id)))
