import base64
import json

import pytest

from agenda.agenda import Agenda
from agenda.http import MAX_BODY, handle
from agenda.memory_repository import MemoryRepository
from conftest import NOW


def call(agenda, method, path, body=None, query=None, owner="owner-a", base64_=False):
    event = {"rawPath": path, "requestContext": {"http": {"method": method}},
             "queryStringParameters": query}
    if owner:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": owner}}}
    if body is not None:
        text = body if isinstance(body, str) else json.dumps(body)
        event["body"] = base64.b64encode(text.encode()).decode() if base64_ else text
        event["isBase64Encoded"] = base64_
    response = handle(event, agenda)
    return response["statusCode"], json.loads(response["body"]) if response["body"] else None


@pytest.fixture
def api():
    return Agenda(MemoryRepository(), lambda: NOW)


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
    assert call(api, "PUT", "/settings", {"open_days": [1], "opens": "08:00", "closes": "12:00"})[0] == 200
    assert call(api, "GET", "/settings")[1]["opens"] == "08:00"


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
    ("GET", "/nothing", 404), ("PATCH", "/services", 405), ("GET", "/services/xyz", 404),
    ("GET", "/services/", 200), ("DELETE", "/services/ZZZZZZZZ", 404),
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
    status, body = call(Agenda(Broken(), lambda: NOW), "GET", "/services")
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
