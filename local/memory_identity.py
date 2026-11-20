"""In-memory identity provider (Cognito's part, locally): the logins created in the app. Never deployed."""
from __future__ import annotations

import uuid
from typing import Optional

from agenda_core.domain.errors import ValidationError


class MemoryIdentity:
    def __init__(self) -> None:
        self.logins: dict[str, dict] = {}           # e-mail -> what Cognito would keep

    def create_login(self, email: str, name: str, salon: str, professional_id: Optional[str], manager: bool) -> str:
        if email in self.logins:
            raise ValidationError("já existe um acesso com esse e-mail")
        login_id = str(uuid.uuid4())
        self.logins[email] = {"id": login_id, "name": name, "salon": salon, "professional_id": professional_id,
                              "group": "manager" if manager else "employee"}
        return login_id

    def delete_login(self, email: str) -> None:
        self.logins.pop(email, None)
