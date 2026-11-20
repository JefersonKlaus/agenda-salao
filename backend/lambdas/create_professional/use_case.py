"""Use case (application layer): registers a professional, her services and work hours.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any, Mapping

from agenda_core.application import check_limit, check_professional
from agenda_core.domain.models import Professional
from agenda_core.ports import Dependencies


def create_professional(deps: Dependencies, owner: str, payload: Mapping[str, Any]) -> Professional:
    check_limit(deps.repo, owner, "professional")
    prof = Professional.from_input(payload)
    check_professional(deps.repo, owner, prof)
    deps.repo.save(owner, "professional", prof)
    return prof
