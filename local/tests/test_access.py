"""Logins created in the app (Acessos), and what an employee may do with absences: only her own.
Through the API, since the salon, the role and the professional come from the login token."""
import pytest

from test_http import api, call, set_up  # noqa: F401  (api is the fixture)

MANAGER = "owner-a"


def as_login(access, salon=MANAGER):
    """The token of a login created in the app: Cognito writes the salon and the professional in it."""
    claims = {"custom:salon": salon}
    if access.get("professional_id"):
        claims["custom:professional_id"] = access["professional_id"]
    return dict(owner=access["id"], groups="[manager]" if access["manager"] else "[employee]", claims=claims)


def test_a_service_provider_access_starts_her_professional(api):
    status, access = call(api, "POST", "/access", {"email": "Ana@Salao.com", "name": "Ana", "provider": True})
    assert status == 201 and access["email"] == "ana@salao.com" and access["manager"] is False
    [ana] = call(api, "GET", "/professionals")[1]
    assert ana["id"] == access["professional_id"] and ana["login"] == "ana@salao.com"
    assert ana["services"] == [] and ana["work_hours"] == []            # services and days: configured later
    assert [a["name"] for a in call(api, "GET", "/access")[1]] == ["Ana"]
    assert call(api, "POST", "/access", {"email": "ana@salao.com", "name": "Outra"})[0] == 400   # e-mail taken


def test_an_access_for_a_professional_who_had_none(api):
    _, ana = set_up(api)
    status, access = call(api, "POST", "/access", {"email": "ana@salao.com", "professional_id": ana["id"]})
    assert status == 201 and access["professional_id"] == ana["id"] and access["name"] == "Ana"
    assert call(api, "GET", "/professionals")[1][0]["login"] == "ana@salao.com"
    status, error = call(api, "POST", "/access", {"email": "outra@salao.com", "professional_id": ana["id"]})
    assert status == 400 and "já tem acesso" in error["error"]
    # editing her (services, hours) keeps the access hers
    call(api, "PUT", f"/professionals/{ana['id']}", {"name": "Ana", "services": ana["services"]})
    assert call(api, "GET", "/professionals")[1][0]["login"] == "ana@salao.com"


@pytest.mark.parametrize("body", [{"email": "nope", "name": "X"}, {"email": "a@b.com"},
                                  {"email": "a@b.com", "name": "X", "manager": "yes"},
                                  {"email": "a@b.com", "professional_id": "deadbeef"}])
def test_invalid_access(api, body):
    assert call(api, "POST", "/access", body)[0] in (400, 404)


def test_an_employee_login_works_in_the_managers_salon(api):
    _, ana = set_up(api)                                                  # the salon of owner-a
    _, access = call(api, "POST", "/access", {"email": "ana@salao.com", "professional_id": ana["id"]})
    login = as_login(access)
    assert call(api, "GET", "/professionals", **login)[1][0]["name"] == "Ana"     # same salon, not an empty one
    assert call(api, "GET", "/me", **login)[1] == {"manager": False, "professional_id": ana["id"]}
    assert call(api, "GET", "/me")[1] == {"manager": True, "professional_id": None}  # the salon's own account
    assert call(api, "POST", "/services", {"name": "X", "duration_min": 30, "price_cents": 1}, **login)[0] == 403


def test_a_login_created_in_the_app_is_the_manager_only_in_that_group(api):
    _, access = call(api, "POST", "/access", {"email": "socia@salao.com", "name": "Sócia", "manager": True})
    assert call(api, "GET", "/me", **as_login(access))[1]["manager"] is True
    no_group = dict(owner="someone", claims={"custom:salon": MANAGER})            # in no group: not the manager
    assert call(api, "GET", "/me", **no_group)[1]["manager"] is False


def test_an_employee_registers_and_removes_only_her_own_absences(api):
    haircut, ana = set_up(api)
    _, bia = call(api, "POST", "/professionals", {"name": "Bia", "services": [haircut["id"]]})
    _, access = call(api, "POST", "/access", {"email": "ana@salao.com", "professional_id": ana["id"]})
    login = as_login(access)
    mine = {"professional_id": ana["id"], "first_day": "2026-11-20", "kind": "sick"}
    status, body = call(api, "POST", "/time-off", mine, **login)
    assert status == 201
    status, error = call(api, "POST", "/time-off", {**mine, "professional_id": bia["id"]}, **login)
    assert status == 403 and "suas próprias" in error["error"]
    _, bias = call(api, "POST", "/time-off", {**mine, "professional_id": bia["id"]})   # the manager: anyone's
    assert call(api, "DELETE", f"/time-off/{bias['time_off']['id']}", **login)[0] == 403
    assert call(api, "DELETE", f"/time-off/{body['time_off']['id']}", **login)[0] == 204
    assert call(api, "DELETE", f"/time-off/{bias['time_off']['id']}")[0] == 204


def test_an_employee_who_does_not_attend_clients_has_no_absences(api):
    _, ana = set_up(api)
    _, access = call(api, "POST", "/access", {"email": "recepcao@salao.com", "name": "Recepção"})
    assert access["professional_id"] is None
    status, _ = call(api, "POST", "/time-off", {"professional_id": ana["id"], "first_day": "2026-11-20"},
                     **as_login(access))
    assert status == 403


def test_removing_an_access(api):
    _, ana = set_up(api)
    _, access = call(api, "POST", "/access", {"email": "ana@salao.com", "professional_id": ana["id"]})
    assert call(api, "DELETE", f"/access/{access['id']}", **as_login(access))[0] == 403   # not by an employee
    assert call(api, "DELETE", f"/access/{access['id']}") == (204, None)
    assert call(api, "GET", "/access")[1] == []
    assert call(api, "GET", "/professionals")[1][0]["login"] is None           # she stays, with no access
    assert call(api, "DELETE", f"/access/{access['id']}")[0] == 404
    assert call(api, "DELETE", "/access/not-a-login-id")[0] == 404
    # the e-mail is free again: a new login can be created with it
    assert call(api, "POST", "/access", {"email": "ana@salao.com", "professional_id": ana["id"]})[0] == 201


def test_deleting_a_professional_removes_her_login(api):
    _, ana = set_up(api)
    call(api, "POST", "/access", {"email": "ana@salao.com", "professional_id": ana["id"]})
    call(api, "POST", "/access", {"email": "recepcao@salao.com", "name": "Recepção"})
    assert call(api, "DELETE", f"/professionals/{ana['id']}") == (204, None)
    assert [a["name"] for a in call(api, "GET", "/access")[1]] == ["Recepção"]
    assert call(api, "POST", "/access", {"email": "ana@salao.com", "name": "Ana"})[0] == 201      # the login is gone
