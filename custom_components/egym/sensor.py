"""Sensors for the unofficial eGym / Netpulse integration.

The coordinator already flattens the API payload (see api.py), so everything
here is a plain lookup. Response shapes were verified against a live member
account on 2026-09-12.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfLength,
    UnitOfMass,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BODY_VALUES, CONF_USERNAME, DEFAULT_BODY_VALUES, DOMAIN
from .entity import device_info_for

# Keys whose value is an ISO timestamp string and needs converting to a
# timezone-aware datetime before Home Assistant will accept it.
TIMESTAMP_KEYS = {"last_workout_date", "last_gym_workout_date"}

# eGym reports bio-age in whole years. Home Assistant does not translate units,
# and the dashboard is German, so spell it out rather than using the SI symbol
# "a" — nobody reads "57 a" as "57 Jahre".
YEARS = "Jahre"

# Values that are floats in the payload but meaningless past one decimal.
ROUNDED_TO_ONE_DECIMAL = {"bmi", "vo2max", "waist_to_hip_ratio"}

# Measurements of a body rather than of a training session. They are health
# data, and a sensor's history lives in the recorder database and in every
# backup taken of it, so there is a switch for them in the options -- see
# CONF_BODY_VALUES. Everything else here describes what somebody did, not what
# their body is.
BODY_VALUE_KEYS = frozenset(
    {
        "bioage_total",
        "bioage_cardio",
        "bioage_metabolic",
        "bioage_muscle",
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
    }
)


def _as_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


SENSOR_DESCRIPTIONS = (
    # --- Counts -------------------------------------------------------------
    SensorEntityDescription(
        key="workout_count",
        name="Workouts (30 days)",
        icon="mdi:dumbbell",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="gym_workout_count",
        name="Gym workouts (30 days)",
        icon="mdi:weight-lifter",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # Distinct calendar days, the count that is not inflated by eGym filing one
    # copy of every Garmin/Strava/Apple-Health activity.
    SensorEntityDescription(
        key="workout_days_30d",
        name="Active days (30 days)",
        icon="mdi:calendar-check",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="workout_days_7d",
        name="Active days (7 days)",
        icon="mdi:calendar-week",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="gym_workout_days_30d",
        name="Gym days (30 days)",
        icon="mdi:calendar-star",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="gym_workout_count_7d",
        name="Gym workouts (7 days)",
        icon="mdi:weight-lifter",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="workout_days_365d",
        name="Active days (12 months)",
        icon="mdi:calendar-month",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="gym_workout_days_365d",
        name="Gym days (12 months)",
        icon="mdi:calendar-month-outline",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="days_since_last_workout",
        name="Days since last workout",
        icon="mdi:timer-sand",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="days_since_last_gym_workout",
        name="Days since last gym workout",
        icon="mdi:timer-sand-complete",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # --- 30-day totals ------------------------------------------------------
    SensorEntityDescription(
        key="calories_30d",
        name="Calories (30 days)",
        icon="mdi:fire",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="points_30d",
        name="Activity points (30 days)",
        icon="mdi:star",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="points_7d",
        name="Activity points (7 days)",
        icon="mdi:star-outline",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="duration_30d",
        name="Training time (30 days)",
        icon="mdi:clock-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="distance_30d",
        name="Distance (30 days)",
        icon="mdi:map-marker-distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="gym_volume_30d",
        name="Training volume (30 days)",
        icon="mdi:weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # --- Last workout -------------------------------------------------------
    SensorEntityDescription(
        key="last_workout_date",
        name="Last workout",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="last_workout_name",
        name="Last workout type",
        icon="mdi:run",
    ),
    SensorEntityDescription(
        key="last_workout_calories",
        name="Last workout calories",
        icon="mdi:fire",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_workout_points",
        name="Last workout activity points",
        icon="mdi:star-outline",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_workout_duration",
        name="Last workout duration",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_workout_distance",
        name="Last workout distance",
        icon="mdi:map-marker-distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_workout_heart_rate",
        name="Last workout heart rate",
        icon="mdi:heart-pulse",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # --- Last gym workout ---------------------------------------------------
    SensorEntityDescription(
        key="last_gym_workout_date",
        name="Last gym workout",
        icon="mdi:calendar-check",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="last_gym_workout_duration",
        name="Last gym workout duration",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_gym_workout_calories",
        name="Last gym workout calories",
        icon="mdi:fire",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_gym_workout_points",
        name="Last gym workout activity points",
        icon="mdi:star-four-points-outline",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # reps x weight summed over every set — the number that says whether a gym
    # session was harder than the one before it.
    SensorEntityDescription(
        key="last_gym_workout_volume",
        name="Last gym workout volume",
        icon="mdi:weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_gym_workout_top_weight",
        name="Last gym workout top weight",
        icon="mdi:arm-flex",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # --- Bio-age ------------------------------------------------------------
    SensorEntityDescription(
        key="bioage_total",
        name="Bioage total",
        icon="mdi:account-heart",
        native_unit_of_measurement=YEARS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="bioage_cardio",
        name="Bioage cardio",
        icon="mdi:heart-pulse",
        native_unit_of_measurement=YEARS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="bioage_metabolic",
        name="Bioage metabolic",
        icon="mdi:scale-bathroom",
        native_unit_of_measurement=YEARS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="bioage_muscle",
        name="Bioage muscle",
        icon="mdi:arm-flex",
        native_unit_of_measurement=YEARS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="bioage_upper_body",
        name="Bioage upper body",
        icon="mdi:arm-flex-outline",
        native_unit_of_measurement=YEARS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="bioage_core",
        name="Bioage core",
        icon="mdi:human-handsup",
        native_unit_of_measurement=YEARS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="bioage_lower_body",
        name="Bioage lower body",
        icon="mdi:human-handsdown",
        native_unit_of_measurement=YEARS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # --- Body values --------------------------------------------------------
    SensorEntityDescription(
        key="body_fat",
        name="Body fat",
        icon="mdi:percent-outline",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="bmi",
        name="BMI",
        icon="mdi:human",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="vo2max",
        name="VO2max",
        icon="mdi:lungs",
        native_unit_of_measurement="mL/min/kg",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="resting_heart_rate",
        name="Resting heart rate",
        icon="mdi:heart",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # Stay "unknown" until the member types them into the eGym app. They exist
    # so the value appears by itself the day it is entered, rather than needing
    # a code change first.
    SensorEntityDescription(
        key="waist_to_hip_ratio",
        name="Waist to hip ratio",
        icon="mdi:tape-measure",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="blood_pressure_systolic",
        name="Blood pressure systolic",
        icon="mdi:heart-plus-outline",
        native_unit_of_measurement="mmHg",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="blood_pressure_diastolic",
        name="Blood pressure diastolic",
        icon="mdi:heart-minus-outline",
        native_unit_of_measurement="mmHg",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    username = entry.data[CONF_USERNAME]
    body_values = entry.options.get(CONF_BODY_VALUES, DEFAULT_BODY_VALUES)
    async_add_entities(
        EgymSensor(coordinator, username, description)
        for description in SENSOR_DESCRIPTIONS
        if body_values or description.key not in BODY_VALUE_KEYS
    )


def _attributes_for(key: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Extra detail that belongs with a sensor but does not deserve its own.

    Keys with an empty/None value are dropped so a card never shows a row of
    blanks on an account that has not produced that data yet.
    """
    if key == "workout_count":
        # Makes the triple-counting inspectable: the per-source breakdown shows
        # at a glance how much of the number is mirrored app data.
        extra = {
            "sources": data.get("sources_30d"),
            "activities": data.get("activities_30d"),
            "active_days": data.get("workout_days_30d"),
            "last_7_days": data.get("workout_count_7d"),
            "last_12_months": data.get("workout_count_365d"),
        }
    elif key == "gym_workout_count":
        extra = {
            "gym_days": data.get("gym_workout_days_30d"),
            "last_7_days": data.get("gym_workout_count_7d"),
            "last_12_months": data.get("gym_workout_count_365d"),
        }
    elif key == "last_workout_date":
        extra = {
            "type": data.get("last_workout_name"),
            "sources": data.get("last_workout_sources"),
            "duration_min": data.get("last_workout_duration"),
            "distance_km": data.get("last_workout_distance"),
        }
    elif key == "last_gym_workout_date":
        extra = {
            "exercises": data.get("last_gym_workout_exercises"),
            "sets": data.get("last_gym_workout_sets"),
            "volume_kg": data.get("last_gym_workout_volume"),
            "top_weight_kg": data.get("last_gym_workout_top_weight"),
        }
    elif key == "last_gym_workout_volume":
        extra = {"sets": data.get("last_gym_workout_sets")}
    elif key == "bioage_total":
        extra = {
            "measured_at": data.get("bioage_measured_at"),
            "hint": data.get("bioage_hint"),
        }
    elif key == "bioage_muscle":
        extra = {
            "upper_body": data.get("bioage_upper_body"),
            "core": data.get("bioage_core"),
            "lower_body": data.get("bioage_lower_body"),
        }
    elif key in ("bioage_upper_body", "bioage_core", "bioage_lower_body"):
        # IMBALANCED means the two sides of the body scored differently.
        region = key.removeprefix("bioage_")
        extra = {"muscles_state": data.get(f"muscles_state_{region}")}
    elif key == "body_fat":
        extra = {"measured_at": data.get("body_fat_measured_at")}
    elif key == "resting_heart_rate":
        extra = {"measured_at": data.get("resting_heart_rate_measured_at")}
    else:
        return None
    cleaned = {name: value for name, value in extra.items() if value not in (None, "", [], {})}
    return cleaned or None


class EgymSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: Any, username: str, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"egym_{username.casefold()}_{description.key}"
        self._attr_device_info = device_info_for(username)

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        key = self.entity_description.key
        value = data.get(key)
        if key in TIMESTAMP_KEYS:
            return _as_datetime(value)
        if key in ROUNDED_TO_ONE_DECIMAL and isinstance(value, float):
            return round(value, 1)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return _attributes_for(self.entity_description.key, self.coordinator.data or {})
