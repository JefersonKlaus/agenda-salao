"""Inbound adapter of this Lambda: GET /clients/{id} -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies
from agenda_core.domain.models import PHONE_RE

from .use_case import get_client

handle = endpoint(lambda deps, r: get_client(deps, r.owner, r.id), manager_only=True, id_pattern=PHONE_RE)


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
