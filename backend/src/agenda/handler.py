"""Lambda entry point. It only wires the pieces together: database, clock and router."""
from __future__ import annotations

import os
from typing import Any

from .agenda import Agenda
from .clock import salon_now
from .dynamo_repository import DynamoRepository
from .http import handle

_agenda = None


def _get_agenda() -> Agenda:
    global _agenda
    if _agenda is None:             # created once per execution environment and reused
        import boto3                # already present in Lambda; imported here so tests don't require it
        repo = DynamoRepository(boto3.client("dynamodb"), os.environ["TABLE_NAME"])
        _agenda = Agenda(repo, salon_now)
    return _agenda


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return handle(event, _get_agenda())
