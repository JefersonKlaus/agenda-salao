"""The agenda runs on Brasília time, whatever the machine's time zone (a UTC server once made the
local server think it was 3 hours later, hiding the afternoon's free times as "past")."""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from agenda.clock import salon_now


@pytest.fixture
def machine_time_zone():
    """Changes this process's time zone, like running on a machine configured differently."""
    original = os.environ.get("TZ")

    def set_zone(zone):
        os.environ["TZ"] = zone
        time.tzset()
    yield set_zone
    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


@pytest.mark.parametrize("zone", ["UTC", "Asia/Tokyo", "America/New_York", "America/Sao_Paulo"])
def test_salon_now_is_brasilia_time_on_any_machine(machine_time_zone, zone):
    machine_time_zone(zone)
    expected = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)
    now = salon_now()
    assert now.tzinfo is None and abs(now - expected) < timedelta(seconds=5)


def test_the_lambda_and_the_local_server_use_the_salon_clock():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for path in ("backend/src/agenda/handler.py", "e2e/local_server.py"):
        source = (root / path).read_text(encoding="utf-8")
        assert "Agenda(" in source and "salon_now" in source and "datetime.now" not in source, path
