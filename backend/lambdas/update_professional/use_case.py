"""Use case (application layer): edits a professional, her services and work hours.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any, Mapping

from dataclasses import replace

from agenda_core.application import check_professional, get_item
from agenda_core.domain.models import Professional
from agenda_core.ports import Dependencies


def update_professional(deps: Dependencies, owner: str, id: str, payload: Mapping[str, Any]) -> Professional:
    current = get_item(deps.repo, owner, "professional", id)
    prof = replace(Professional.from_input(payload, id=id), login=current.login)     # the access stays hers
    check_professional(deps.repo, owner, prof)
    deps.repo.save(owner, "professional", prof)
    return prof
