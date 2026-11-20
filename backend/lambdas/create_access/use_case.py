"""Use case (application layer): creates a login to the app. Two ways in:
- from Acessos: {email, name, manager, provider}. A service provider (provider=true) gets her
  professional created with it, with no services and no days yet, for the manager to configure;
- from Profissionais: {email, professional_id, manager}: a login for a professional who has none.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from agenda_core.application import check_limit, get_item
from agenda_core.domain.errors import ValidationError
from agenda_core.domain.models import Access, Professional, new_id, parse_email, parse_name
from agenda_core.ports import Dependencies


def create_access(deps: Dependencies, owner: str, payload: Mapping[str, Any]) -> Access:
    email = parse_email(payload)
    manager = payload.get("manager", False)
    if not isinstance(manager, bool):
        raise ValidationError("gerente: envie true ou false")
    if payload.get("professional_id") is not None:
        prof = get_item(deps.repo, owner, "professional", payload["professional_id"])
        if prof.login:
            raise ValidationError(f"{prof.name} já tem acesso ({prof.login})")
        name = prof.name
    else:
        name = parse_name(payload)
        prof = None
        if payload.get("provider") is True:      # starts her professional: services and days come later
            check_limit(deps.repo, owner, "professional")
            prof = Professional(new_id(), name, (), ())
    # The login first: if the e-mail is taken, nothing else is saved.
    login_id = deps.identity.create_login(email, name, owner, prof.id if prof else None, manager)
    if prof:
        deps.repo.save(owner, "professional", replace(prof, login=email))
    access = Access(login_id, email, name, manager, prof.id if prof else None)
    deps.repo.save_access(owner, access)
    return access
