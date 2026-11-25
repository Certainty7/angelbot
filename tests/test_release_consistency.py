"""A release number lives in one place and is copied by machines, not by hand."""

from __future__ import annotations

import json
import pathlib
import re

from angel import __version__

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _top_changelog_version() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## (\d+\.\d+\.\d+)", text, re.MULTILINE)
    assert match, "CHANGELOG.md has no '## <version>' heading"
    return match.group(1)


def test_version_agrees_across_code_changelog_and_site():
    assert _top_changelog_version() == __version__
    site = json.loads((ROOT / "website/src/data/site.json").read_text(encoding="utf-8"))
    assert site["version"] == __version__


def test_readmes_advertise_the_current_release():
    for name in ("README.md", "README.ar.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        badges = re.findall(r"badge/release-v(\d+\.\d+\.\d+)", text)
        assert badges == [__version__], f"{name} badge says {badges}"


def test_readmes_do_not_hardcode_suite_counts():
    for name in ("README.md", "README.ar.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"\b\d{3}\s+(?:tests?|اختبار)", text), (
            f"{name} repeats a suite count that will go stale; point at CI instead"
        )
