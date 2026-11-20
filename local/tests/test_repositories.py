"""Repository contract, without going through the Agenda checks: here only the lock counts."""
import json
from dataclasses import replace

import pytest

from agenda_core.domain.models import Appointment, Professional, Service, Settings, Shift, TimeOff
from agenda_core.adapters.dynamo_repository import DynamoRepository
from agenda_core.domain.errors import SlotConflict
from conftest import OTHER, OWNER, FakeClientError, FakeDynamo


def appt(id, start="10:00", duration=60, prof="p1", date="2026-11-17"):
    return Appointment(id, date, start, duration, prof, "Ana", "s1", "Haircut", 100, "Maria", "")


def test_lock_prevents_overlap_even_without_prior_check(repo):
    repo.create_appointment(OWNER, appt("2026-11-17_1000_aaaaaaaa"))
    for start, duration in (("10:00", 60), ("10:30", 30), ("09:30", 45), ("10:45", 15)):
        with pytest.raises(SlotConflict):
            repo.create_appointment(OWNER, appt("2026-11-17_9999_bbbbbbbb", start, duration))
    assert len(repo.appointments_on_day(OWNER, "2026-11-17")) == 1


def test_conflict_does_not_leave_partial_locks(repo):
    repo.create_appointment(OWNER, appt("2026-11-17_1000_aaaaaaaa", "10:00", 60))
    with pytest.raises(SlotConflict):
        repo.create_appointment(OWNER, appt("2026-11-17_0930_bbbbbbbb", "09:30", 60))   # clashes at 10:00
    repo.create_appointment(OWNER, appt("2026-11-17_0900_cccccccc", "09:00", 60))       # 09:30 was not left locked


def test_touching_is_not_a_conflict_and_other_owner_or_professional_does_not_interfere(repo):
    repo.create_appointment(OWNER, appt("2026-11-17_1000_aaaaaaaa"))
    repo.create_appointment(OWNER, appt("2026-11-17_1100_bbbbbbbb", "11:00"))
    repo.create_appointment(OWNER, appt("2026-11-17_1000_cccccccc", prof="p2"))
    repo.create_appointment(OTHER, appt("2026-11-17_1000_dddddddd"))
    repo.create_appointment(OWNER, appt("2026-11-18_1000_eeeeeeee", date="2026-11-18"))
    assert len(repo.appointments_on_day(OWNER, "2026-11-17")) == 3


def test_cancel_frees_the_locks_and_does_not_cancel_twice(repo):
    repo.create_appointment(OWNER, appt("2026-11-17_1000_aaaaaaaa"))
    assert repo.cancel_appointment(OWNER, "2026-11-17_1000_aaaaaaaa").id == "2026-11-17_1000_aaaaaaaa"
    assert repo.cancel_appointment(OWNER, "2026-11-17_1000_aaaaaaaa") is None
    repo.create_appointment(OWNER, appt("2026-11-17_1000_bbbbbbbb"))


def test_save_get_list_delete(repo):
    service = Service("aaaaaaaa", "Haircut", 60, 8000)
    prof = Professional("bbbbbbbb", "Ana", ("aaaaaaaa",))
    repo.save(OWNER, "service", service)
    repo.save(OWNER, "professional", prof)
    assert repo.get(OWNER, "service", "aaaaaaaa") == service
    assert repo.list_items(OWNER, "professional") == [prof]
    assert repo.list_items(OTHER, "service") == [] and repo.get(OTHER, "service", "aaaaaaaa") is None
    repo.delete(OWNER, "service", "aaaaaaaa")
    repo.delete(OWNER, "service", "aaaaaaaa")                       # deleting again does not break
    assert repo.list_items(OWNER, "service") == [] and len(repo.list_items(OWNER, "professional")) == 1


def test_professional_work_hours_are_saved(repo):
    prof = Professional("bbbbbbbb", "Ana", (), (Shift(1, "10:00", "14:00"), Shift(5, "08:00", "12:00")))
    repo.save(OWNER, "professional", prof)
    assert repo.get(OWNER, "professional", "bbbbbbbb") == prof


def test_appointments_between_is_inclusive_and_only_returns_appointments(repo):
    for id, date in (("2026-11-15_1000_aaaaaaaa", "2026-11-15"), ("2026-11-16_0900_bbbbbbbb", "2026-11-16"),
                     ("2026-11-22_1800_cccccccc", "2026-11-22"), ("2026-11-23_0900_dddddddd", "2026-11-23")):
        repo.create_appointment(OWNER, appt(id, date=date))
    repo.create_appointment(OTHER, appt("2026-11-17_1000_eeeeeeee"))
    repo.save(OWNER, "service", Service("aaaaaaaa", "Haircut", 60, 8000))          # other kinds of items
    repo.save_settings(OWNER, Settings())
    found = sorted(a.id for a in repo.appointments_between(OWNER, "2026-11-16", "2026-11-22"))
    assert found == ["2026-11-16_0900_bbbbbbbb", "2026-11-22_1800_cccccccc"]
    assert [a.id for a in repo.appointments_between(OWNER, "2026-11-15", "2026-11-15")] == ["2026-11-15_1000_aaaaaaaa"]


def test_settings_empty_then_saved(repo):
    assert repo.get_settings(OWNER) is None
    settings = Settings((Shift(1, "08:00", "12:00"), Shift(2, "13:00", "18:00")))
    repo.save_settings(OWNER, settings)
    assert repo.get_settings(OWNER) == settings and repo.get_settings(OTHER) is None


# ---------------------------------------------------------------- DynamoDB only

def test_list_joins_all_pages():
    repo = DynamoRepository(FakeDynamo(page_size=2), "t")
    for i in range(7):
        repo.save(OWNER, "service", Service(f"{i:08x}", f"S{i}", 30, 100))
    assert len(repo.list_items(OWNER, "service")) == 7


def test_day_prefix_does_not_match_another_day():
    repo = DynamoRepository(FakeDynamo(), "t")
    repo.create_appointment(OWNER, appt("2026-11-17_1000_aaaaaaaa"))
    repo.create_appointment(OWNER, appt("2026-11-18_1000_bbbbbbbb", date="2026-11-18"))
    assert [a.id for a in repo.appointments_on_day(OWNER, "2026-11-18")] == ["2026-11-18_1000_bbbbbbbb"]


def test_transaction_has_one_conditional_put_per_block():
    db = FakeDynamo()
    DynamoRepository(db, "t").create_appointment(OWNER, appt("2026-11-17_1000_aaaaaaaa", duration=60))
    operations = db.calls[0]
    assert len(operations) == 1 + 4                                  # the appointment + 4 blocks of 15 min
    assert all(op["Put"]["ConditionExpression"] == "attribute_not_exists(PK)" for op in operations)
    assert all(op["Put"]["Item"]["PK"] == {"S": f"SALAO#{OWNER}"} for op in operations)


def test_only_a_failed_condition_becomes_a_conflict():
    class Db(FakeDynamo):
        def __init__(self, error):
            super().__init__()
            self.error = error

        def transact_write_items(self, TransactItems):
            raise self.error

    for error in (FakeClientError("TransactionCanceledException", ["None", "TransactionConflict"]),
                  FakeClientError("ProvisionedThroughputExceededException"), RuntimeError("boom")):
        with pytest.raises(type(error)):
            DynamoRepository(Db(error), "t").create_appointment(OWNER, appt("2026-11-17_1000_aaaaaaaa"))
    conflict = FakeClientError("TransactionCanceledException", ["None", "ConditionalCheckFailed"])
    with pytest.raises(SlotConflict):
        DynamoRepository(Db(conflict), "t").create_appointment(OWNER, appt("2026-11-17_1000_aaaaaaaa"))


# The table already holds data written in this format (keys and field names in Portuguese).
# Changing it would make existing items unreadable: these two tests pin it down.
LEGACY_ITEMS = {
    "SERV#aaaaaaaa": {"id": "aaaaaaaa", "nome": "Haircut", "duracao_min": 60, "preco_centavos": 8000},
    "PROF#bbbbbbbb": {"id": "bbbbbbbb", "nome": "Ana", "servicos": ["aaaaaaaa"]},
    "CONF": {"dias_abertos": [1, 2], "abre": "08:00", "fecha": "12:00"},
    "AGE#2026-11-17_1000_cccccccc": {
        "id": "2026-11-17_1000_cccccccc", "data": "2026-11-17", "inicio": "10:00", "duracao_min": 30,
        "profissional_id": "bbbbbbbb", "profissional_nome": "Ana", "servico_id": "aaaaaaaa",
        "servico_nome": "Haircut", "preco_centavos": 8000, "cliente_nome": "Maria", "cliente_telefone": ""},
    "TRAVA#bbbbbbbb#2026-11-17#1000": {"ag": "2026-11-17_1000_cccccccc"},
    "TRAVA#bbbbbbbb#2026-11-17#1015": {"ag": "2026-11-17_1000_cccccccc"},
}


def _stored(db):
    return {sk: json.loads(item["dados"]["S"]) for (pk, sk), item in db.items.items()
            if pk == f"SALAO#{OWNER}"}


def test_writes_the_existing_storage_format():
    db = FakeDynamo()
    repo = DynamoRepository(db, "t")
    repo.save(OWNER, "service", Service("aaaaaaaa", "Haircut", 60, 8000))
    repo.save(OWNER, "professional", Professional("bbbbbbbb", "Ana", ("aaaaaaaa",)))
    repo.save_settings(OWNER, Settings((Shift(1, "08:00", "12:00"), Shift(2, "08:00", "12:00"))))
    repo.create_appointment(OWNER, Appointment("2026-11-17_1000_cccccccc", "2026-11-17", "10:00", 30,
                                               "bbbbbbbb", "Ana", "aaaaaaaa", "Haircut", 8000, "Maria", ""))
    # the only changes since then are new fields, which older code simply ignores
    # per-day hours are a new field; the old ones stay, so older code can still read the item
    hours = [{"day": d, "start": "08:00", "end": "12:00"} for d in (1, 2)]
    assert _stored(db) == {**LEGACY_ITEMS, "PROF#bbbbbbbb": {**LEGACY_ITEMS["PROF#bbbbbbbb"], "work_hours": None, "login": None,
                                            "commissions": {}},
                           "SERV#aaaaaaaa": {**LEGACY_ITEMS["SERV#aaaaaaaa"], "active": True},
                           "CONF": {**LEGACY_ITEMS["CONF"], "hours": hours},
                           "AGE#2026-11-17_1000_cccccccc": {**LEGACY_ITEMS["AGE#2026-11-17_1000_cccccccc"], "paid": False,
                                                            "commission_cents": 0}}


def test_reads_items_already_in_the_table():
    db = FakeDynamo()
    for sk, data in LEGACY_ITEMS.items():
        db.put_item("t", {"PK": {"S": f"SALAO#{OWNER}"}, "SK": {"S": sk},
                          "dados": {"S": json.dumps(data, ensure_ascii=False)}})
    repo = DynamoRepository(db, "t")
    assert repo.get(OWNER, "service", "aaaaaaaa") == Service("aaaaaaaa", "Haircut", 60, 8000)
    assert repo.list_items(OWNER, "professional") == [Professional("bbbbbbbb", "Ana", ("aaaaaaaa",))]
    assert repo.list_items(OWNER, "professional")[0].work_hours is None          # = follows the salon
    assert repo.get_settings(OWNER) == Settings((Shift(1, "08:00", "12:00"), Shift(2, "08:00", "12:00")))
    [existing] = repo.appointments_on_day(OWNER, "2026-11-17")
    assert (existing.client_name, existing.start, existing.service_name) == ("Maria", "10:00", "Haircut")
    with pytest.raises(SlotConflict):                               # its locks still hold the slot
        repo.create_appointment(OWNER, appt("2026-11-17_1015_dddddddd", "10:15", 15, prof="bbbbbbbb"))
    assert repo.cancel_appointment(OWNER, existing.id) == existing
    assert set(_stored(db)) == {"SERV#aaaaaaaa", "PROF#bbbbbbbb", "CONF"}      # locks released too


# ---------------------------------------------------------------- absences and changing the professional

def off(id, first, last, prof="p1", start=None, end=None):
    return TimeOff(f"{first}_{id}", prof, first, last, start, end, "")


def test_time_off_between_finds_absences_that_started_long_before(repo):
    long_leave = off("aaaaaaaa", "2026-08-01", "2026-12-31")                        # started months earlier
    repo.save_time_off(OWNER, long_leave)
    repo.save_time_off(OWNER, off("bbbbbbbb", "2026-11-10", "2026-11-15"))           # ended before
    repo.save_time_off(OWNER, off("cccccccc", "2026-11-23", "2026-11-23"))           # starts after
    repo.save_time_off(OWNER, off("dddddddd", "2026-11-22", "2026-11-22", start="09:00", end="10:00"))
    repo.save_time_off(OTHER, off("eeeeeeee", "2026-11-17", "2026-11-17"))
    repo.create_appointment(OWNER, appt("2026-11-17_1000_ffffffff"))                 # other items around
    found = sorted(t.id for t in repo.time_off_between(OWNER, "2026-11-16", "2026-11-22"))
    assert found == ["2026-08-01_aaaaaaaa", "2026-11-22_dddddddd"]
    assert repo.delete_time_off(OWNER, "2026-11-22_dddddddd") is True
    assert repo.delete_time_off(OWNER, "2026-11-22_dddddddd") is False
    assert [t.id for t in repo.time_off_between(OWNER, "2026-11-22", "2026-11-22")] == ["2026-08-01_aaaaaaaa"]


def test_change_professional_swaps_the_locks(repo):
    old = appt("2026-11-17_1000_aaaaaaaa", prof="p1")
    repo.create_appointment(OWNER, old)
    new = replace(old, professional_id="p2", professional_name="Bia")
    repo.change_appointment_professional(OWNER, old, new)
    assert repo.get_appointment(OWNER, old.id) == new
    repo.create_appointment(OWNER, appt("2026-11-17_1000_bbbbbbbb", prof="p1"))       # p1's time is free
    with pytest.raises(SlotConflict):
        repo.create_appointment(OWNER, appt("2026-11-17_1030_cccccccc", "10:30", 30, prof="p2"))   # p2's is taken
    assert repo.cancel_appointment(OWNER, old.id) == new                              # and cancelling frees p2
    repo.create_appointment(OWNER, appt("2026-11-17_1030_cccccccc", "10:30", 30, prof="p2"))


def test_change_professional_refused_if_her_time_was_taken_or_the_appointment_changed(repo):
    old = appt("2026-11-17_1000_aaaaaaaa", prof="p1")
    repo.create_appointment(OWNER, old)
    repo.create_appointment(OWNER, appt("2026-11-17_1045_bbbbbbbb", "10:45", 15, prof="p2"))
    with pytest.raises(SlotConflict, match="ocupado"):
        repo.change_appointment_professional(OWNER, old, replace(old, professional_id="p2"))
    with pytest.raises(SlotConflict, match="alterado"):                            # someone changed it first
        repo.change_appointment_professional(OWNER, replace(old, professional_id="p9"), replace(old, professional_id="p3"))
    repo.cancel_appointment(OWNER, old.id)
    with pytest.raises(SlotConflict, match="alterado"):                            # or cancelled it
        repo.change_appointment_professional(OWNER, old, replace(old, professional_id="p3"))
    assert repo.get_appointment(OWNER, old.id) is None
    repo.create_appointment(OWNER, appt("2026-11-17_1000_cccccccc", prof="p1"))       # nothing was left locked
    repo.create_appointment(OWNER, appt("2026-11-17_1000_dddddddd", prof="p3"))


def test_change_professional_is_one_conditional_transaction():
    db = FakeDynamo()
    repo = DynamoRepository(db, "t")
    old = appt("2026-11-17_1000_aaaaaaaa", duration=30, prof="p1")
    repo.create_appointment(OWNER, old)
    repo.change_appointment_professional(OWNER, old, replace(old, professional_id="p2"))
    operations = db.calls[-1]
    assert operations[0]["Put"]["ConditionExpression"] == "#d = :old"                # only if unchanged
    assert [op["Delete"]["Key"]["SK"]["S"] for op in operations[1:3]] == ["TRAVA#p1#2026-11-17#1000", "TRAVA#p1#2026-11-17#1015"]
    assert [op["Put"]["Item"]["SK"]["S"] for op in operations[3:]] == ["TRAVA#p2#2026-11-17#1000", "TRAVA#p2#2026-11-17#1015"]
    assert all(op["Put"]["ConditionExpression"] == "attribute_not_exists(PK)" for op in operations[3:])
