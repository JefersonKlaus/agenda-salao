"""Use case (application layer): registers a service (name, duration, price).
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any, Mapping

from agenda_core.application import check_limit
from agenda_core.domain.models import Service
from agenda_core.ports import Dependencies


def create_service(deps: Dependencies, owner: str, payload: Mapping[str, Any]) -> Service:
    check_limit(deps.repo, owner, "service")
    service = Service.from_input(payload)
    deps.repo.save(owner, "service", service)
    return service
