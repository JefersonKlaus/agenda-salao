"""Inbound adapter of this Lambda: DELETE /time-off/{id} -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import delete_time_off

handle = endpoint(lambda deps, r: delete_time_off(deps, r.owner, r.id), status=204)


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
