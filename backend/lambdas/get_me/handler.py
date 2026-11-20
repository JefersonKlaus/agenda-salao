"""Inbound adapter of this Lambda: GET /me -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import get_me

handle = endpoint(lambda deps, r: get_me(deps, r.owner, r.manager, r.professional_id))


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
