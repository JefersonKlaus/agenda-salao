"""DynamoDB repository, single table.

PK = SALAO#<owner>   SK = SERV#id | PROF#id | CONF | AGE#<appointment id> | TRAVA#<block> | OFF#<absence id>
The item stores the whole object as JSON in the `dados` attribute. The `owner` always comes from
the login token, never from what the browser sends: that is what keeps each salon's data apart.

Storage format: the key prefixes above, the `dados` attribute and the field names inside the JSON
were created in Portuguese and are kept exactly as they are, so that items already in the table
stay readable (and an older version of the code can still be rolled back to). Only this module
knows about them: everything else uses the English names.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Optional

from ..domain.models import MAX_TIME_OFF_DAYS, MODELS, Appointment, Settings, TimeOff
from ..domain.errors import SlotConflict
from ..domain.scheduling import lock_keys

PREFIXES = {"service": "SERV#", "professional": "PROF#"}
SETTINGS_KEY, APPOINTMENT_PREFIX, LOCK_PREFIX, OWNER_PREFIX = "CONF", "AGE#", "TRAVA#", "SALAO#"
TIME_OFF_PREFIX = "OFF#"            # newer than the others, so its name is in English
DATA_ATTRIBUTE = "dados"

# English field name (code) -> field name stored in the table. Fields not listed are stored as is.
STORED_FIELD_NAMES = {
    "name": "nome", "duration_min": "duracao_min", "price_cents": "preco_centavos",
    "services": "servicos", "open_days": "dias_abertos", "opens": "abre", "closes": "fecha",
    "date": "data", "start": "inicio", "professional_id": "profissional_id",
    "professional_name": "profissional_nome", "service_id": "servico_id", "service_name": "servico_nome",
    "client_name": "cliente_nome", "client_phone": "cliente_telefone",
}
_FIELD_NAMES_FROM_STORAGE = {stored: field for field, stored in STORED_FIELD_NAMES.items()}


def to_storage(obj: dict[str, Any]) -> dict[str, Any]:
    return {STORED_FIELD_NAMES.get(k, k): v for k, v in obj.items()}


def from_storage(stored: dict[str, Any]) -> dict[str, Any]:
    return {_FIELD_NAMES_FROM_STORAGE.get(k, k): v for k, v in stored.items()}


class DynamoRepository:
    def __init__(self, client: Any, table: str) -> None:
        self.client, self.table = client, table

    # -------------------------------------------------------------- low level
    @staticmethod
    def _pk(owner: str) -> dict[str, str]:
        return {"S": f"{OWNER_PREFIX}{owner}"}

    def _key(self, owner: str, sk: str) -> dict[str, Any]:
        return {"PK": self._pk(owner), "SK": {"S": sk}}

    def _item(self, owner: str, sk: str, obj: dict[str, Any]) -> dict[str, Any]:
        return {**self._key(owner, sk),
                DATA_ATTRIBUTE: {"S": json.dumps(to_storage(obj), ensure_ascii=False)}}

    def _read(self, owner: str, sk: str) -> Optional[dict[str, Any]]:
        response = self.client.get_item(TableName=self.table, Key=self._key(owner, sk),
                                        ConsistentRead=True)
        item = response.get("Item")
        return from_storage(json.loads(item[DATA_ATTRIBUTE]["S"])) if item else None

    def _query_prefix(self, owner: str, prefix: str) -> list[dict[str, Any]]:
        return self._query(owner, "begins_with(SK, :p)", {":p": {"S": prefix}})

    def _query_range(self, owner: str, low: str, high: str) -> list[dict[str, Any]]:
        """Items whose SK is between `low` and `high`, both inclusive."""
        return self._query(owner, "SK BETWEEN :low AND :high", {":low": {"S": low}, ":high": {"S": high}})

    def _query(self, owner: str, sk_condition: str, values: dict[str, Any]) -> list[dict[str, Any]]:
        items, start_key = [], None
        while True:
            request = {"TableName": self.table, "ConsistentRead": True,
                       "KeyConditionExpression": f"PK = :pk AND {sk_condition}",
                       "ExpressionAttributeValues": {":pk": self._pk(owner), **values}}
            if start_key:
                request["ExclusiveStartKey"] = start_key
            response = self.client.query(**request)
            items += [from_storage(json.loads(i[DATA_ATTRIBUTE]["S"])) for i in response.get("Items", [])]
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                return items

    # -------------------------------------------------------------- services and professionals
    def list_items(self, owner: str, kind: str) -> list[Any]:
        return [MODELS[kind].from_dict(d) for d in self._query_prefix(owner, PREFIXES[kind])]

    def get(self, owner: str, kind: str, id: str) -> Optional[Any]:
        data = self._read(owner, PREFIXES[kind] + id)
        return MODELS[kind].from_dict(data) if data else None

    def save(self, owner: str, kind: str, item: Any) -> None:
        self.client.put_item(TableName=self.table,
                             Item=self._item(owner, PREFIXES[kind] + item.id, item.to_dict()))

    def delete(self, owner: str, kind: str, id: str) -> None:
        self.client.delete_item(TableName=self.table, Key=self._key(owner, PREFIXES[kind] + id))

    def get_settings(self, owner: str) -> Optional[Settings]:
        data = self._read(owner, SETTINGS_KEY)
        return Settings.from_dict(data) if data else None

    def save_settings(self, owner: str, settings: Settings) -> None:
        self.client.put_item(TableName=self.table,
                             Item=self._item(owner, SETTINGS_KEY, settings.to_dict()))

    # -------------------------------------------------------------- appointments
    def appointments_on_day(self, owner: str, date: str) -> list[Appointment]:
        return [Appointment.from_dict(d) for d in self._query_prefix(owner, f"{APPOINTMENT_PREFIX}{date}_")]

    def appointments_between(self, owner: str, first: str, last: str) -> list[Appointment]:
        # Appointment ids start with "YYYY-MM-DD_", and "~" sorts after every character they use.
        return [Appointment.from_dict(d) for d in self._query_range(
            owner, f"{APPOINTMENT_PREFIX}{first}_", f"{APPOINTMENT_PREFIX}{last}_~")]

    def change_appointment_professional(self, owner: str, old: Appointment, new: Appointment) -> None:
        """In one transaction: rewrites the appointment, frees the old professional's locks and takes the
        new one's. It only goes through if the appointment is still exactly `old` (not cancelled or
        changed meanwhile) and nobody took the new professional's time."""
        key = self._key(owner, f"{APPOINTMENT_PREFIX}{old.id}")
        stored = self.client.get_item(TableName=self.table, Key=key, ConsistentRead=True).get("Item")
        if stored is None or Appointment.from_dict(from_storage(json.loads(stored[DATA_ATTRIBUTE]["S"]))) != old:
            raise SlotConflict("esse agendamento acabou de ser alterado; atualize a agenda")
        not_exists = "attribute_not_exists(PK)"
        operations = [{"Put": {"TableName": self.table, "Item": self._item(owner, f"{APPOINTMENT_PREFIX}{new.id}", new.to_dict()),
                               "ConditionExpression": "#d = :old", "ExpressionAttributeNames": {"#d": DATA_ATTRIBUTE},
                               "ExpressionAttributeValues": {":old": stored[DATA_ATTRIBUTE]}}}]
        for k in lock_keys(old.professional_id, old.date, old.start_min, old.duration_min):
            operations.append({"Delete": {"TableName": self.table, "Key": self._key(owner, f"{LOCK_PREFIX}{k}")}})
        for k in lock_keys(new.professional_id, new.date, new.start_min, new.duration_min):
            operations.append({"Put": {"TableName": self.table, "ConditionExpression": not_exists,
                                       "Item": self._item(owner, f"{LOCK_PREFIX}{k}", {"ag": new.id})}})
        try:
            self.client.transact_write_items(TransactItems=operations)
        except Exception as error:      # botocore.ClientError, without importing botocore here
            if _is_condition_failure(error):
                raise SlotConflict("esse horário acabou de ser ocupado") from None
            raise

    # -------------------------------------------------------------- absences
    def time_off_between(self, owner: str, first: str, last: str) -> list[TimeOff]:
        """Absences that touch [first, last]. Ids start with their first day, and an absence lasts at
        most MAX_TIME_OFF_DAYS, so only that far back needs to be read."""
        earliest = (date.fromisoformat(first) - timedelta(days=MAX_TIME_OFF_DAYS)).isoformat()
        found = [TimeOff.from_dict(d) for d in self._query_range(
            owner, f"{TIME_OFF_PREFIX}{earliest}_", f"{TIME_OFF_PREFIX}{last}_~")]
        return [t for t in found if t.last_day >= first]

    def save_time_off(self, owner: str, time_off: TimeOff) -> None:
        self.client.put_item(TableName=self.table,
                             Item=self._item(owner, f"{TIME_OFF_PREFIX}{time_off.id}", time_off.to_dict()))

    def delete_time_off(self, owner: str, id: str) -> bool:
        if self._read(owner, f"{TIME_OFF_PREFIX}{id}") is None:
            return False
        self.client.delete_item(TableName=self.table, Key=self._key(owner, f"{TIME_OFF_PREFIX}{id}"))
        return True

    def get_appointment(self, owner: str, id: str) -> Optional[Appointment]:
        data = self._read(owner, f"{APPOINTMENT_PREFIX}{id}")
        return Appointment.from_dict(data) if data else None

    def create_appointment(self, owner: str, appt: Appointment) -> None:
        """Writes the appointment and one lock per 15-minute block in a single transaction.
        If any lock already exists, nothing is written and the slot is refused."""
        not_exists = "attribute_not_exists(PK)"
        operations = [{"Put": {"TableName": self.table, "ConditionExpression": not_exists,
                               "Item": self._item(owner, f"{APPOINTMENT_PREFIX}{appt.id}", appt.to_dict())}}]
        for key in lock_keys(appt.professional_id, appt.date, appt.start_min, appt.duration_min):
            operations.append({"Put": {"TableName": self.table, "ConditionExpression": not_exists,
                                       "Item": self._item(owner, f"{LOCK_PREFIX}{key}", {"ag": appt.id})}})
        try:
            self.client.transact_write_items(TransactItems=operations)
        except Exception as error:      # botocore.ClientError, without importing botocore here
            if _is_condition_failure(error):
                raise SlotConflict("esse horário acabou de ser ocupado") from None
            raise

    def cancel_appointment(self, owner: str, id: str) -> Optional[Appointment]:
        appt = self.get_appointment(owner, id)
        if appt is None:
            return None
        operations = [{"Delete": {"TableName": self.table, "Key": self._key(owner, f"{APPOINTMENT_PREFIX}{id}")}}]
        for key in lock_keys(appt.professional_id, appt.date, appt.start_min, appt.duration_min):
            operations.append({"Delete": {"TableName": self.table,
                                          "Key": self._key(owner, f"{LOCK_PREFIX}{key}")}})
        self.client.transact_write_items(TransactItems=operations)
        return appt


def _is_condition_failure(error: Exception) -> bool:
    response = getattr(error, "response", None) or {}
    if response.get("Error", {}).get("Code") != "TransactionCanceledException":
        return False
    return any(r.get("Code") == "ConditionalCheckFailed"
               for r in response.get("CancellationReasons", []))
