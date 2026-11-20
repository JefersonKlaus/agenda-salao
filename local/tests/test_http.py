import base64
import json

import pytest

from agenda_core.adapters.api_gateway import MAX_BODY
from agenda_core.ports import Dependencies
from api_gateway import ROUTES, dispatch
from memory_identity import MemoryIdentity
from memory_repository import MemoryRepository
from conftest import NOW, ROOT, salon_hours


def call(deps, method, path, body=None, query=None, owner="owner-a", base64_=False, groups=None, claims=None):
    event = {"rawPath": path, "requestContext": {"http": {"method": method}},
             "queryStringParameters": query}
    if owner:
        token = {"sub": owner, **({} if groups is None else {"cognito:groups": groups}), **(claims or {})}
        event["requestContext"]["authorizer"] = {"jwt": {"claims": token}}
    if body is not None:
        text = body if isinstance(body, str) else json.dumps(body)
        event["body"] = base64.b64encode(text.encode()).decode() if base64_ else text
        event["isBase64Encoded"] = base64_
    response = dispatch(event, deps)
    return response["statusCode"], json.loads(response["body"]) if response["body"] else None


@pytest.fixture
def api():
    return Dependencies(MemoryRepository(), lambda: NOW, MemoryIdentity())


def set_up(api):
    _, haircut = call(api, "POST", "/services", {"name": "Haircut", "duration_min": 60, "price_cents": 8000})
    _, ana = call(api, "POST", "/professionals", {"name": "Ana", "services": [haircut["id"]]})
    return haircut, ana


def test_full_flow(api):
    haircut, ana = set_up(api)
    assert call(api, "GET", "/services")[1][0]["name"] == "Haircut"
    status, times = call(api, "GET", "/availability",
                         query={"date": "2026-11-17", "service_id": haircut["id"], "professional_id": ana["id"]})
    assert status == 200 and times[0] == "09:00"
    request = {"date": "2026-11-17", "start": "10:00", "service_id": haircut["id"],
               "professional_id": ana["id"], "client_name": "Maria", "client_phone": ""}
    status, appt = call(api, "POST", "/appointments", request)
    assert status == 201 and appt["service_name"] == "Haircut"
    assert call(api, "POST", "/appointments", request)[0] == 400
    assert len(call(api, "GET", "/appointments", query={"date": "2026-11-17"})[1]) == 1
    assert call(api, "DELETE", f"/appointments/{appt['id']}") == (204, None)
    assert call(api, "DELETE", f"/appointments/{appt['id']}")[0] == 404
    assert call(api, "PUT", "/settings", salon_hours([1], "08:00", "12:00"))[0] == 200
    assert call(api, "GET", "/settings")[1] == {"hours": [{"day": 1, "start": "08:00", "end": "12:00"}]}


def test_no_login_is_401_and_does_not_touch_the_database(api):
    assert call(api, "GET", "/services", owner=None)[0] == 401
    assert call(api, "GET", "/services", owner="")[0] == 401
    assert call(api, "POST", "/services", {"name": "Haircut", "duration_min": 30, "price_cents": 1},
                owner=None)[0] == 401
    assert call(api, "GET", "/services")[1] == []                    # nothing was written


def test_the_owner_comes_from_the_token_not_from_the_body(api):
    call(api, "POST", "/services", {"name": "Haircut", "duration_min": 30, "price_cents": 1,
                                    "owner": "owner-b", "PK": "SALAO#owner-b"})
    assert call(api, "GET", "/services", owner="owner-b")[1] == []
    assert len(call(api, "GET", "/services", owner="owner-a")[1]) == 1


def test_update_and_remove_service(api):
    haircut, _ = set_up(api)
    status, updated = call(api, "PUT", f"/services/{haircut['id']}", {"name": "New", "duration_min": 30, "price_cents": 5})
    assert status == 200 and updated["name"] == "New"
    assert call(api, "DELETE", f"/services/{haircut['id']}") == (204, None)
    assert call(api, "DELETE", f"/services/{haircut['id']}")[0] == 404


@pytest.mark.parametrize("method, path, expected", [
    ("GET", "/nothing", 404), ("PATCH", "/services", 404), ("GET", "/services/xyz", 404),
    ("GET", "/services/", 404), ("DELETE", "/services/ZZZZZZZZ", 404),
    ("GET", "/appointments", 400),                                # missing ?date=
])
def test_odd_routes(api, method, path, expected):
    assert call(api, method, path)[0] == expected


@pytest.mark.parametrize("body", ["{broken", "[1, 2]", '"text"', "x" * (MAX_BODY + 1)])
def test_bad_body_becomes_400(api, body):
    assert call(api, "POST", "/services", body)[0] == 400


def test_base64_body(api):
    status, _ = call(api, "POST", "/services", {"name": "Haircut", "duration_min": 30, "price_cents": 1},
                     base64_=True)
    assert status == 201


def test_unexpected_error_does_not_leak_details(api, caplog):
    class Broken(MemoryRepository):
        def list_items(self, owner, kind):
            raise RuntimeError("database-password")
    status, body = call(Dependencies(Broken(), lambda: NOW), "GET", "/services")
    assert status == 500 and "password" not in json.dumps(body)
    assert "database-password" in caplog.text                     # stays only in the log


def test_professional_work_hours_and_period_through_the_api(api):
    haircut, ana = set_up(api)
    hours = [{"day": 1, "start": "10:00", "end": "12:00"}]
    status, updated = call(api, "PUT", f"/professionals/{ana['id']}",
                           {"name": "Ana", "services": [haircut["id"]], "work_hours": hours})
    assert status == 200 and updated["work_hours"] == hours
    assert ana["work_hours"] is None                                        # created without: follows the salon
    assert call(api, "GET", "/availability", query={"date": "2026-11-17", "service_id": haircut["id"],
                                                    "professional_id": ana["id"]})[1] == ["10:00", "10:15", "10:30", "10:45", "11:00"]
    request = {"date": "2026-11-17", "start": "10:00", "service_id": haircut["id"],
               "professional_id": ana["id"], "client_name": "Maria"}
    assert call(api, "POST", "/appointments", request)[0] == 201
    status, found = call(api, "GET", "/appointments", query={"from": "2026-11-16", "to": "2026-11-22"})
    assert status == 200 and [a["client_name"] for a in found] == ["Maria"]
    assert call(api, "GET", "/appointments", query={"from": "2026-11-16"})[0] == 400
    assert call(api, "GET", "/appointments", query={"from": "2026-11-22", "to": "2026-11-16"})[0] == 400


def test_time_off_and_change_professional_through_the_api(api):
    haircut, ana = set_up(api)
    _, bia = call(api, "POST", "/professionals", {"name": "Bia", "services": [haircut["id"]]})
    request = {"date": "2026-11-17", "start": "10:00", "service_id": haircut["id"], "professional_id": ana["id"],
               "client_name": "Maria"}
    _, appt = call(api, "POST", "/appointments", request)
    status, body = call(api, "POST", "/time-off", {"professional_id": ana["id"], "first_day": "2026-11-17", "reason": "Doente"})
    assert status == 201 and body["time_off"]["reason"] == "Doente" and [a["id"] for a in body["affected"]] == [appt["id"]]
    status, moved = call(api, "PUT", f"/appointments/{appt['id']}/professional", {"professional_id": bia["id"]})
    assert status == 200 and moved["professional_name"] == "Bia"
    assert call(api, "PUT", f"/appointments/{appt['id']}/professional", {"professional_id": ana["id"]})[0] == 400   # away
    status, found = call(api, "GET", "/time-off", query={"from": "2026-11-16", "to": "2026-11-22"})
    assert status == 200 and len(found) == 1
    assert call(api, "DELETE", f"/time-off/{found[0]['id']}") == (204, None)
    assert call(api, "DELETE", f"/time-off/{found[0]['id']}")[0] == 404
    assert call(api, "GET", "/time-off", query={"from": "2026-11-16"})[0] == 400


def test_disable_service_through_the_api(api):
    haircut, ana = set_up(api)
    status, updated = call(api, "PUT", f"/services/{haircut['id']}", {**haircut, "active": False})
    assert status == 200 and updated["active"] is False
    assert call(api, "GET", "/availability", query={"date": "2026-11-17", "service_id": haircut["id"],
                                                    "professional_id": ana["id"]})[0] == 400


@pytest.mark.parametrize("groups", ["[employee]", ["employee"], "employee"])
def test_employee_cannot_change_catalog_or_settings(api, groups):
    haircut, ana = set_up(api)
    as_employee = dict(groups=groups)
    for method, path, body in [
            ("POST", "/services", {"name": "Color", "duration_min": 60, "price_cents": 1}),
            ("PUT", f"/services/{haircut['id']}", {"name": "X", "duration_min": 60, "price_cents": 1}),
            ("DELETE", f"/services/{haircut['id']}", None),
            ("POST", "/professionals", {"name": "Bia", "services": []}),
            ("PUT", f"/professionals/{ana['id']}", {"name": "X", "services": []}),
            ("DELETE", f"/professionals/{ana['id']}", None),
            ("PUT", "/settings", salon_hours([0], "09:00", "18:00"))]:
        assert call(api, method, path, body, **as_employee)[0] == 403, (method, path)
    assert call(api, "GET", "/services")[1][0]["name"] == "Haircut"          # nothing changed
    assert [p["name"] for p in call(api, "GET", "/professionals")[1]] == ["Ana"]


def test_employee_sees_the_agenda_but_does_not_book(api):
    haircut, ana = set_up(api)
    for path in ("/services", "/professionals", "/settings"):
        assert call(api, "GET", path, groups="[employee]")[0] == 200
    status, _ = call(api, "GET", "/appointments", query={"date": "2026-11-17"}, groups="[employee]")
    assert status == 200
    request = {"date": "2026-11-17", "start": "10:00", "service_id": haircut["id"], "professional_id": ana["id"],
               "client_name": "Maria"}
    _, appt = call(api, "POST", "/appointments", request)                        # the manager books it
    query = {"date": "2026-11-17", "service_id": haircut["id"], "professional_id": ana["id"]}
    for method, path, body, params in [("POST", "/appointments", request, None),
                                       ("GET", "/availability", None, query),
                                       ("DELETE", f"/appointments/{appt['id']}", None, None),
                                       ("PUT", f"/appointments/{appt['id']}/professional", {"professional_id": ana["id"]}, None),
                                       ("PUT", f"/appointments/{appt['id']}/payment", {"paid": True}, None),
                                       ("GET", "/finance", None, {"month": "2026-11"}),
                                       ("GET", "/access", None, None),
                                       ("POST", "/access", {"email": "x@y.com", "name": "X"}, None)]:
        assert call(api, method, path, body, query=params, groups="[employee]")[0] == 403, (method, path)


@pytest.mark.parametrize("groups", [None, "[manager]", "[manager employee]", ["manager"]])
def test_manager_or_no_group_changes_the_catalog(api, groups):
    status, _ = call(api, "POST", "/services", {"name": "Color", "duration_min": 60, "price_cents": 1},
                     groups=groups)
    assert status == 201


def test_one_lambda_per_action_each_with_its_own_route():
    """backend/lambdas/<action>/: the use case, the inbound adapter and lambda.json (read by Terraform)."""
    folders = sorted(p.name for p in (ROOT / "backend" / "lambdas").iterdir() if p.is_dir() and p.name != "__pycache__")
    assert folders == sorted(name for _, _, name, _ in ROUTES)
    for name in folders:
        for file in ("__init__.py", "use_case.py", "handler.py", "lambda.json"):
            assert (ROOT / "backend" / "lambdas" / name / file).is_file(), (name, file)
    routes = [(method, pattern.pattern) for method, pattern, _, _ in ROUTES]
    assert len(routes) == len(set(routes)), "two Lambdas with the same route"


def test_read_only_lambdas_never_write(api):
    """The Lambdas marked "read" get an IAM role that cannot write: their use case must not need it."""
    reads = [name for _, _, name, _ in ROUTES
             if json.loads((ROOT / "backend" / "lambdas" / name / "lambda.json").read_text())["database"] == "read"]
    assert reads and all(n.startswith(("list_", "get_")) for n in reads)
    source = "\n".join((ROOT / "backend" / "lambdas" / n / "use_case.py").read_text(encoding="utf-8") for n in reads)
    for write in ("save", "delete", "create_appointment", "cancel_appointment", "change_appointment"):
        assert f"repo.{write}" not in source, write


def test_time_off_kind_and_a_year_of_absences(api):
    _, ana = set_up(api)
    status, body = call(api, "POST", "/time-off", {"professional_id": ana["id"], "first_day": "2027-07-01",
                                                   "last_day": "2027-07-20", "kind": "vacation"})
    assert status == 201 and body["time_off"]["kind"] == "vacation"
    status, found = call(api, "GET", "/time-off", query={"from": "2026-11-17", "to": "2027-11-17"})   # the next year
    assert status == 200 and [t["kind"] for t in found] == ["vacation"]
    assert call(api, "GET", "/time-off", query={"from": "2026-11-17", "to": "2027-11-18"})[0] == 400
    assert call(api, "GET", "/appointments", query={"from": "2026-11-17", "to": "2027-11-17"})[0] == 400   # still 62


def test_every_call_of_the_frontend_has_a_lambda_and_every_lambda_is_used():
    """The contract between the two sides: each api("METHOD", "/path") in frontend/js matches a route
    in some lambda.json (what Terraform deploys), and no Lambda is left that nobody calls."""
    import re
    routes = {json.loads((ROOT / "backend" / "lambdas" / name / "lambda.json").read_text())["route"]
              for _, _, name, _ in ROUTES}
    calls = set()
    for file in (ROOT / "frontend" / "js").rglob("*.js"):
        for method, path in re.findall(r'api\("([A-Z]+)", [`"]([^`"]+)[`"]', file.read_text(encoding="utf-8")):
            # catalog.js serves both lists with `/${route}`; any other ${...} is an id
            for kind in (("services", "professionals") if "${route}" in path else (None,)):
                concrete = path.replace("${route}", kind or "")
                calls.add(f"{method} {re.sub(r'\$\{[^}]+\}', '{id}', concrete)}")
    assert calls - routes == set(), "the frontend calls routes no Lambda answers"
    assert routes - calls == set(), "Lambdas nobody calls"
