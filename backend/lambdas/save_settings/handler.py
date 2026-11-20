"""Inbound adapter of this Lambda: PUT /settings -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import save_settings

handle = endpoint(lambda deps, r: save_settings(deps, r.owner, r.body).to_dict(), manager_only=True)


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
