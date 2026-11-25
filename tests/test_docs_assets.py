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


MODULE_TOKEN = re.compile(r"(?<![\w/])((?:[\w-]+/)*[\w-]+\.py|cogs/\*)")
THIRD_PARTY = {"discord.py"}  # named as a dependency, not a repository path


def test_the_architecture_figure_names_only_modules_that_exist():
    """A figure is an index. An index that points at a deleted file is worse than no index.

    `LANES` is hand-maintained, so the figure cannot notice a module that landed or left; a
    reader can. This is that reader, automated: every path the figure prints must resolve.
    """
    svg = (SVGS / "architecture.svg").read_text(encoding="utf-8")
    tokens = sorted(set(MODULE_TOKEN.findall(svg)))
    assert tokens, "the architecture figure names no modules"
    missing = [t for t in tokens if t not in THIRD_PARTY and not list(ROOT.glob(t))]
    assert missing == [], f"architecture.svg advertises paths that do not exist: {missing}"


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
