"""Identity in AWS: the salon's logins are Cognito users. The salon and the professional are written in
immutable custom attributes (infra/cognito.tf), so the token carries them and nobody can change them;
the group (manager / employee) says what the login may do."""
from __future__ import annotations

from typing import Any, Optional

from ..domain.errors import ValidationError


class CognitoIdentity:
    def __init__(self, client: Any, pool_id: str) -> None:
        self.client, self.pool_id = client, pool_id

    def create_login(self, email: str, name: str, salon: str, professional_id: Optional[str], manager: bool) -> str:
        attributes = [{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"},
                      {"Name": "name", "Value": name}, {"Name": "custom:salon", "Value": salon}]
        if professional_id:
            attributes.append({"Name": "custom:professional_id", "Value": professional_id})
        try:
            user = self.client.admin_create_user(UserPoolId=self.pool_id, Username=email, UserAttributes=attributes)
        except Exception as error:      # botocore.ClientError, without importing botocore here
            if getattr(error, "response", {}).get("Error", {}).get("Code") == "UsernameExistsException":
                raise ValidationError("já existe um acesso com esse e-mail") from None
            raise
        self.client.admin_add_user_to_group(UserPoolId=self.pool_id, Username=email,
                                            GroupName="manager" if manager else "employee")
        return next(a["Value"] for a in user["User"]["Attributes"] if a["Name"] == "sub")

    def delete_login(self, email: str) -> None:
        try:
            self.client.admin_delete_user(UserPoolId=self.pool_id, Username=email)
        except Exception as error:      # already gone: that is what was wanted
            if getattr(error, "response", {}).get("Error", {}).get("Code") != "UserNotFoundException":
                raise
