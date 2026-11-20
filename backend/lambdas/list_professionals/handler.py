"""Inbound adapter of this Lambda: GET /professionals -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import list_professionals

handle = endpoint(lambda deps, r: [p.to_dict() for p in list_professionals(deps, r.owner)])


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
