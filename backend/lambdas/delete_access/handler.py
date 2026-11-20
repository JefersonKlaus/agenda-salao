"""Inbound adapter of this Lambda: DELETE /access/{id} -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
import re

from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import delete_access

_LOGIN_ID = re.compile(r"^[0-9a-f-]{36}$")        # Cognito's sub

handle = endpoint(lambda deps, r: delete_access(deps, r.owner, r.id), status=204, manager_only=True,
                  id_pattern=_LOGIN_ID)


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
