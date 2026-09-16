"""The polling floor is enforced where it cannot be talked around.

The options form has a minimum, but a form minimum is a hint to a browser.
Options written by an older version, or edited by hand in .storage, arrive at
setup without ever passing through it -- and a poller below the rate limit gets
the household's own address blocked, phone and eGym app included.
"""

from __future__ import annotations

import pytest
from conftest import load_entrypoint
from egym.const import DEFAULT_SCAN_INTERVAL, MIN_SCAN_INTERVAL

entrypoint = load_entrypoint()


class FakeEntry:
    def __init__(self, options):
        self.options = options


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, DEFAULT_SCAN_INTERVAL),
        (900, 900),
        (3600, 3600),
        # Below the floor, at the floor, and absurd.
        (1, MIN_SCAN_INTERVAL),
        (299, MIN_SCAN_INTERVAL),
        (300, 300),
        (0, MIN_SCAN_INTERVAL),
        (-60, MIN_SCAN_INTERVAL),
        # The options flow stores a number selector's value, which arrives as a
        # float, and hand-edited storage can hold a string.
        (600.0, 600),
        ("600", 600),
    ],
)
def test_the_floor_holds_whatever_the_entry_says(configured, expected):
    options = {} if configured is None else {"scan_interval": configured}
    assert entrypoint._scan_interval(FakeEntry(options)) == expected


@pytest.mark.parametrize("configured", [None, "", "fast", [], {}, object()])
def test_nonsense_falls_back_to_the_default_rather_than_to_zero(configured):
    assert entrypoint._scan_interval(FakeEntry({"scan_interval": configured})) == (
        DEFAULT_SCAN_INTERVAL
    )


def test_the_floor_is_not_higher_than_the_default():
    assert MIN_SCAN_INTERVAL <= DEFAULT_SCAN_INTERVAL
