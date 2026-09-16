"""How the coordinator reacts to being turned away.

The distinction it draws is the one that keeps the user's address off eGym's
block list: an expired session is worth one silent login, a refused login is
not worth repeating every quarter of an hour forever.
"""

from __future__ import annotations

import asyncio

import pytest
from egym.api import EgymApiError, EgymAuthError, EgymLoginRejected
from egym.coordinator import EgymCoordinator
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

DATA = {"workout_count": 7}


class FakeApi:
    """Answers with a scripted sequence and counts the logins it was asked for."""

    def __init__(self, *results):
        self._results = list(results)
        self.logins = 0
        self.login_error: Exception | None = None

    async def async_fetch_data(self):
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def async_login(self):
        self.logins += 1
        if self.login_error is not None:
            raise self.login_error


def update(api):
    return asyncio.run(EgymCoordinator(None, api)._async_update_data())


def test_the_ordinary_case_asks_for_nothing_extra():
    api = FakeApi(DATA)
    assert update(api) == DATA
    assert api.logins == 0


def test_an_expired_session_is_worth_exactly_one_login():
    api = FakeApi(EgymAuthError("session gone"), DATA)
    assert update(api) == DATA
    assert api.logins == 1


def test_a_refused_login_asks_the_user_instead_of_trying_again():
    api = FakeApi(EgymAuthError("session gone"))
    api.login_error = EgymLoginRejected("eGym refused this combination")

    with pytest.raises(ConfigEntryAuthFailed):
        update(api)

    # One attempt, not a retry loop: Home Assistant stops polling from here and
    # shows a re-authentication prompt.
    assert api.logins == 1


def test_credentials_refused_on_the_very_first_call_go_straight_to_reauth():
    api = FakeApi(EgymLoginRejected("eGym refused this combination"))

    with pytest.raises(ConfigEntryAuthFailed):
        update(api)

    assert api.logins == 0


def test_a_session_that_bounces_even_after_a_fresh_login_waits_for_next_time():
    """Not ConfigEntryAuthFailed: the password was accepted, so asking the user
    for a new one would be asking the wrong question."""
    api = FakeApi(EgymAuthError("session gone"), EgymAuthError("still refused"))

    with pytest.raises(UpdateFailed):
        update(api)

    assert api.logins == 1


def test_an_ordinary_api_failure_is_just_a_failed_update():
    with pytest.raises(UpdateFailed):
        update(FakeApi(EgymApiError("eGym answered HTTP 502")))


def test_the_polling_interval_is_what_it_was_given():
    coordinator = EgymCoordinator(None, FakeApi(DATA), 1800)
    assert coordinator.update_interval.total_seconds() == 1800
