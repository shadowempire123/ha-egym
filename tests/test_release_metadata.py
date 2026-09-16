"""Version numbers that must agree, and the release notes that come from them.

Three files carry the version: manifest.json is what HACS reads, const.VERSION
goes into the User-Agent the Netpulse host sees, and CHANGELOG.md is what the
release workflow publishes. A mismatch between the first two ships a wrong
User-Agent; a missing changelog section fails the release after the tag has
already been pushed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "egym"
MANIFEST = json.loads((INTEGRATION / "manifest.json").read_text())

sys.path.insert(0, str(ROOT / "scripts"))
from changelog_section import section  # noqa: E402


def test_manifest_and_const_agree():
    from egym.const import VERSION

    assert MANIFEST["version"] == VERSION


def test_hacs_manifest_is_valid_json_with_a_name():
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["name"]
    assert "homeassistant" in hacs


@pytest.mark.parametrize("key", ["documentation", "issue_tracker"])
def test_manifest_links_point_at_the_repository(key):
    assert MANIFEST[key].startswith("https://github.com/")


def test_manifest_has_what_hassfest_and_hacs_require():
    for key in ("domain", "name", "version", "documentation", "issue_tracker", "codeowners"):
        assert MANIFEST.get(key), f"manifest.json is missing {key}"


def test_the_current_version_has_release_notes():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert section(changelog, MANIFEST["version"]).strip(), (
        "the release workflow would publish an empty release"
    )


def test_an_unknown_version_fails_loudly():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "changelog_section.py"), "99.0.0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


def test_the_translations_cover_every_string():
    """A missing key shows the raw identifier in the UI, which looks broken."""
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))

    def paths(node, prefix=()):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from paths(value, (*prefix, key))
        else:
            yield prefix

    expected = set(paths(strings))
    assert expected
    for name in ("en", "de"):
        translation = json.loads(
            (INTEGRATION / "translations" / f"{name}.json").read_text(encoding="utf-8")
        )
        assert set(paths(translation)) == expected, f"{name}.json does not match strings.json"


def png_size(path: Path) -> tuple[int, int]:
    """Width and height straight out of the PNG header.

    Read by hand rather than with Pillow: the images are generated once by a
    developer, and making the CI install an imaging library to measure four
    files would be the tail wagging the dog.
    """
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


@pytest.mark.parametrize(
    ("name", "size"),
    [("icon.png", 256), ("icon@2x.png", 512), ("logo.png", 256), ("logo@2x.png", 512)],
)
def test_the_brand_images_are_the_sizes_home_assistant_serves(name, size):
    assert png_size(INTEGRATION / "brand" / name) == (size, size)
