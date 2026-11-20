"""Composition root in AWS: plugs the ports into DynamoDB and the salon's clock."""
from __future__ import annotations

import os
from typing import Optional

from ..ports import Dependencies
from .clock import salon_now
from .cognito_identity import CognitoIdentity
from .dynamo_repository import DynamoRepository

_dependencies: Optional[Dependencies] = None


def aws_dependencies() -> Dependencies:
    global _dependencies
    if _dependencies is None:       # created once per execution environment and reused
        import boto3                # already present in Lambda; imported here so tests don't require it
        pool = os.environ.get("USER_POOL_ID")       # only for the Lambdas that create logins
        _dependencies = Dependencies(DynamoRepository(boto3.client("dynamodb"), os.environ["TABLE_NAME"]), salon_now,
                                     CognitoIdentity(boto3.client("cognito-idp"), pool) if pool else None)
    return _dependencies
