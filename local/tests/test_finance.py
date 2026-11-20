"""The manager records what already happened, client payments, and the month's money (Financeiro).
Through the API, since the role comes from the login token. "Now" is Monday 2026-11-16, 10:00."""
from dataclasses import replace

import pytest

from agenda_core.domain.errors import SlotConflict
from test_http import api, call, set_up  # noqa: F401  (api is the fixture)
from test_repositories import appt

EMPLOYEE = dict(groups="[employee]")


def booking(service, professional, start, date="2026-11-16", client="Maria"):
    return {"date": date, "start": start, "service_id": service["id"], "professional_id": professional["id"],
            "client_name": client, "client_phone": "11900000001" if client == "Maria" else "11900000002"}


def test_the_manager_records_what_already_happened(api):
    haircut, ana = set_up(api)
    query = {"date": "2026-11-16", "service_id": haircut["id"], "professional_id": ana["id"]}
    assert call(api, "GET", "/availability", query=query)[1][0] == "10:15"          # normally: only ahead
    assert call(api, "GET", "/availability", query={**query, "include_past": "true"})[1][0] == "09:00"   # recording
    _, past = call(api, "POST", "/appointments", booking(haircut, ana, "09:00"))
    assert past["start"] == "09:00"
    _, bia = call(api, "POST", "/professionals", {"name": "Bia", "services": [haircut["id"]]})
    assert call(api, "PUT", f"/appointments/{past['id']}/professional", {"professional_id": bia["id"]})[0] == 200
    assert call(api, "DELETE", f"/appointments/{past['id']}")[0] == 204


def test_marking_paid(api):
    haircut, ana = set_up(api)
    _, a = call(api, "POST", "/appointments", booking(haircut, ana, "11:00"))
    assert a["paid"] is False
    path = f"/appointments/{a['id']}/payment"
    assert call(api, "PUT", path, {"paid": True}, **EMPLOYEE)[0] == 403
    assert call(api, "PUT", path, {"paid": "yes"})[0] == 400
    status, paid = call(api, "PUT", path, {"paid": True})
    assert status == 200 and paid["paid"] is True
    assert call(api, "GET", "/appointments", query={"date": "2026-11-16"})[1][0]["paid"] is True
    assert call(api, "PUT", path, {"paid": False})[1]["paid"] is False                      # undone
    assert call(api, "PUT", "/appointments/2026-11-16_1100_ffffffff/payment", {"paid": True})[0] == 404


def test_finance_of_the_month(api):
    haircut, ana = set_up(api)                                                  # haircut: R$ 80,00
    _, nails = call(api, "POST", "/services", {"name": "Nails", "duration_min": 30, "price_cents": 4000})
    _, bia = call(api, "POST", "/professionals", {"name": "Bia", "services": [nails["id"]]})
    _, a1 = call(api, "POST", "/appointments", booking(haircut, ana, "09:00"))           # passed, will be paid
    _, a2 = call(api, "POST", "/appointments", booking(nails, bia, "09:00", client="Joana"))   # passed, not paid
    call(api, "POST", "/appointments", booking(haircut, ana, "14:00", "2026-11-20"))      # ahead
    call(api, "POST", "/appointments", booking(haircut, ana, "10:00", "2026-12-01"))      # next month: not counted
    call(api, "PUT", f"/appointments/{a1['id']}/payment", {"paid": True})

    assert call(api, "GET", "/finance", query={"month": "2026-11"}, **EMPLOYEE)[0] == 403
    assert call(api, "GET", "/finance", query={"month": "2026-13"})[0] == 400
    status, month = call(api, "GET", "/finance", query={"month": "2026-11"})
    assert status == 200
    assert month["totals"] == {"count": 3, "expected": 20000, "paid": 8000, "pending": 12000, "commission": 0}
    assert [(r["name"], r["count"], r["expected"], r["paid"], r["pending"]) for r in month["by_professional"]] == [
        ("Ana", 2, 16000, 8000, 8000), ("Bia", 1, 4000, 0, 4000)]
    assert [(r["name"], r["expected"]) for r in month["by_service"]] == [("Haircut", 16000), ("Nails", 4000)]
    assert [a["client_name"] for a in month["overdue"]] == ["Joana"]           # happened, still not paid
    assert call(api, "GET", "/finance", query={"month": "2026-10"})[1]["totals"]["count"] == 0


def test_update_appointment_refuses_a_stale_copy(repo):
    original = appt("2026-11-17_1000_aaaaaaaa")
    repo.create_appointment("o", original)
    repo.update_appointment("o", original, replace(original, paid=True))
    assert repo.get_appointment("o", original.id).paid is True
    with pytest.raises(SlotConflict):                       # someone changed it after `original` was read
        repo.update_appointment("o", original, replace(original, client_name="Other"))


def test_commission_per_service_percent_or_fixed(api):
    haircut, ana = set_up(api)                                                  # haircut: R$ 80,00
    _, nails = call(api, "POST", "/services", {"name": "Nails", "duration_min": 30, "price_cents": 4000})
    rules = {haircut["id"]: {"kind": "percent", "value": 40}, nails["id"]: {"kind": "fixed", "value": 1500}}
    status, ana = call(api, "PUT", f"/professionals/{ana['id']}",
                       {"name": "Ana", "services": [haircut["id"], nails["id"]], "commissions": rules})
    assert status == 200 and ana["commissions"] == rules
    _, cut = call(api, "POST", "/appointments", booking(haircut, ana, "11:00"))
    _, mani = call(api, "POST", "/appointments", booking(nails, ana, "13:00"))
    assert (cut["commission_cents"], mani["commission_cents"]) == (3200, 1500)       # 40% of 80,00; 15,00 fixed

    # changing the rule later does not change what was booked (like the price)
    call(api, "PUT", f"/professionals/{ana['id']}", {"name": "Ana", "services": [haircut["id"], nails["id"]],
                                                     "commissions": {haircut["id"]: {"kind": "percent", "value": 10}}})
    totals = call(api, "GET", "/finance", query={"month": "2026-11"})[1]["by_professional"][0]
    assert totals["commission"] == 4700

    # given to another professional: hers now, at her commission
    _, bia = call(api, "POST", "/professionals", {"name": "Bia", "services": [haircut["id"]],
                                                  "commissions": {haircut["id"]: {"kind": "fixed", "value": 2500}}})
    _, moved = call(api, "PUT", f"/appointments/{cut['id']}/professional", {"professional_id": bia["id"]})
    assert moved["commission_cents"] == 2500


@pytest.mark.parametrize("commissions", [
    {"deadbeef": {"kind": "percent", "value": 10}},                     # a service she does not perform
    {"SERVICE": {"kind": "percent", "value": 101}}, {"SERVICE": {"kind": "percent", "value": -1}},
    {"SERVICE": {"kind": "bonus", "value": 10}}, {"SERVICE": {"kind": "fixed", "value": "10"}},
    {"SERVICE": {"kind": "fixed", "value": True}}, ["SERVICE"],
])
def test_invalid_commission(api, commissions):
    haircut, ana = set_up(api)
    if isinstance(commissions, dict):
        commissions = {(haircut["id"] if k == "SERVICE" else k): v for k, v in commissions.items()}
    status, _ = call(api, "PUT", f"/professionals/{ana['id']}",
                     {"name": "Ana", "services": [haircut["id"]], "commissions": commissions})
    assert status == 400


def test_deleting_a_service_drops_its_commission(api):
    haircut, ana = set_up(api)
    _, nails = call(api, "POST", "/services", {"name": "Nails", "duration_min": 30, "price_cents": 4000})
    rules = {haircut["id"]: {"kind": "percent", "value": 40}, nails["id"]: {"kind": "fixed", "value": 1500}}
    call(api, "PUT", f"/professionals/{ana['id']}", {"name": "Ana", "services": [haircut["id"], nails["id"]], "commissions": rules})
    call(api, "DELETE", f"/services/{nails['id']}")
    [ana] = call(api, "GET", "/professionals")[1]
    assert ana["services"] == [haircut["id"]] and list(ana["commissions"]) == [haircut["id"]]
