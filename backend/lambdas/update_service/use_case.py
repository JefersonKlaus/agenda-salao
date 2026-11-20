"""Use case (application layer): edits a service, or disables / enables it.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any, Mapping

from agenda_core.application import get_item
from agenda_core.domain.models import Service
from agenda_core.ports import Dependencies


def update_service(deps: Dependencies, owner: str, id: str, payload: Mapping[str, Any]) -> Service:
    current = get_item(deps.repo, owner, "service", id)
    if "active" not in payload:
        payload = {**payload, "active": current.active}        # editing does not re-enable it
    service = Service.from_input(payload, id=id)
    deps.repo.save(owner, "service", service)
    return service
