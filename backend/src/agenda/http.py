"""Translates the API Gateway event (HTTP API v2) into Agenda calls and returns the JSON response."""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Callable

from .agenda import Agenda
from .errors import BusinessError, ValidationError

log = logging.getLogger(__name__)
MAX_BODY = 10_000                       # bytes: no record needs more than this
_ID = r"([0-9a-f]{8})"
_APPT_ID = r"([0-9a-f_-]{15,40})"
_TIME_OFF_ID = r"([0-9a-f_-]{15,30})"


def _crud_handlers(kind: str) -> tuple[Callable, ...]:
    """The /services and /professionals routes share the same code."""
    def list_items(a, o, c): return [i.to_dict() for i in a.list_items(o, kind)]
    def create(a, o, c): return 201, a.create(o, kind, c["body"]).to_dict()
    def update(a, o, c): return a.update(o, kind, c["id"], c["body"]).to_dict()
    def remove(a, o, c): return 204, a.remove(o, kind, c["id"])
    return list_items, create, update, remove


def _list_appointments(agenda: Agenda, owner: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    """?date=YYYY-MM-DD for one day, or ?from=...&to=... for a period (week and month views)."""
    q = context["query"]
    if "from" in q or "to" in q:
        items = agenda.schedule_between(owner, q.get("from"), q.get("to"))
    else:
        items = agenda.day_schedule(owner, q.get("date"))
    return [x.to_dict() for x in items]


def _create_time_off(agenda: Agenda, owner: str, context: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """The new absence, plus her appointments inside it (they need to be moved or cancelled)."""
    time_off, affected = agenda.create_time_off(owner, context["body"])
    return 201, {"time_off": time_off.to_dict(), "affected": [a.to_dict() for a in affected]}


def _build_routes() -> list[tuple[str, re.Pattern, Callable]]:
    """Each handler receives (agenda, owner, context) and returns a body or (status, body)."""
    table = []
    for path, kind in (("services", "service"), ("professionals", "professional")):
        list_items, create, update, remove = _crud_handlers(kind)
        table += [("GET", f"/{path}", list_items), ("POST", f"/{path}", create),
                  ("PUT", f"/{path}/{_ID}", update), ("DELETE", f"/{path}/{_ID}", remove)]
    table += [
        ("GET", "/settings", lambda a, o, c: a.settings(o).to_dict()),
        ("PUT", "/settings", lambda a, o, c: a.save_settings(o, c["body"]).to_dict()),
        ("GET", "/appointments", _list_appointments),
        ("POST", "/appointments", lambda a, o, c: (201, a.book(o, c["body"]).to_dict())),
        ("DELETE", f"/appointments/{_APPT_ID}", lambda a, o, c: (204, a.cancel(o, c["id"]))),
        ("PUT", f"/appointments/{_APPT_ID}/professional",
         lambda a, o, c: a.change_professional(o, c["id"], c["body"]).to_dict()),
        ("GET", "/time-off", lambda a, o, c: [t.to_dict() for t in a.time_off_between(
            o, c["query"].get("from"), c["query"].get("to"))]),
        ("POST", "/time-off", _create_time_off),
        ("DELETE", f"/time-off/{_TIME_OFF_ID}", lambda a, o, c: (204, a.delete_time_off(o, c["id"]))),
        ("GET", "/availability", lambda a, o, c: a.availability(
            o, c["query"].get("date"), c["query"].get("service_id"), c["query"].get("professional_id"))),
    ]
    return [(m, re.compile(f"^{p}$"), f) for m, p, f in table]


ROUTES = _build_routes()


def _response(status: int, body: Any = None) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": "" if body is None else json.dumps(body, ensure_ascii=False)}


def _owner(event: dict[str, Any]) -> str:
    """Salon id = `sub` of the token already verified by API Gateway. Never taken from the body."""
    try:
        sub = event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        sub = None
    if not isinstance(sub, str) or not sub:
        raise PermissionError
    return sub


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


def handle(event: dict[str, Any], agenda: Agenda) -> dict[str, Any]:
    try:
        owner = _owner(event)
        method = event["requestContext"]["http"]["method"]
        path = event.get("rawPath", "").rstrip("/") or "/"
        path_exists = False
        for m, pattern, handler in ROUTES:
            match = pattern.match(path)
            if not match:
                continue
            path_exists = True
            if m != method:
                continue
            context = {"body": _body(event) if method in ("POST", "PUT") else {},
                       "query": event.get("queryStringParameters") or {},
                       "id": match.group(1) if match.groups() else None}
            result = handler(agenda, owner, context)
            if isinstance(result, tuple):
                status, body = result
                return _response(status, None if status == 204 else body)   # 204 carries no body
            return _response(200, result)
        return _response(405 if path_exists else 404, {"error": "rota não encontrada"})
    except PermissionError:
        return _response(401, {"error": "não autenticado"})
    except BusinessError as error:
        return _response(error.status, {"error": str(error)})
    except Exception:
        log.exception("unexpected error")
        return _response(500, {"error": "erro interno, tente de novo"})
