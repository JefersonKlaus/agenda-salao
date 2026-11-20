"""Inbound adapter of this Lambda: PUT /appointments/{id}/payment -> use case. `handle(event, deps)` is what the local
server and the tests call; `lambda_handler` is what AWS calls, plugged into DynamoDB."""
from agenda_core.adapters.api_gateway import endpoint
from agenda_core.adapters.aws import aws_dependencies

from .use_case import set_appointment_payment

handle = endpoint(lambda deps, r: set_appointment_payment(deps, r.owner, r.id, r.body).to_dict(), manager_only=True)


def lambda_handler(event, context):
    return handle(event, aws_dependencies())
