"""Clients: the phone is the key; booking registers her; her page has the appointments, what she paid
and what is open, which can be paid right there. "Now" is Monday 2026-11-16, 10:00."""
from dataclasses import replace

import pytest

from agenda_core.domain.models import Client
from test_http import api, call, set_up  # noqa: F401  (api is the fixture)
from test_repositories import appt

MARIA = "11988887777"


def booking(service, professional, start, date="2026-11-17", name="Maria", phone="(11) 98888-7777"):
    return {"date": date, "start": start, "service_id": service["id"], "professional_id": professional["id"],
            "client_name": name, "client_phone": phone}


def test_booking_registers_the_client_by_phone(api):
    haircut, ana = set_up(api)
    assert call(api, "POST", "/appointments", booking(haircut, ana, "10:00"))[0] == 201
    assert call(api, "GET", "/clients")[1] == [{"phone": MARIA, "name": "Maria"}]
    # the same phone, written another way and with the full name: the same client, name updated
    call(api, "POST", "/appointments", booking(haircut, ana, "14:00", name="Maria Souza", phone="11 98888 7777"))
    assert call(api, "GET", "/clients")[1] == [{"phone": MARIA, "name": "Maria Souza"}]
    assert call(api, "POST", "/appointments", booking(haircut, ana, "16:00", phone=""))[0] == 400   # required


def test_her_history_what_she_paid_and_what_is_open(api):
    haircut, ana = set_up(api)                                               # haircut: R$ 80,00
    _, paid = call(api, "POST", "/appointments", booking(haircut, ana, "09:00", "2026-11-13"))     # last Friday
    _, owed = call(api, "POST", "/appointments", booking(haircut, ana, "11:00", "2026-11-14"))     # last Saturday
    _, ahead = call(api, "POST", "/appointments", booking(haircut, ana, "10:00", "2026-11-18"))
    call(api, "POST", "/appointments", booking(haircut, ana, "12:00", "2026-11-18", name="Joana", phone="11977776666"))
    call(api, "PUT", f"/appointments/{paid['id']}/payment", {"paid": True})

    status, page = call(api, "GET", f"/clients/{MARIA}")
    assert status == 200 and page["client"] == {"phone": MARIA, "name": "Maria"}
    assert [a["id"] for a in page["appointments"]] == [ahead["id"], owed["id"], paid["id"]]   # newest first, only hers
    assert page["totals"] == {"visits": 2, "paid": 8000, "open": 8000, "upcoming": 8000}
    assert [a["id"] for a in page["open"]] == [owed["id"]]                   # happened, not paid: to charge

    call(api, "PUT", f"/appointments/{owed['id']}/payment", {"paid": True})  # paid right there
    page = call(api, "GET", f"/clients/{MARIA}")[1]
    assert page["open"] == [] and page["totals"]["open"] == 0 and page["totals"]["paid"] == 16000

    call(api, "DELETE", f"/appointments/{ahead['id']}")                      # cancelled: gone from her history
    assert len(call(api, "GET", f"/clients/{MARIA}")[1]["appointments"]) == 2


def test_register_and_rename_a_client(api):
    status, client = call(api, "POST", "/clients", {"name": "Ana Paula", "phone": "(11) 3333-4444"})
    assert status == 201 and client == {"phone": "1133334444", "name": "Ana Paula"}
    status, error = call(api, "POST", "/clients", {"name": "Outra", "phone": "1133334444"})
    assert status == 400 and "Ana Paula" in error["error"]                  # the phone is taken: says by whom
    assert call(api, "PUT", "/clients/1133334444", {"name": "Ana Paula Lima"})[1]["name"] == "Ana Paula Lima"
    assert call(api, "PUT", "/clients/1199999999", {"name": "X"})[0] == 404
    for bad in ({"name": "X", "phone": "123"}, {"name": "", "phone": "1133335555"}, {"phone": "1133335555"}):
        assert call(api, "POST", "/clients", bad)[0] == 400


@pytest.mark.parametrize("method, path", [("GET", "/clients/123"), ("GET", "/clients/abc"), ("GET", f"/clients/{MARIA}")])
def test_unknown_or_malformed_phone_is_404(api, method, path):
    assert call(api, method, path)[0] == 404


def test_clients_are_the_managers(api):
    call(api, "POST", "/clients", {"name": "Ana Paula", "phone": "1133334444"})
    for method, path, body in [("GET", "/clients", None), ("GET", "/clients/1133334444", None),
                               ("POST", "/clients", {"name": "X", "phone": "1133335555"}),
                               ("PUT", "/clients/1133334444", {"name": "X"})]:
        assert call(api, method, path, body, groups="[employee]")[0] == 403, (method, path)


def test_each_salon_has_its_own_clients(api):
    haircut, ana = set_up(api)
    call(api, "POST", "/appointments", booking(haircut, ana, "10:00"))
    assert call(api, "GET", "/clients", owner="owner-b")[1] == []
    assert call(api, "GET", f"/clients/{MARIA}", owner="owner-b")[0] == 404


def test_client_appointments_follow_every_change(repo):
    """Both repositories (DynamoDB through its index): booking, payment, another professional and
    cancelling all show in the client's history; another client's and another salon's never do."""
    repo.save_client("o", Client(MARIA, "Maria"))
    first = replace(appt("2026-11-17_1000_aaaaaaaa"), client_phone=MARIA)
    second = replace(appt("2026-11-20_1500_bbbbbbbb", "15:00"), client_phone=MARIA)
    other = replace(appt("2026-11-17_1100_cccccccc", "11:00"), client_phone="11977776666")
    for a in (first, second, other):
        repo.create_appointment("o", a)
    repo.create_appointment("x", replace(appt("2026-11-17_1000_dddddddd"), client_phone=MARIA))   # another salon
    assert sorted(a.id for a in repo.client_appointments("o", MARIA)) == [first.id, second.id]
    repo.update_appointment("o", first, replace(first, paid=True))
    repo.change_appointment_professional("o", second, replace(second, professional_id="p2", professional_name="Bia"))
    found = {a.id: a for a in repo.client_appointments("o", MARIA)}
    assert found[first.id].paid and found[second.id].professional_name == "Bia"
    repo.cancel_appointment("o", first.id)
    assert [a.id for a in repo.client_appointments("o", MARIA)] == [second.id]
    assert repo.get_client("o", MARIA) == Client(MARIA, "Maria") and repo.list_clients("o") == [Client(MARIA, "Maria")]
