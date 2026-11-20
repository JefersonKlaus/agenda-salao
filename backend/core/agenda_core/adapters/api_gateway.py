"""Inbound adapter shared by every Lambda: API Gateway event (HTTP API, payload v2) -> Request ->
the Lambda's action -> HTTP response. Login, role, body and errors are handled here, once."""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..domain.errors import BusinessError, ValidationError
from ..ports import Dependencies

log = logging.getLogger(__name__)
MAX_BODY = 10_000                       # bytes: no record needs more than this
MANAGER, EMPLOYEE = "manager", "employee"   # Cognito groups


@dataclass(frozen=True)
class Request:
    owner: str                          # salon id = `sub` of the token API Gateway already verified
    body: dict[str, Any]
    query: dict[str, str]
    id: Optional[str]                   # the {id} in the route, when it has one


Action = Callable[[Dependencies, Request], Any]
Handle = Callable[[dict[str, Any], Dependencies], dict[str, Any]]


def endpoint(action: Action, *, status: int = 200, manager_only: bool = False,
             id_pattern: Optional[re.Pattern] = None) -> Handle:
    """Wraps a Lambda's action. `manager_only`: employees get 403. `id_pattern`: an {id} that does
    not match is 404 before touching the database. A 204 answers with no body."""
    def handle(event: dict[str, Any], deps: Dependencies) -> dict[str, Any]:
        try:
            owner = _owner(event)
            if manager_only and _role(event) != MANAGER:
                return response(403, {"error": "só a gerente pode fazer isso"})
            id = (event.get("pathParameters") or {}).get("id")
            if id_pattern is not None and not (isinstance(id, str) and id_pattern.match(id)):
                return response(404, {"error": "rota não encontrada"})
            method = event["requestContext"]["http"]["method"]
            request = Request(owner, _body(event) if method in ("POST", "PUT") else {},
                              event.get("queryStringParameters") or {}, id)
            result = action(deps, request)
            return response(status, None if status == 204 else result)
        except PermissionError:
            return response(401, {"error": "não autenticado"})
        except BusinessError as error:
            return response(error.status, {"error": str(error)})
        except Exception:
            log.exception("unexpected error")
            return response(500, {"error": "erro interno, tente de novo"})
    return handle


def response(status: int, body: Any = None) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": "" if body is None else json.dumps(body, ensure_ascii=False)}


def _owner(event: dict[str, Any]) -> str:
    """Never taken from the body: that is what keeps each salon's data apart."""
    try:
        sub = event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        sub = None
    if not isinstance(sub, str) or not sub:
        raise PermissionError
    return sub


def _role(event: dict[str, Any]) -> str:
    """From the token's `cognito:groups`. API Gateway hands a list claim over as a string such as
    "[employee]" or "[manager employee]". A user in no group is the manager: the accounts created
    before the groups existed are all the salon's manager."""
    try:
        groups = event["requestContext"]["authorizer"]["jwt"]["claims"].get("cognito:groups") or []
    except (KeyError, TypeError, AttributeError):
        groups = []
    if isinstance(groups, str):
        groups = groups.strip("[]").replace(",", " ").split()
    return EMPLOYEE if EMPLOYEE in groups and MANAGER not in groups else MANAGER


def _body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", "replace")
    if not raw:
        return {}
    if len(raw) > MAX_BODY:
        raise ValidationError("corpo grande demais")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise ValidationError("corpo não é um JSON válido") from None
    if not isinstance(payload, dict):
        raise ValidationError("o corpo deve ser um objeto JSON")
    return payload
