import sys
import threading
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agenda.agenda import Agenda  # noqa: E402
from agenda.dynamo_repository import DynamoRepository  # noqa: E402
from agenda.memory_repository import MemoryRepository  # noqa: E402

NOW = datetime(2026, 11, 16, 10, 0)         # Monday, 10:00
OWNER = "owner-a"
OTHER = "owner-b"


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
              ConsistentRead=False, ExclusiveStartKey=None):
        values = {k: v["S"] for k, v in ExpressionAttributeValues.items()}
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


@pytest.fixture
def agenda(repo):
    return Agenda(repo, lambda: NOW)


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
