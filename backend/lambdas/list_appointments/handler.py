"""Inbound adapter of this Lambda: GET /appointments -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import list_appointments

handle = endpoint(lambda deps, r: [a.to_dict() for a in list_appointments(deps, r.owner, r.query)])


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
