"""Inbound adapter of this Lambda: GET /availability -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import get_availability

handle = endpoint(lambda deps, r: get_availability(deps, r.owner, r.query.get("date"), r.query.get("service_id"),
                                             r.query.get("professional_id")))


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
