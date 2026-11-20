"""Inbound adapter of this Lambda: POST /time-off -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import create_time_off


def _action(deps, request):
    time_off, affected = create_time_off(deps, request.owner, request.body)
    return {"time_off": time_off.to_dict(), "affected": [a.to_dict() for a in affected]}


handle = endpoint(_action, status=201)


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
