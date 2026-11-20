"""Inbound adapter of this Lambda: GET /time-off -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import list_time_off

handle = endpoint(lambda deps, r: [t.to_dict() for t in list_time_off(deps, r.owner, r.query.get("from"), r.query.get("to"))])


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
