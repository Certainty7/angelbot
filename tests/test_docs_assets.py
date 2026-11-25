"""Docs assets are generated, parseable, and actually referenced."""

from __future__ import annotations

import pathlib
import re
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
SVGS = ROOT / "docs/screenshots"
README_LINK = re.compile(r"docs/screenshots/([\w.-]+\.(?:svg|png))")


def test_every_shipped_svg_parses():
    files = sorted(SVGS.glob("*.svg"))
    assert files, "no SVG assets found"
    for path in files:
        # Local, generated, committed files: no external entities to resolve.
        ET.parse(path)  # raises on malformed XML


def test_the_figures_name_the_modules_they_claim():
    architecture = (SVGS / "architecture.svg").read_text(encoding="utf-8")
    for module in ("nl_router.py", "work_queue.py", "database.py", "media.py", "net.py", "confirmations.py"):
        assert module in architecture, module
    pipeline = (SVGS / "message-pipeline.svg").read_text(encoding="utf-8")
    assert "nl_router.py" in pipeline and "database.py" in pipeline
    assert "بوابة التأكيد" in pipeline


def test_the_gate_card_quotes_a_passing_run():
    gate = (SVGS / "deploy-gate.svg").read_text(encoding="utf-8")
    assert "checks passed" in gate
    assert "[FAIL]" not in gate


def test_readmes_only_reference_files_that_exist():
    for name in ("README.md", "README.ar.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        refs = set(README_LINK.findall(text))
        assert refs, f"{name} references no screenshot"
        for ref in refs:
            assert (SVGS / ref).is_file(), f"{name} points at missing {ref}"
            assert ref.endswith(".svg"), f"{name} still points at a stale raster {ref}"
