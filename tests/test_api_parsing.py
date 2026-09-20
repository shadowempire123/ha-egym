"""The parsing layer guesses the field names of an undocumented API.

When eGym renames a key a sensor simply goes quiet, with nothing in the log, so
the shapes recorded in docs/API.md are pinned down here. The awkward parts --
"unknown rather than a misleading zero", and counting calendar days rather than
rows -- are what the numbers on a dashboard actually mean.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from egym.api import (
    _bioage_field,
    _bioage_value,
    _completed_at,
    _distinct_days,
    _is_gym_workout,
    _rfc3339,
    _source_breakdown,
    _sum_attribute,
    _sum_many,
    _top_weight,
    _volume,
    _within,
)

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def workout(when: str, *, source="fitness_machine", label="Fitness Machine", **attributes):
    """One workout with a single exercise, in the shape the API returns."""
    return {
        "completedAt": when,
        "exercises": [
            {
                "name": "EGYM Leg Press",
                "source": {"code": source, "label": label},
                "attributes": {
                    name: value if isinstance(value, list) else {"value": value}
                    for name, value in attributes.items()
                },
            }
        ],
    }


def strength_workout(sets):
    return {
        "completedAt": "2026-09-15T12:00:00Z",
        "exercises": [
            {
                "name": "EGYM Chest Press",
                "source": {"code": "fitness_machine", "label": "Fitness Machine"},
                "attributes": {
                    "sets_of_reps_and_weight_or_duration_and_weight": [
                        {"reps": {"value": reps}, "weight": {"value": weight}}
                        for reps, weight in sets
                    ]
                },
            }
        ],
    }


def test_the_timestamp_format_is_the_only_one_the_api_accepts():
    # Anything else answers HTTP 400 "wrongFormat" -- no "+00:00", no
    # milliseconds, no date-only.
    assert _rfc3339(NOW) == "2026-09-16T12:00:00Z"
    assert _rfc3339(datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)) == (
        "2026-01-02T03:04:05Z"
    )


@pytest.mark.parametrize("raw", [None, "", "not a date", "2026-13-45T99:99:99Z"])
def test_an_unparseable_timestamp_sorts_last_instead_of_crashing(raw):
    sortable = _completed_at({"completedAt": raw} if raw is not None else {})
    assert sortable == datetime.min.replace(tzinfo=UTC)


def test_a_workout_is_a_gym_workout_only_when_a_machine_recorded_it():
    assert _is_gym_workout(workout("2026-09-15T12:00:00Z"))
    assert not _is_gym_workout(
        workout("2026-09-15T12:00:00Z", source="connected_app", label="Garmin")
    )
    assert not _is_gym_workout({})
    assert not _is_gym_workout({"exercises": None})


def test_windows_are_cut_by_completion_time():
    inside = workout("2026-09-15T12:00:00Z")
    outside = workout("2026-08-01T12:00:00Z")
    assert _within([inside, outside], 7, NOW) == [inside]
    assert _within([inside, outside], 365, NOW) == [inside, outside]


def test_distinct_days_is_what_survives_the_triple_counting():
    """eGym files one workout per connected app for the same bike ride.

    Three rows, one day. Counting rows says three sessions; counting days says
    one, which is the true answer and the reason the dashboard leads with it.
    """
    same_ride = [
        workout("2026-09-15T12:00:00Z", source="connected_app", label=label)
        for label in ("Garmin", "Strava", "Apple Health")
    ]
    assert len(same_ride) == 3
    assert _distinct_days(same_ride) == 1
    assert _distinct_days([*same_ride, workout("2026-09-14T12:00:00Z")]) == 2


def test_a_workout_without_a_date_belongs_to_no_day():
    assert _distinct_days([{"exercises": []}]) == 0


def test_the_source_breakdown_counts_each_workout_once_per_source():
    workouts = [
        workout("2026-09-15T12:00:00Z", source="connected_app", label="Garmin"),
        workout("2026-09-14T12:00:00Z", source="connected_app", label="Garmin"),
        workout("2026-09-13T12:00:00Z", source="connected_app", label="Strava"),
    ]
    # Sorted by count, descending: the dashboard reads top-down.
    assert list(_source_breakdown(workouts).items()) == [("Garmin", 2), ("Strava", 1)]


def test_a_missing_attribute_is_unknown_rather_than_zero():
    """A pure-cardio session has no volume; 0 kg would be a lie on a card."""
    assert _sum_attribute(workout("2026-09-15T12:00:00Z"), "calories") is None
    assert _sum_attribute(workout("2026-09-15T12:00:00Z", calories=430), "calories") == 430
    assert _sum_many([], "calories") is None
    assert _volume(workout("2026-09-15T12:00:00Z")) is None
    assert _top_weight(workout("2026-09-15T12:00:00Z")) is None


def test_a_boolean_is_not_a_number():
    # bool is a subclass of int in Python, so a flag would otherwise be summed.
    assert _sum_attribute(workout("2026-09-15T12:00:00Z", calories=True), "calories") is None


def test_volume_is_reps_times_weight_across_every_set():
    session = strength_workout([(12, 40.0), (10, 45.0), (8, 50.0)])
    assert _volume(session) == pytest.approx(12 * 40 + 10 * 45 + 8 * 50)
    assert _top_weight(session) == 50.0


def test_an_incomplete_set_is_skipped_rather_than_counted_as_zero():
    session = {
        "exercises": [
            {
                "attributes": {
                    "sets_of_reps_and_weight_or_duration_and_weight": [
                        {"reps": {"value": 10}, "weight": {"value": 40.0}},
                        {"duration": {"value": 60}},
                    ]
                }
            }
        ]
    }
    assert _volume(session) == pytest.approx(400.0)



MEASURED = "2026-09-19T13:45:35Z"
BIOAGE = {
    "totalDetails": {
        "totalBioAge": {"value": 52, "amountDiff": -3, "progress": "down", "createdAt": MEASURED},
    },
    "flexibilityDetails": {
        "flexibilityAge": {"value": 54, "amountDiff": None, "createdAt": MEASURED},
    },
    "metabolicDetails": {"waistToHipRatio": None},
}


def test_flexibility_arrives_once_the_mobility_test_is_done():
    assert _bioage_value(BIOAGE, "flexibilityDetails", "flexibilityAge") == 54
    # Before the test the whole section is null, and so is the sensor.
    assert _bioage_value({"flexibilityDetails": None}, "flexibilityDetails", "flexibilityAge") is None
    assert _bioage_value({}, "flexibilityDetails", "flexibilityAge") is None


def test_the_change_is_read_as_is_and_a_null_metric_does_not_crash():
    """A negative change means the score got younger; None means eGym has no
    previous measurement to compare against, which is not the same as zero."""
    assert _bioage_field(BIOAGE, "totalDetails", "totalBioAge", "amountDiff") == -3
    assert _bioage_field(BIOAGE, "flexibilityDetails", "flexibilityAge", "amountDiff") is None
    assert _bioage_value(BIOAGE, "metabolicDetails", "waistToHipRatio") is None
