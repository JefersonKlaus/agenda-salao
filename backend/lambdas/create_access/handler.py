"""Inbound adapter of this Lambda: POST /access -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import create_access

handle = endpoint(lambda deps, r: create_access(deps, r.owner, r.body).to_dict(), status=201, manager_only=True)


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
