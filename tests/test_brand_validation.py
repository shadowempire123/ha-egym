"""The brand decides which host receives the member's password.

``EgymApi`` builds ``https://<brand>.netpulse.com`` and posts the username and
password to it. Every string below that gets through the validator and still
changes the hostname is a credential leak, so this file is written as an allow
list check rather than a list of tricks somebody thought of.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from egym.api import EgymApi, EgymBrandError, normalize_brand

ACCEPTED = [
    ("mygym", "mygym"),
    ("cityfitness", "cityfitness"),
    ("a", "a"),
    ("gym-1", "gym-1"),
    # Case and surrounding whitespace are a typo, not an attack.
    ("MyGym", "mygym"),
    ("  MYGYM  ", "mygym"),
    ("a" * 63, "a" * 63),
]

REJECTED = [
    "",
    " ",
    # The full host instead of the label: the common honest mistake.
    "mygym.netpulse.com",
    # Everything below moves the hostname somewhere else.
    "evil.com#",
    "evil.com?",
    "user@evil.com",
    "attacker.example/x",
    "mygym.evil.com",
    "mygym:8080",
    "mygym\\evil",
    "mygym/../evil",
    "//evil.com",
    "mygym%2eevil.com",
    "mygym\nevil",
    "mygym evil",
    "mygym\tevil",
    # Underscores are not valid in a DNS label and are not needed here.
    "my_gym",
    # A hyphen may not start or end a label.
    "-mygym",
    "mygym-",
    # Longer than a DNS label may be.
    "a" * 64,
    # Look-alikes: a Cyrillic letter where the ASCII one is expected, and
    # an umlaut. Both render close enough to fool a reader and resolve
    # somewhere else entirely. Written as escapes on purpose -- the source
    # of a test about confusable characters should not itself contain any.
    "myg\u0443m",
    "\u00fcbergym",
]


@pytest.mark.parametrize(("raw", "expected"), ACCEPTED)
def test_a_plain_dns_label_is_accepted(raw, expected):
    assert normalize_brand(raw) == expected


@pytest.mark.parametrize("raw", REJECTED)
def test_anything_that_is_not_a_dns_label_is_refused(raw):
    with pytest.raises(EgymBrandError):
        normalize_brand(raw)


@pytest.mark.parametrize(("raw", "expected"), ACCEPTED)
def test_the_password_only_ever_goes_to_netpulse(raw, expected):
    api = EgymApi(object(), raw, "member@example.com", "hunter2")
    host = urlsplit(api.base_url).hostname
    assert host == f"{expected}.netpulse.com"
    assert host.endswith(".netpulse.com")


@pytest.mark.parametrize("raw", REJECTED)
def test_the_api_refuses_to_be_built_with_a_bad_brand(raw):
    """Checked in the client, not only in the config flow.

    A config entry written by an older version, or edited by hand in .storage,
    reaches this constructor without passing through the config flow at all.
    """
    with pytest.raises(EgymBrandError):
        EgymApi(object(), raw, "member@example.com", "hunter2")
