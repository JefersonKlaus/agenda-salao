"""The local server's demo data (local/seed.py) must be valid on any day the developer runs it."""
from datetime import date, datetime, timedelta

import pytest

from agenda_core.domain.models import parse_date
from agenda_core.domain.scheduling import fits_business_hours
from agenda_core.ports import Dependencies
from memory_identity import MemoryIdentity
from memory_repository import MemoryRepository
from seed import seed

OWNER = "local-salon"


@pytest.mark.parametrize("offset", range(7))          # every weekday as "today"
def test_demo_data_is_valid_whatever_the_day(offset):
    today = date(2026, 11, 16) + timedelta(days=offset)
    repo = MemoryRepository()
    seed(Dependencies(repo, lambda: datetime.combine(today, datetime.min.time()), MemoryIdentity()), OWNER, today)

    settings = repo.get_settings(OWNER)
    professionals = {p.id: p for p in repo.list_items(OWNER, "professional")}
    assert len(repo.list_items(OWNER, "service")) == 18 and len(professionals) == 22      # more than a page each
    appointments = repo.appointments_between(OWNER, (today - timedelta(days=7)).isoformat(),
                                             (today + timedelta(days=14)).isoformat())
    assert len(appointments) > 100                                         # a busy agenda
    assert any(a.date == today.isoformat() for a in appointments) or today.weekday() == 6   # closed on Sunday
    for a in appointments:                                                 # every one bookable for real
        assert fits_business_hours(settings, parse_date(a.date), a.start_min, a.duration_min,
                                   professionals[a.professional_id]), a
    kinds = {t.kind for t in repo.time_off_between(OWNER, today.isoformat(), (today + timedelta(days=20)).isoformat())}
    assert kinds == {"vacation", "day_off", "other"}
    # logins: Ana, Bia and part of the team (linked to their professionals), and the receptionist (no professional)
    accesses = {a.name: a for a in repo.list_accesses(OWNER)}
    assert len(accesses) == 12 and {"Ana", "Bia", "Recepção", "João Pedro Alves"} <= set(accesses)
    assert accesses["Recepção"].professional_id is None and accesses["João Pedro Alves"].email == "joao@salao.local"
    assert len({a.email for a in accesses.values()}) == 12                  # no e-mail twice
    assert {p.name: p.login for p in professionals.values()}["Ana"] == "ana@salao.local"


def test_same_agenda_every_time():
    today = date(2026, 11, 18)
    agendas = []
    for _ in range(2):
        repo = MemoryRepository()
        seed(Dependencies(repo, lambda: datetime(2026, 11, 18, 10), MemoryIdentity()), OWNER, today)
        agendas.append([(a.date, a.start, a.professional_name, a.client_name)
                        for a in repo.appointments_between(OWNER, "2026-11-11", "2026-12-02")])
    assert agendas[0] == agendas[1]
