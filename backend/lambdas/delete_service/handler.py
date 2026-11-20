"""Inbound adapter of this Lambda: DELETE /services/{id} -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies
from agenda_core.domain.models import ITEM_ID_RE

from .use_case import delete_service

handle = endpoint(lambda deps, r: delete_service(deps, r.owner, r.id), status=204, manager_only=True,
                  id_pattern=ITEM_ID_RE)


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
