"""Inbound adapter of this Lambda: DELETE /appointments/{id} -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import cancel_appointment

handle = endpoint(lambda deps, r: cancel_appointment(deps, r.owner, r.id), status=204, manager_only=True)


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
