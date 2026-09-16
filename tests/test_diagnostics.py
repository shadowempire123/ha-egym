"""Diagnostics must not hand out anybody's health data.

The fixture is a full coordinator payload with plausible, *distinctive* values:
the assertions search the finished report for every one of them as a string, so
a field that slips through the allow list is caught by the value it carries
rather than by the name somebody remembered to list.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, ClassVar

from egym.diagnostics import (
    async_get_config_entry_diagnostics,
    describe_shape,
    scrub,
    sensitive_values,
)

USERNAME = "member@example.com"
PASSWORD = "correct-horse-battery-staple"
BRAND = "mygym"

# Every one of these is a measurement of a body. None may appear in the output.
BIOAGE_TOTAL = 41
BODY_FAT = 23.7
BMI = 24.9
VO2MAX = 46.3
RESTING_HEART_RATE = 52
SYSTOLIC = 128
DIASTOLIC = 83
LAST_WORKOUT = "2026-09-15T18:42:11Z"
MEMBER_UUID = "8f14e45f-ceea-467a-9c2b-7a1b2c3d4e5f"

HEALTH_VALUES = [
    BIOAGE_TOTAL,
    BODY_FAT,
    BMI,
    VO2MAX,
    RESTING_HEART_RATE,
    SYSTOLIC,
    DIASTOLIC,
    LAST_WORKOUT,
    MEMBER_UUID,
    USERNAME,
    PASSWORD,
]

DATA = {
    "history_days": 365,
    "history_total": 47,
    "history_gym_total": 6,
    "workout_count": 31,
    "workout_count_30d": 31,
    "gym_workout_count": 4,
    "gym_workout_count_30d": 4,
    "workout_days_30d": 12,
    "gym_workout_days_30d": 4,
    "bioage_total": BIOAGE_TOTAL,
    "bioage_cardio": 39,
    "body_fat": BODY_FAT,
    "bmi": BMI,
    "vo2max": VO2MAX,
    "resting_heart_rate": RESTING_HEART_RATE,
    "blood_pressure_systolic": SYSTOLIC,
    "blood_pressure_diastolic": DIASTOLIC,
    "last_workout_date": LAST_WORKOUT,
    "last_workout_name": "EGYM Leg Press",
    "bioage_hint": "Add your waist-hip ratio to complete your profile",
    "activities_30d": {"EGYM Leg Press": 4, "Spinning / Indoor Cycling": 9, "Treadmill": 2},
    "sources_30d": {"Garmin": 16, "Apple Health": 18},
    "latest_workout": {
        "code": "w-1",
        "completedAt": LAST_WORKOUT,
        "exerciserUuid": MEMBER_UUID,
        "exercises": [
            {
                "name": "EGYM Leg Press",
                "source": {"code": "fitness_machine", "label": "Fitness Machine"},
                "attributes": {"calories": {"value": 431}},
            }
        ],
    },
    "latest_gym_workout": None,
    "bioage": {
        "totalDetails": {"totalBioAge": {"value": BIOAGE_TOTAL, "createdAt": LAST_WORKOUT}},
        "metabolicDetails": {"bodyFat": {"value": BODY_FAT}, "bmi": {"value": BMI}},
        "cardioDetails": {
            "vo2max": {"value": VO2MAX},
            "restingHeartRate": {"value": RESTING_HEART_RATE},
            "systolicPressure": {"value": SYSTOLIC},
            "diastolicPressure": {"value": DIASTOLIC},
        },
    },
}


class FakeEntry:
    entry_id = "abc123"
    data: ClassVar[dict[str, Any]] = {"brand": BRAND, "username": USERNAME, "password": PASSWORD}
    options: ClassVar[dict[str, Any]] = {"scan_interval": 900, "body_values": True}


class FakeCoordinator:
    data: ClassVar[dict[str, Any]] = DATA
    last_update_success = True

    class update_interval:
        @staticmethod
        def total_seconds():
            return 900.0


class FakeHass:
    data: ClassVar[dict[str, Any]] = {"egym": {FakeEntry.entry_id: FakeCoordinator()}}


def report():
    return asyncio.run(async_get_config_entry_diagnostics(FakeHass(), FakeEntry()))


def test_no_measurement_of_a_body_survives():
    rendered = json.dumps(report())
    for value in HEALTH_VALUES:
        assert str(value) not in rendered, f"{value!r} leaked into the diagnostics"


def test_the_counts_do_survive_because_that_is_what_reports_are_about():
    counts = report()["counts"]
    assert counts["history_total"] == 47
    assert counts["workout_days_30d"] == 12
    assert counts["gym_workout_count"] == 4


def test_the_field_names_survive_even_though_the_values_do_not():
    """A renamed key is the failure this whole layer exists to diagnose."""
    described = report()["field_types"]
    assert described["bioage_total"] == "int"
    assert described["body_fat"] == "float"
    assert described["last_workout_date"] == "str"
    shapes = report()["payload_shapes"]
    assert "totalDetails" in shapes["bioage"]
    assert "exercises" in shapes["latest_workout"]


def test_the_exercises_are_counted_rather_than_named():
    """describe_shape keeps dictionary keys, and here the keys are the member's
    own training profile rather than anything the API defines."""
    described = report()["field_types"]
    assert described["activities_30d"] == "dict[3]"
    # The connected apps are a fixed vocabulary naming a service, not a person,
    # and the triple counting they cause is what most reports are about.
    assert described["sources_30d"] == {"Apple Health": "int", "Garmin": "int"}


def test_the_brand_is_kept_and_the_credentials_are_not():
    entry = report()["entry"]["data"]
    assert entry["brand"] == BRAND
    assert entry["username"] == "**REDACTED**"
    assert entry["password"] == "**REDACTED**"


def test_the_options_are_reported_so_a_switched_off_sensor_is_not_a_mystery():
    assert report()["entry"]["options"]["body_values"] is True
    assert report()["coordinator"]["update_interval_seconds"] == 900.0


def test_an_entry_that_never_finished_setting_up_still_produces_a_report():
    class EmptyHass:
        data: ClassVar[dict[str, Any]] = {}

    result = asyncio.run(async_get_config_entry_diagnostics(EmptyHass(), FakeEntry()))
    assert result["coordinator"]["last_update_success"] is False
    assert result["counts"]["history_total"] is None


def test_describe_shape_keeps_names_and_types_but_no_values():
    assert describe_shape({"a": 1, "b": "x", "c": None}) == {
        "a": "int",
        "b": "str",
        "c": "NoneType",
    }
    assert describe_shape([{"v": 1}, {"v": 2}, {"v": 3}]) == [{"v": "int"}, "... 3 items"]
    assert describe_shape([]) == []
    # Deep enough and it stops descending, so a pathological payload cannot
    # turn a bug report into a novel.
    assert describe_shape({"a": {"b": {"c": {"d": {"e": 1}}}}})["a"]["b"]["c"]["d"] == "dict[1]"


def test_the_value_scrub_is_a_second_line_of_defence():
    secrets = sensitive_values({"username": USERNAME, "password": PASSWORD})
    assert secrets == {USERNAME, PASSWORD}
    scrubbed = scrub({"note": f"failed for {USERNAME}", "ok": True, "n": 1}, secrets)
    assert scrubbed == {"note": "**REDACTED**", "ok": True, "n": 1}


def test_a_short_secret_is_not_used_as_a_needle():
    """Below four characters a "secret" matches half the report by accident."""
    assert sensitive_values({"username": "me", "password": "x"}) == set()
