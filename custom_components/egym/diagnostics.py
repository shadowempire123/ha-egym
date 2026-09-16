"""Diagnostics for issue reports.

A downloaded diagnostics file usually ends up pasted into a public issue, and
what this integration holds is health data: bio-age, body fat, BMI, VO2max,
resting heart rate, blood pressure, and a dated record of when somebody trained
and where. None of that belongs in a bug report, and unlike a password it
cannot be changed after it has been published.

So the rule here is inverted compared to the usual redaction list. Nothing is
included unless it is on the allow list below; everything else is reduced to
its *shape* -- which fields arrived and of what type -- which is what actually
tells a maintainer whether the parser saw what it expected. A value-based scrub
runs over the result as a second line of defence.

The brand is deliberately kept. It names the gym, not the member, and it is the
one setting that differs between installations, so a report without it is
almost always unanswerable -- the same trade-off Home Assistant's own
integrations make with a hostname.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import WINDOWS
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN

REDACTED = "**REDACTED**"

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}

# Counts, and only counts. These say whether the windowing and the
# gym-versus-mirrored-app split work, which is what nearly every report is
# about, and no one of them is a measurement of a body.
SAFE_FIELDS = (
    "history_days",
    "history_total",
    "history_gym_total",
    "workout_count",
    "gym_workout_count",
    *(
        f"{name}_{days}d"
        for days in WINDOWS
        for name in ("workout_count", "gym_workout_count", "workout_days", "gym_workout_days")
    ),
)

# The unparsed API responses. Their field names are the useful part -- that is
# how a renamed key gets spotted -- and their values are exactly the part that
# must not travel.
RAW_PAYLOADS = ("latest_workout", "latest_gym_workout", "bioage")

# Breakdowns keyed by something the *member* generated rather than by a field
# name the API defines. "Which fields arrived" is diagnostic; "EGYM Glutes,
# Spinning, Treadmill, Walking Outdoor" is a training profile, and describe_shape
# keeps dictionary keys by design. So these are reduced to a count.
#
# sources_* is deliberately not among them: its keys are the connected apps
# (Garmin, Strava, Apple Health), a short fixed vocabulary that names a service
# rather than a person -- and the triple-counting those cause is the single
# most reported thing about this integration.
COUNTED_ONLY = ("activities_",)

MAX_SHAPE_DEPTH = 4


def describe_shape(value: Any, depth: int = 0) -> Any:
    """Return the structure of a payload without any of its values."""
    if isinstance(value, dict):
        if depth >= MAX_SHAPE_DEPTH:
            return f"dict[{len(value)}]"
        return {key: describe_shape(item, depth + 1) for key, item in sorted(value.items())}
    if isinstance(value, list):
        if not value:
            return []
        if depth >= MAX_SHAPE_DEPTH:
            return f"list[{len(value)}]"
        return [describe_shape(value[0], depth + 1), f"... {len(value)} items"]
    return type(value).__name__


def sensitive_values(entry_data: dict[str, Any]) -> set[str]:
    """Strings that must not appear anywhere in the output."""
    values = {
        str(entry_data[key])
        for key in (CONF_USERNAME, CONF_PASSWORD)
        if entry_data.get(key)
    }
    # Below four characters a "secret" matches half the report by accident.
    return {value for value in values if len(value) >= 4}


def scrub(value: Any, secrets: set[str]) -> Any:
    """Replace anything that still carries one of the sensitive values."""
    if isinstance(value, dict):
        return {key: scrub(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item, secrets) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    text = str(value)
    if any(secret in text for secret in secrets):
        return REDACTED
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = (coordinator.data if coordinator else None) or {}
    secrets = sensitive_values(dict(entry.data))

    described = {
        key: (
            f"dict[{len(value)}]"
            if key.startswith(COUNTED_ONLY) and isinstance(value, dict)
            else describe_shape(value)
        )
        for key, value in sorted(data.items())
        if key not in SAFE_FIELDS and key not in RAW_PAYLOADS
    }

    report = {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": bool(coordinator and coordinator.last_update_success),
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator and coordinator.update_interval
                else None
            ),
        },
        "counts": {field: data.get(field) for field in SAFE_FIELDS},
        # Types, never values: "bioage_total": "int" says the sensor has a
        # reading without saying what anybody's bio-age is.
        "field_types": described,
        "payload_shapes": {key: describe_shape(data.get(key)) for key in RAW_PAYLOADS},
    }
    return scrub(report, secrets)
