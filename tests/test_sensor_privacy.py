"""The body-values switch has to actually remove the entities.

An option that only hides something on a dashboard is worse than no option at
all: the history still accumulates in the recorder database and travels in
every backup taken of it.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from egym.sensor import BODY_VALUE_KEYS, SENSOR_DESCRIPTIONS, _as_datetime, async_setup_entry

ALL_KEYS = {description.key for description in SENSOR_DESCRIPTIONS}


class FakeEntry:
    entry_id = "abc123"
    data: ClassVar[dict[str, Any]] = {"username": "member@example.com"}

    def __init__(self, options=None):
        self.options = options or {}


class FakeHass:
    def __init__(self):
        self.data = {"egym": {FakeEntry.entry_id: object()}}


def keys_created(options):
    created = []

    def add_entities(entities):
        created.extend(entity.entity_description.key for entity in entities)

    asyncio.run(async_setup_entry(FakeHass(), FakeEntry(options), add_entities))
    return set(created)


def test_the_switch_is_on_by_default():
    assert keys_created({}) == ALL_KEYS


def test_switching_it_off_removes_every_body_value_and_nothing_else():
    remaining = keys_created({"body_values": False})
    assert remaining == ALL_KEYS - BODY_VALUE_KEYS
    assert not remaining & BODY_VALUE_KEYS
    # The training sensors are the point of the integration and must stay.
    assert {"workout_count", "gym_workout_count", "last_workout_date"} <= remaining


def test_every_body_value_key_is_a_sensor_that_exists():
    """A typo here would silently leave a health sensor switched on."""
    assert BODY_VALUE_KEYS <= ALL_KEYS


def test_the_body_values_are_the_ones_a_person_would_call_health_data():
    assert {
        "bioage_total",
        "bioage_cardio",
        "bioage_metabolic",
        "bioage_muscle",
        "bioage_flexibility",
        "bioage_upper_body",
        "bioage_core",
        "bioage_lower_body",
        "body_fat",
        "bmi",
        "vo2max",
        "resting_heart_rate",
        "waist_to_hip_ratio",
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
    } == BODY_VALUE_KEYS


def test_the_entity_id_never_carries_the_account():
    """The device name prefixes every entity id, so naming the device after the
    member would put an email address on every dashboard."""
    from egym.entity import device_info_for

    info = device_info_for("Member@Example.COM")
    assert info["name"] == "eGym"
    assert "example.com" not in str(info["name"]).lower()
    # The identifier is allowed to carry it -- it is not displayed anywhere.
    assert info["identifiers"] == {("egym", "member@example.com")}


def test_a_timestamp_without_a_zone_is_read_as_utc_rather_than_dropped():
    assert _as_datetime("2026-09-15T18:42:11Z").tzinfo is not None
    assert _as_datetime("2026-09-15T18:42:11").tzinfo is not None
    assert _as_datetime("not a date") is None
    assert _as_datetime(None) is None
