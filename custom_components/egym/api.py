"""Thin async client for the unofficial eGym / Netpulse member API.

This talks to UNDOCUMENTED, reverse-engineered endpoints — there is no official
eGym API. Endpoint paths below come from public community write-ups
(see docs/API.md for sources and the full disclaimer).

Verified against a real member account on 2026-09-12, with live workout and
bio-age data:

- The login needs form encoding, not JSON, and answers with a `JSESSIONID`
  cookie. The member id arrives as `uuid`.
- That session cookie alone is enough for both the workout and the bio-age
  service. No `externalAuthToken` is needed — it stays `null` on a perfectly
  working account, so its absence must not be treated as an error.
- `completedAfter`/`completedBefore` must be `%Y-%m-%dT%H:%M:%SZ`. Every other
  spelling (`+00:00`, `+0000`, millisecond precision, date-only, epoch) is
  rejected with HTTP 400 `{"errors": {"completedBefore": "wrongFormat"}}`.
- Bio-age lives on the brand host, not on `mobile-api.int.api.egym.com`, and is
  addressed by the Netpulse `uuid` — using `egymAccountId` answers 403.
- Workouts come back newest first, and the date range is not capped at 30 days:
  a 400-day window answers fine, so one request covers every rolling window.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import aiohttp
import homeassistant.util.dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import VERSION

LOGIN_PATH = "/np/exerciser/login"
WORKOUTS_PATH_TEMPLATE = "/workouts/api/workouts/v2.3/exercisers/{uid}/workouts"
BIOAGE_PATH_TEMPLATE = "/analysis/api/v1.0/exercisers/{uid}/bioage"
# Workouts that were actually recorded on a gym machine, as opposed to the
# Garmin/Strava/Apple-Health copies eGym mirrors into the same feed.
FITNESS_MACHINE_SOURCE = "fitness_machine"
# One request covers every window we report on. The API happily answers a
# 400-day range, so there is no reason to ask for 30 days and throw the rest
# of the member's history away.
HISTORY_DAYS = 365
# Rolling windows, in days, that get their own sensors.
WINDOWS = (7, 30, 365)
# Strength sets arrive under this single, very long attribute name.
SETS_ATTRIBUTE = "sets_of_reps_and_weight_or_duration_and_weight"

USER_AGENT = f"HomeAssistant-egym-integration/{VERSION}"

# Nothing here is worth waiting on forever. Without a timeout a Netpulse host
# that accepts the connection and then goes quiet holds the coordinator's
# update open indefinitely, and the integration stops reporting without ever
# logging a failure.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# A brand is a DNS label, and the only sane way to check one is an allow list
# of what a label may contain -- never a deny list of the tricks that have been
# thought of. See normalize_brand() for why this one matters more than it
# looks.
BRAND_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

# Stands in for the member id in anything that may reach a log or the UI.
REDACTED = "<member-id>"

# Netpulse returns the member id as `uuid`; the eGym side of the account uses a
# separate `egymAccountId`. Order matters — the first hit wins.
UID_KEYS = ("uuid", "exerciseruuid", "uid", "exerciserid", "id", "userid", "memberid")
EGYM_ID_KEYS = ("egymaccountid", "egymuserid")
# Optional. Observed as `null` on a fully working, data-carrying account, so
# this is kept only as an extra header when a brand does hand one out.
TOKEN_KEYS = ("externalauthtoken", "externalidtoken")


def async_egym_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    """A client session that never stores cookies.

    Netpulse rejects a login request that already carries a `JSESSIONID` with
    HTTP 403 "Access to the specified resource has been forbidden." Home
    Assistant's shared session keeps a cookie jar, so the cookie from the config
    flow's login would be replayed into the next login and break setup — with a
    403 that reads like wrong credentials. This client discards cookies; the
    session cookie is tracked by hand in EgymApi and sent as an explicit header.
    """
    return async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar())


class EgymApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class EgymAuthError(EgymApiError):
    """The session was not accepted. Usually expired, sometimes wrong."""


class EgymLoginRejected(EgymAuthError):
    """A *fresh* login with the stored credentials was refused.

    Kept apart from EgymAuthError on purpose. An expired session is worth one
    silent login; a refused login is not worth repeating every quarter of an
    hour until the address is blocked, so the coordinator turns this one into a
    re-authentication prompt instead.
    """


class EgymBrandError(ValueError):
    """The brand is not a plain DNS label."""


def normalize_brand(value: str) -> str:
    """Validate a brand and return it as a bare, lower-case DNS label.

    This is the one piece of user input that decides *where the password goes*:
    the brand is interpolated into ``https://<brand>.netpulse.com``, and the
    login posts the member's username and password to that host. A brand of
    ``evil.com#``, ``attacker.example/x`` or ``user@evil.com`` moves the host
    somewhere else, and the credentials go with it.

    So the check is an allow list of the characters a DNS label may contain,
    not a deny list of the tricks anybody happened to think of. The earlier
    version rejected ``.`` and ``/`` and let ``@``, ``:``, ``#``, a backslash,
    ``?``, whitespace and every non-ASCII look-alike straight through.
    """
    brand = value.strip().lower()
    if not BRAND_PATTERN.match(brand):
        raise EgymBrandError(
            "A brand is the bare Netpulse subdomain: lower-case letters, digits "
            "and hyphens only, e.g. 'mygym' for mygym.netpulse.com"
        )
    return brand


def _first_value(value: Any, names: set[str]) -> Any:
    """Recursively search a parsed JSON structure for the first matching key."""
    if isinstance(value, dict):
        for name, candidate in value.items():
            if name.lower() in names and candidate not in (None, ""):
                return candidate
        for candidate in value.values():
            found = _first_value(candidate, names)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for candidate in value:
            found = _first_value(candidate, names)
            if found not in (None, ""):
                return found
    return None


def _ordered_value(data: Any, names: tuple[str, ...]) -> Any:
    """Look up keys in priority order, then fall back to a recursive search."""
    if isinstance(data, dict):
        lowered = {key.lower(): value for key, value in data.items()}
        for name in names:
            value = lowered.get(name)
            if value not in (None, ""):
                return value
    return _first_value(data, set(names))


def _rfc3339(moment: datetime) -> str:
    # Netpulse accepts exactly this spelling; "+00:00", "+0000", millisecond
    # precision, date-only and epoch values all answer HTTP 400 "wrongFormat".
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _completed_at_raw(workout: Any) -> str | None:
    if isinstance(workout, dict):
        value = workout.get("completedAt") or workout.get("createdAt")
        if value:
            return str(value)
    return None


def _completed_at(workout: Any) -> datetime:
    """Sort key. Unparseable or missing timestamps sort last, never crash."""
    raw = _completed_at_raw(workout)
    if not raw:
        return datetime.min.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def _exercises(workout: Any) -> list[dict[str, Any]]:
    if not isinstance(workout, dict):
        return []
    return [item for item in workout.get("exercises") or [] if isinstance(item, dict)]


def _is_gym_workout(workout: Any) -> bool:
    """True if any exercise was recorded on a gym machine rather than mirrored
    in from a connected app (Garmin, Strava, Apple Health)."""
    return any(
        (exercise.get("source") or {}).get("code") == FITNESS_MACHINE_SOURCE
        for exercise in _exercises(workout)
    )


def _sum_attribute(workout: Any, attribute: str) -> int | float | None:
    """Sum one numeric attribute across a workout's exercises.

    Values sit at exercises[].attributes.<name>.value. Returns None rather than
    0 when no exercise carries the attribute, so the sensor shows "unknown"
    instead of a misleading zero.
    """
    total: int | float = 0
    found = False
    for exercise in _exercises(workout):
        entry = (exercise.get("attributes") or {}).get(attribute)
        value = entry.get("value") if isinstance(entry, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += value
            found = True
    if not found:
        return None
    return round(total, 2) if isinstance(total, float) else total


def _exercise_names(workout: Any) -> list[str]:
    return [str(exercise["name"]) for exercise in _exercises(workout) if exercise.get("name")]


def _bioage_field(bioage: Any, section: str, metric: str, field: str) -> Any:
    """Read bioage.<section>.<metric>.<field>; every level can legitimately be
    null (e.g. flexibilityDetails on an account without a mobility test)."""
    if not isinstance(bioage, dict):
        return None
    details = bioage.get(section)
    if not isinstance(details, dict):
        return None
    entry = details.get(metric)
    if not isinstance(entry, dict):
        return None
    return entry.get(field)


def _bioage_value(bioage: Any, section: str, metric: str) -> Any:
    return _bioage_field(bioage, section, metric, "value")


def _local_date(workout: Any) -> date | None:
    """Calendar day a workout belongs to, in Home Assistant's local timezone.

    Counting distinct days is the honest alternative to counting workouts: eGym
    mirrors Garmin, Strava and Apple Health into the same feed and files one
    workout per connected app, so a single bike ride shows up three times.
    """
    raw = _completed_at_raw(workout)
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt_util.as_local(moment).date()


def _within(workouts: list[Any], days: int, now: datetime) -> list[Any]:
    cutoff = now - timedelta(days=days)
    return [w for w in workouts if _completed_at(w) >= cutoff]


def _distinct_days(workouts: list[Any]) -> int:
    return len({day for day in (_local_date(w) for w in workouts) if day})


def _sum_many(workouts: list[Any], attribute: str) -> int | float | None:
    """Sum one attribute across many workouts, None when nothing carries it."""
    total: int | float = 0
    found = False
    for workout in workouts:
        value = _sum_attribute(workout, attribute)
        if value is not None:
            total += value
            found = True
    if not found:
        return None
    return round(total, 2) if isinstance(total, float) else total


def _sets(exercise: Any) -> list[dict[str, Any]]:
    if not isinstance(exercise, dict):
        return []
    entry = (exercise.get("attributes") or {}).get(SETS_ATTRIBUTE)
    return [item for item in entry or [] if isinstance(item, dict)] if isinstance(entry, list) else []


def _set_value(entry: Any, field: str) -> int | float | None:
    value = (entry.get(field) or {}).get("value") if isinstance(entry, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _volume(workout: Any) -> float | None:
    """Training volume in kg: sum of reps x weight over every strength set.

    The single number that says whether a gym session was harder than the last
    one. None when the workout holds no strength sets at all (a pure cardio
    session), so the sensor reads "unknown" instead of a misleading 0 kg.
    """
    total = 0.0
    found = False
    for exercise in _exercises(workout):
        for entry in _sets(exercise):
            reps = _set_value(entry, "reps")
            weight = _set_value(entry, "weight")
            if reps is not None and weight is not None:
                total += reps * weight
                found = True
    return round(total, 1) if found else None


def _top_weight(workout: Any) -> float | None:
    """Heaviest weight moved in a workout, across all machines."""
    weights = [
        weight
        for exercise in _exercises(workout)
        for entry in _sets(exercise)
        if (weight := _set_value(entry, "weight")) is not None
    ]
    return max(weights) if weights else None


def _average_attribute(workout: Any, attribute: str) -> int | float | None:
    """Mean of a per-exercise average (heart rate), weighted by nothing.

    Workouts almost always hold a single exercise, so a plain mean is accurate
    enough and avoids inventing a weighting the API does not support.
    """
    values = [
        value
        for exercise in _exercises(workout)
        if isinstance(
            value := ((exercise.get("attributes") or {}).get(attribute) or {}).get("value"),
            (int, float),
        )
        and not isinstance(value, bool)
    ]
    return round(sum(values) / len(values)) if values else None


def _source_labels(workout: Any) -> list[str]:
    return [
        str(label)
        for exercise in _exercises(workout)
        if (label := (exercise.get("source") or {}).get("label"))
    ]


def _source_breakdown(workouts: list[Any]) -> dict[str, int]:
    """How many workouts came from each source, e.g. {"Garmin": 16, ...}.

    Makes the triple-counting visible right on the sensor instead of leaving it
    as a footnote on the dashboard.
    """
    counts: dict[str, int] = {}
    for workout in workouts:
        for label in dict.fromkeys(_source_labels(workout)):
            counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def _activity_breakdown(workouts: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for workout in workouts:
        for name in dict.fromkeys(_exercise_names(workout)):
            counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def _days_since(workout: Any, now: datetime) -> int | None:
    if not _completed_at_raw(workout):
        return None
    return max((now - _completed_at(workout)).days, 0)


def _minutes(seconds: int | float | None) -> int | None:
    return round(seconds / 60) if isinstance(seconds, (int, float)) else None


def _hours(seconds: int | float | None) -> float | None:
    return round(seconds / 3600, 1) if isinstance(seconds, (int, float)) else None


def _sets_summary(workout: Any) -> list[dict[str, Any]]:
    """Per-machine sets of the last gym workout, for the sensor attributes."""
    summary: list[dict[str, Any]] = []
    for exercise in _exercises(workout):
        entries = _sets(exercise)
        if not entries:
            continue
        summary.append(
            {
                "name": exercise.get("name"),
                "sets": len(entries),
                "reps": [_set_value(entry, "reps") for entry in entries],
                "weight_kg": [_set_value(entry, "weight") for entry in entries],
            }
        )
    return summary


class EgymApi:
    """Async client for the unofficial eGym/Netpulse member API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        brand: str,
        username: str,
        password: str,
        *,
        body_values: bool = True,
    ) -> None:
        self._session = session
        # When the body values are switched off, the bio-age service is not
        # asked at all. Fetching health data and then only declining to build
        # sensors from it would leave it sitting in memory and in anything that
        # inspects the coordinator -- not requesting it is the honest reading
        # of the switch.
        self._body_values = body_values
        # Validated here as well as in the config flow: an entry written by an
        # older version, or edited by hand in .storage, must not be able to
        # aim the login at another host.
        self._brand = normalize_brand(brand)
        self._username = username
        self._password = password
        self._uid: str | None = None
        self._egym_id: str | None = None
        self._cookie: str | None = None
        self._token: str | None = None

    @property
    def base_url(self) -> str:
        return f"https://{self._brand}.netpulse.com"

    def _headers(self, *, token: bool = False) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie
        if token and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _redact(self, text: str) -> str:
        """Strip the member id out of anything that may reach a log or the UI.

        Every data request carries the member id in its path, and the messages
        raised below are shown in the Home Assistant log and, during setup, on
        screen. That id is the handle the API addresses the account by, so it
        does not belong in either.
        """
        for secret in (self._uid, self._egym_id):
            if secret:
                text = text.replace(str(secret), REDACTED)
        return text

    async def _json(self, response: aiohttp.ClientResponse) -> Any:
        try:
            return await response.json(content_type=None)
        except ValueError as error:
            raise EgymApiError("eGym returned a non-JSON response") from error

    async def async_login(self) -> None:
        # Netpulse expects form encoding here. Sending JSON is accepted by the
        # server but silently ignored, which answers HTTP 401 with
        # {"message": "Required parameters are missing"} — verified 2026-09-11.
        url = f"{self.base_url}{LOGIN_PATH}"
        payload = {"username": self._username, "password": self._password}
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # Drop whatever is left of an earlier session before asking for a new
        # one. If the login fails the old cookie and member id would otherwise
        # stay behind, and the next request would go out looking like it still
        # had a working session.
        self._uid = self._egym_id = self._cookie = self._token = None
        try:
            async with self._session.post(
                url, data=payload, headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status in (401, 403):
                    raise EgymLoginRejected(
                        "eGym refused this brand, username and password combination",
                        status=response.status,
                    )
                if response.status >= 400:
                    raise EgymApiError(
                        f"eGym login failed with HTTP {response.status}", status=response.status
                    )
                data = await self._json(response)
                # aiohttp's headers are case-insensitive, which matters: Netpulse
                # spells this one `set-cookie` in lower case.
                raw_cookie = response.headers.get("Set-Cookie")
        except (aiohttp.ClientError, TimeoutError) as error:
            # The message of a connection error repeats the URL, and the URL
            # holds the brand but never a credential -- the password is in the
            # body. Still wrapped, so a network hiccup arrives as this module's
            # own error rather than as an unexpected exception in the log.
            raise EgymApiError(f"Could not reach {self.base_url}: {error}") from error
        uid = _ordered_value(data, UID_KEYS)
        if not uid:
            raise EgymApiError("eGym login succeeded but no exerciser id was found in the response")
        self._uid = str(uid)
        egym_id = _ordered_value(data, EGYM_ID_KEYS)
        self._egym_id = str(egym_id) if egym_id else None
        token = _ordered_value(data, TOKEN_KEYS)
        self._token = str(token) if token else None
        self._cookie = raw_cookie.split(";")[0] if raw_cookie else None

    async def _get(self, url: str, *, token: bool = False) -> Any:
        try:
            async with self._session.get(
                url, headers=self._headers(token=token), timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status in (401, 403):
                    # Redact before clearing, not after: _redact() works off
                    # the very ids being dropped here, so the other order
                    # would put the member id straight into the log.
                    message = self._redact(f"eGym rejected the session for {url}")
                    # The session is gone, not necessarily the credentials --
                    # EgymLoginRejected is what says the password is wrong.
                    self._cookie = self._uid = None
                    raise EgymAuthError(message, status=response.status)
                if response.status >= 400:
                    raise EgymApiError(
                        self._redact(f"eGym answered HTTP {response.status} for {url}"),
                        status=response.status,
                    )
                return await self._json(response)
        except (aiohttp.ClientError, TimeoutError) as error:
            raise EgymApiError(self._redact(f"Could not reach {url}: {error}")) from error

    async def async_fetch_data(self) -> dict[str, Any]:
        if not self._uid:
            await self.async_login()

        now = datetime.now(UTC)
        workouts_url = (
            f"{self.base_url}{WORKOUTS_PATH_TEMPLATE.format(uid=self._uid)}"
            f"?completedAfter={_rfc3339(now - timedelta(days=HISTORY_DAYS))}"
            f"&completedBefore={_rfc3339(now)}"
        )
        workouts = await self._get(workouts_url)
        if isinstance(workouts, list):
            workout_list = workouts
        elif isinstance(workouts, dict):
            workout_list = workouts.get("workouts") or workouts.get("data") or workouts.get("result") or []
        else:
            workout_list = []
        # Documented as newest-first, but sort anyway so "latest" cannot silently
        # turn into "oldest" if that ever changes.
        workout_list = sorted(workout_list, key=_completed_at, reverse=True)
        gym_workouts = [w for w in workout_list if _is_gym_workout(w)]

        latest_workout = workout_list[0] if workout_list else None
        latest_gym_workout = gym_workouts[0] if gym_workouts else None

        bioage: dict[str, Any] | None = None
        if self._body_values:
            try:
                # Same host and same uuid as the workout service — the eGym-side
                # `egymAccountId` is rejected with 403 here.
                bioage = await self._get(
                    f"{self.base_url}{BIOAGE_PATH_TEMPLATE.format(uid=self._uid)}"
                )
            except EgymAuthError:
                # A rejected session has to reach the coordinator: swallowing it
                # here would hide the one error that triggers a re-login.
                raise
            except EgymApiError:
                # Not every brand exposes bio-age; degrade instead of failing the
                # whole update, the workout sensors are the more important half.
                bioage = None

        data: dict[str, Any] = {
            "latest_workout": latest_workout,
            "latest_gym_workout": latest_gym_workout,
            "history_days": HISTORY_DAYS,
            "history_total": len(workout_list),
            "history_gym_total": len(gym_workouts),
            "last_workout_date": _completed_at_raw(latest_workout),
            "last_workout_name": ", ".join(_exercise_names(latest_workout)) or None,
            "last_workout_sources": ", ".join(dict.fromkeys(_source_labels(latest_workout))) or None,
            "last_workout_calories": _sum_attribute(latest_workout, "calories"),
            "last_workout_points": _sum_attribute(latest_workout, "activity_points"),
            "last_workout_duration": _minutes(_sum_attribute(latest_workout, "duration")),
            "last_workout_distance": _sum_attribute(latest_workout, "distance"),
            "last_workout_heart_rate": _average_attribute(latest_workout, "average_heart_rate"),
            "days_since_last_workout": _days_since(latest_workout, now),
            "last_gym_workout_date": _completed_at_raw(latest_gym_workout),
            "last_gym_workout_exercises": _exercise_names(latest_gym_workout),
            "last_gym_workout_sets": _sets_summary(latest_gym_workout),
            "last_gym_workout_calories": _sum_attribute(latest_gym_workout, "calories"),
            "last_gym_workout_points": _sum_attribute(latest_gym_workout, "activity_points"),
            "last_gym_workout_duration": _minutes(_sum_attribute(latest_gym_workout, "duration")),
            "last_gym_workout_volume": _volume(latest_gym_workout),
            "last_gym_workout_top_weight": _top_weight(latest_gym_workout),
            "days_since_last_gym_workout": _days_since(latest_gym_workout, now),
            "bioage": bioage,
            "bioage_total": _bioage_value(bioage, "totalDetails", "totalBioAge"),
            "bioage_cardio": _bioage_value(bioage, "cardioDetails", "cardioAge"),
            "bioage_metabolic": _bioage_value(bioage, "metabolicDetails", "metabolicAge"),
            "bioage_muscle": _bioage_value(bioage, "muscleDetails", "muscleBioAge"),
            # The three regions behind the muscle score. `musclesState` flags an
            # imbalance between the two sides of the body and is carried along as
            # a sensor attribute.
            "bioage_upper_body": _bioage_value(bioage, "muscleDetails", "upperBodyAge"),
            "bioage_core": _bioage_value(bioage, "muscleDetails", "coreAge"),
            "bioage_lower_body": _bioage_value(bioage, "muscleDetails", "lowerBodyAge"),
            "muscles_state_upper_body": _bioage_field(bioage, "muscleDetails", "upperBodyAge", "musclesState"),
            "muscles_state_core": _bioage_field(bioage, "muscleDetails", "coreAge", "musclesState"),
            "muscles_state_lower_body": _bioage_field(bioage, "muscleDetails", "lowerBodyAge", "musclesState"),
            "bioage_measured_at": _bioage_field(bioage, "totalDetails", "totalBioAge", "createdAt"),
            "body_fat": _bioage_value(bioage, "metabolicDetails", "bodyFat"),
            "body_fat_measured_at": _bioage_field(bioage, "metabolicDetails", "bodyFat", "createdAt"),
            "bmi": _bioage_value(bioage, "metabolicDetails", "bmi"),
            "vo2max": _bioage_value(bioage, "cardioDetails", "vo2max"),
            "resting_heart_rate": _bioage_value(bioage, "cardioDetails", "restingHeartRate"),
            "resting_heart_rate_measured_at": _bioage_field(
                bioage, "cardioDetails", "restingHeartRate", "createdAt"
            ),
            # Null until the member enters them in the eGym app. Kept as keys so
            # the sensors exist and fill themselves in the day a value shows up.
            "waist_to_hip_ratio": _bioage_value(bioage, "metabolicDetails", "waistToHipRatio"),
            "blood_pressure_systolic": _bioage_value(bioage, "cardioDetails", "systolicPressure"),
            "blood_pressure_diastolic": _bioage_value(bioage, "cardioDetails", "diastolicPressure"),
            # eGym's own nudge ("add your waist-hip ratio ..."), which is the only
            # hint the API gives about what is still missing.
            "bioage_hint": _bioage_field(bioage, "totalDetails", "quote", "text"),
        }

        for days in WINDOWS:
            window = _within(workout_list, days, now)
            gym_window = [w for w in window if _is_gym_workout(w)]
            suffix = f"_{days}d"
            data[f"workout_count{suffix}"] = len(window)
            data[f"gym_workout_count{suffix}"] = len(gym_window)
            # Distinct days, not workout rows — see _local_date.
            data[f"workout_days{suffix}"] = _distinct_days(window)
            data[f"gym_workout_days{suffix}"] = _distinct_days(gym_window)
            data[f"calories{suffix}"] = _sum_many(window, "calories")
            data[f"points{suffix}"] = _sum_many(window, "activity_points")
            data[f"duration{suffix}"] = _hours(_sum_many(window, "duration"))
            data[f"distance{suffix}"] = _sum_many(window, "distance")
            data[f"gym_volume{suffix}"] = (
                round(sum(volume for w in gym_window if (volume := _volume(w)) is not None), 1)
                if any(_volume(w) is not None for w in gym_window)
                else None
            )
            data[f"sources{suffix}"] = _source_breakdown(window)
            data[f"activities{suffix}"] = _activity_breakdown(window)

        # Names the original sensors already use, kept so their entity ids and
        # recorded history survive the switch to windowed keys.
        data["workout_count"] = data["workout_count_30d"]
        data["gym_workout_count"] = data["gym_workout_count_30d"]
        return data
