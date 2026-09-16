"""What leaves this module, and what must never leave it.

Exception messages raised here reach the Home Assistant log and, during setup,
the screen. The member id is in the path of every data request and the password
is in the body of the login, so both are checked against every message the
client can produce.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from egym.api import (
    BIOAGE_PATH_TEMPLATE,
    WORKOUTS_PATH_TEMPLATE,
    EgymApi,
    EgymApiError,
    EgymAuthError,
    EgymLoginRejected,
)

UID = "8f14e45f-ceea-467a-9c2b-7a1b2c3d4e5f"
PASSWORD = "correct-horse-battery-staple"
USERNAME = "member@example.com"


class FakeResponse:
    def __init__(self, status: int, payload=None, headers=None):
        self.status = status
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}

    async def json(self, content_type=None):
        return self._payload


class _Call:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Records what it was asked to do and answers with a canned response."""

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.requests: list[tuple[str, str, dict]] = []

    def _handle(self, method, url, kwargs):
        self.requests.append((method, url, kwargs))
        if self._raises is not None:
            raise self._raises
        return _Call(self._response)

    def get(self, url, **kwargs):
        return self._handle("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._handle("POST", url, kwargs)


def make_api(session, **kwargs):
    return EgymApi(session, "mygym", USERNAME, PASSWORD, **kwargs)


def test_a_rejected_session_does_not_name_the_member():
    session = FakeSession(FakeResponse(403))
    api = make_api(session)
    api._uid = UID
    url = f"{api.base_url}{WORKOUTS_PATH_TEMPLATE.format(uid=UID)}"

    with pytest.raises(EgymAuthError) as raised:
        asyncio.run(api._get(url))

    assert UID not in str(raised.value)
    assert "<member-id>" in str(raised.value)


def test_a_server_error_does_not_name_the_member_either():
    session = FakeSession(FakeResponse(500))
    api = make_api(session)
    api._uid = UID
    url = f"{api.base_url}{BIOAGE_PATH_TEMPLATE.format(uid=UID)}"

    with pytest.raises(EgymApiError) as raised:
        asyncio.run(api._get(url))

    assert UID not in str(raised.value)
    assert raised.value.status == 500


def test_a_network_error_does_not_name_the_member():
    session = FakeSession(raises=aiohttp.ClientError(f"cannot connect to host for {UID}"))
    api = make_api(session)
    api._uid = UID

    with pytest.raises(EgymApiError) as raised:
        asyncio.run(api._get(f"{api.base_url}{WORKOUTS_PATH_TEMPLATE.format(uid=UID)}"))

    assert UID not in str(raised.value)


def test_a_rejected_session_drops_the_session_it_was_holding():
    """Otherwise the next request goes out with a cookie known to be dead."""
    session = FakeSession(FakeResponse(401))
    api = make_api(session)
    api._uid = UID
    api._cookie = "JSESSIONID=stale"

    with pytest.raises(EgymAuthError):
        asyncio.run(api._get(f"{api.base_url}{WORKOUTS_PATH_TEMPLATE.format(uid=UID)}"))

    assert api._cookie is None
    assert api._uid is None


def test_every_request_carries_a_timeout():
    """Without one, a host that accepts the connection and then goes quiet
    holds the coordinator's update open forever and nothing is ever logged."""
    session = FakeSession(
        FakeResponse(200, {"uuid": UID, "workouts": []}, {"Set-Cookie": "JSESSIONID=abc"})
    )
    api = make_api(session)
    asyncio.run(api.async_login())
    asyncio.run(api._get(f"{api.base_url}{WORKOUTS_PATH_TEMPLATE.format(uid=UID)}"))

    assert session.requests
    for method, url, kwargs in session.requests:
        assert kwargs.get("timeout") is not None, f"{method} {url} has no timeout"


def test_a_refused_login_is_told_apart_from_an_expired_session():
    """EgymLoginRejected is what stops the polling and asks for a new password.

    A plain EgymAuthError only earns one silent login, which against a service
    that rate-limits failed logins is the difference between a prompt and a
    blocked address.
    """
    session = FakeSession(FakeResponse(401, {"message": "Required parameters are missing"}))
    api = make_api(session)

    with pytest.raises(EgymLoginRejected) as raised:
        asyncio.run(api.async_login())

    assert isinstance(raised.value, EgymAuthError)
    assert PASSWORD not in str(raised.value)
    assert USERNAME not in str(raised.value)


def test_a_failed_login_leaves_nothing_of_the_previous_session_behind():
    session = FakeSession(FakeResponse(403))
    api = make_api(session)
    api._uid, api._cookie, api._token, api._egym_id = UID, "JSESSIONID=old", "t", "e"

    with pytest.raises(EgymLoginRejected):
        asyncio.run(api.async_login())

    assert (api._uid, api._cookie, api._token, api._egym_id) == (None, None, None, None)


def test_the_login_is_form_encoded_and_goes_to_the_brand_host():
    """JSON is accepted and silently ignored, which answers 401 and reads like
    a wrong password."""
    session = FakeSession(
        FakeResponse(200, {"uuid": UID}, {"Set-Cookie": "JSESSIONID=abc; Path=/; HttpOnly"})
    )
    api = make_api(session)
    asyncio.run(api.async_login())

    method, url, kwargs = session.requests[0]
    assert method == "POST"
    assert url == "https://mygym.netpulse.com/np/exerciser/login"
    assert kwargs["data"] == {"username": USERNAME, "password": PASSWORD}
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert "json" not in kwargs
    # Only the cookie's value, not its Path/HttpOnly attributes.
    assert api._cookie == "JSESSIONID=abc"
    assert api._uid == UID


def test_the_body_values_switch_stops_the_bio_age_request_being_made():
    """Not creating the sensors would still leave health data in memory."""
    session = FakeSession(FakeResponse(200, {"workouts": []}))
    api = make_api(session, body_values=False)
    api._uid = UID
    asyncio.run(api.async_fetch_data())

    assert not any("bioage" in url for _method, url, _kwargs in session.requests)
    assert any("workouts" in url for _method, url, _kwargs in session.requests)
