"""Use case (application layer): who is logged in, for the screen to show what she may use.
The API checks the same on every request. Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any, Optional

from agenda_core.ports import Dependencies


def get_me(deps: Dependencies, owner: str, manager: bool, professional_id: Optional[str]) -> dict[str, Any]:
    return {"manager": manager, "professional_id": professional_id}
