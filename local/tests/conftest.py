import sys
import threading
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local"))                  # MemoryRepository and the local API Gateway

import api_gateway  # noqa: E402,F401  (puts backend/core and backend/lambdas on the path, like each zip)
from agenda_core.adapters.dynamo_repository import DynamoRepository  # noqa: E402
from agenda_core.ports import Dependencies  # noqa: E402
from book_appointment.use_case import book_appointment  # noqa: E402
from cancel_appointment.use_case import cancel_appointment  # noqa: E402
from change_appointment_professional.use_case import change_appointment_professional  # noqa: E402
from create_professional.use_case import create_professional  # noqa: E402
from create_service.use_case import create_service  # noqa: E402
from create_time_off.use_case import create_time_off  # noqa: E402
from delete_professional.use_case import delete_professional  # noqa: E402
from delete_service.use_case import delete_service  # noqa: E402
from delete_time_off.use_case import delete_time_off  # noqa: E402
from get_availability.use_case import get_availability  # noqa: E402
from get_settings.use_case import get_settings  # noqa: E402
from list_appointments.use_case import list_appointments  # noqa: E402
from list_professionals.use_case import list_professionals  # noqa: E402
from list_services.use_case import list_services  # noqa: E402
from list_time_off.use_case import list_time_off  # noqa: E402
from memory_repository import MemoryRepository  # noqa: E402
from save_settings.use_case import save_settings  # noqa: E402
from update_professional.use_case import update_professional  # noqa: E402
from update_service.use_case import update_service  # noqa: E402

NOW = datetime(2026, 11, 16, 10, 0)         # Monday, 10:00
OWNER = "owner-a"
OTHER = "owner-b"


def salon_hours(days, start, end):
    """PUT /settings body: the salon open on `days` (0 = Monday), from `start` to `end` on each."""
    return {"hours": [{"day": d, "start": start, "end": end} for d in days]}


class FakeClientError(Exception):
    """Mimics botocore.ClientError: has `.response`."""

    def __init__(self, code, reasons=()):
        super().__init__(code)
        self.response = {"Error": {"Code": code},
                         "CancellationReasons": [{"Code": r} for r in reasons]}


class FakeDynamo:
    """Only what the repository uses. A transaction is all-or-nothing, like in the real DynamoDB."""

    def __init__(self, page_size=2):
        self.items, self.page_size, self.calls = {}, page_size, []
        self._lock = threading.Lock()       # the real transaction is atomic even with concurrent calls

    @staticmethod
    def _k(key):
        return key["PK"]["S"], key["SK"]["S"]

    def get_item(self, TableName, Key, ConsistentRead=False):
        item = self.items.get(self._k(Key))
        return {"Item": item} if item else {}

    def put_item(self, TableName, Item):
        self.items[self._k(Item)] = Item

    def delete_item(self, TableName, Key):
        self.items.pop(self._k(Key), None)

    def query(self, TableName, KeyConditionExpression, ExpressionAttributeValues,
              ConsistentRead=False, ExclusiveStartKey=None, IndexName=None):
        values = {k: v["S"] for k, v in ExpressionAttributeValues.items()}
        if IndexName:
            return self._query_index(IndexName, KeyConditionExpression, values, ConsistentRead, ExclusiveStartKey)
        if "begins_with(SK, :p)" in KeyConditionExpression:
            matches = lambda sk: sk.startswith(values[":p"])                          # noqa: E731
        else:
            assert "SK BETWEEN :low AND :high" in KeyConditionExpression, KeyConditionExpression
            matches = lambda sk: values[":low"] <= sk <= values[":high"]              # noqa: E731
        pk = values[":pk"]
        found = sorted(k for k in self.items if k[0] == pk and matches(k[1]))
        if ExclusiveStartKey:
            found = [k for k in found if k[1] > ExclusiveStartKey["SK"]["S"]]
        page, rest = found[:self.page_size], found[self.page_size:]
        response = {"Items": [self.items[k] for k in page]}
        if rest:
            response["LastEvaluatedKey"] = {"PK": {"S": pk}, "SK": {"S": page[-1][1]}}
        return response

    def _query_index(self, index, condition, values, consistent, start):
        """The by_client index: items whose GSI1PK is the value, ordered by GSI1SK. Like the real one, an
        index cannot be read consistently."""
        assert index == "by_client" and condition == "GSI1PK = :c" and not consistent, (index, condition)
        found = sorted((item["GSI1SK"]["S"], key) for key, item in self.items.items()
                       if item.get("GSI1PK", {}).get("S") == values[":c"])
        if start:
            found = [f for f in found if f[0] > start["GSI1SK"]["S"]]
        page, rest = found[:self.page_size], found[self.page_size:]
        response = {"Items": [self.items[key] for _, key in page]}
        if rest:
            response["LastEvaluatedKey"] = {"GSI1SK": {"S": page[-1][0]}}
        return response

    def _condition_holds(self, put):
        """The two conditions the repository uses: "not there yet" and "unchanged since it was read"."""
        condition = put and put.get("ConditionExpression")
        if not condition:
            return True
        current = self.items.get(self._k(put["Item"]))
        if condition == "attribute_not_exists(PK)":
            return current is None
        assert condition == "#d = :old", condition
        attribute = put["ExpressionAttributeNames"]["#d"]
        return current is not None and current.get(attribute) == put["ExpressionAttributeValues"][":old"]

    def transact_write_items(self, TransactItems):
        with self._lock:
            self._transaction(TransactItems)

    def _transaction(self, TransactItems):
        self.calls.append(TransactItems)
        reasons = ["None" if self._condition_holds(op.get("Put")) else "ConditionalCheckFailed" for op in TransactItems]
        if "ConditionalCheckFailed" in reasons:
            raise FakeClientError("TransactionCanceledException", reasons)
        for op in TransactItems:
            if "Put" in op:
                self.put_item(**{"TableName": "t", "Item": op["Put"]["Item"]})
            else:
                self.delete_item(TableName="t", Key=op["Delete"]["Key"])


@pytest.fixture(params=["memory", "dynamo"])
def repo(request):
    """Every rule test runs against both repositories: they must behave the same."""
    return MemoryRepository() if request.param == "memory" else DynamoRepository(FakeDynamo(), "t")


class UseCases:
    """Calls each Lambda's use case directly (no HTTP), under short names for the tests."""

    def __init__(self, deps):
        self.deps = deps

    def list_items(self, owner, kind):
        return (list_services if kind == "service" else list_professionals)(self.deps, owner)

    def create(self, owner, kind, payload):
        return (create_service if kind == "service" else create_professional)(self.deps, owner, payload)

    def update(self, owner, kind, id, payload):
        return (update_service if kind == "service" else update_professional)(self.deps, owner, id, payload)

    def remove(self, owner, kind, id):
        return (delete_service if kind == "service" else delete_professional)(self.deps, owner, id)

    def settings(self, owner):
        return get_settings(self.deps, owner)

    def save_settings(self, owner, payload):
        return save_settings(self.deps, owner, payload)

    def availability(self, owner, date, service_id, professional_id):
        return get_availability(self.deps, owner, date, service_id, professional_id)

    def day_schedule(self, owner, date):
        return list_appointments(self.deps, owner, {"date": date})

    def schedule_between(self, owner, first, last):
        return list_appointments(self.deps, owner, {"from": first, "to": last})

    def book(self, owner, payload):
        return book_appointment(self.deps, owner, payload)

    def cancel(self, owner, id):
        return cancel_appointment(self.deps, owner, id)

    def change_professional(self, owner, id, payload):
        return change_appointment_professional(self.deps, owner, id, payload)

    def time_off_between(self, owner, first, last):
        return list_time_off(self.deps, owner, first, last)

    def create_time_off(self, owner, payload):
        return create_time_off(self.deps, owner, payload)

    def delete_time_off(self, owner, id):
        return delete_time_off(self.deps, owner, id)


@pytest.fixture
def agenda(repo):
    return UseCases(Dependencies(repo, lambda: NOW))


@pytest.fixture
def salon(agenda):
    """A 60-minute service, a 30-minute one, and a professional who performs both."""
    haircut = agenda.create(OWNER, "service", {"name": "Haircut", "duration_min": 60, "price_cents": 8000})
    nails = agenda.create(OWNER, "service", {"name": "Nails", "duration_min": 30, "price_cents": 4000})
    ana = agenda.create(OWNER, "professional", {"name": "Ana", "services": [haircut.id, nails.id]})
    return haircut, nails, ana


def booking(service, professional, start="10:00", date="2026-11-17", **extra):
    return {"date": date, "start": start, "service_id": service.id, "professional_id": professional.id,
            "client_name": "Maria", "client_phone": "(11) 98888-7777", **extra}
