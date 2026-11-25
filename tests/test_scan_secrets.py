"""The scanner must catch a planted token and must not cry wolf on this repository."""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("scan", ROOT / "scripts/scan_secrets.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_catches_a_planted_discord_token():
    fake = "M" + "a" * 23 + "." + "b" * 6 + "." + "c" * 27
    hits = _module().scan([("fixture.py", f'TOKEN = "{fake}"'.encode())])
    assert len(hits) == 1 and hits[0].startswith("discord-token:fixture.py")


def test_it_ignores_a_base64_run_of_letters():
    blob = b"AKIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    assert _module().scan([("report.json", blob)]) == []


def test_it_accepts_a_placeholder():
    hits = _module().scan([("x.py", b'TOKEN = os.environ["DISCORD_TOKEN"]')])
    assert hits == []


def test_it_catches_a_token_that_a_later_commit_deleted(tmp_path):
    """History means history: the file's *current* content is not the thing being scanned."""
    repo = tmp_path / "history"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(git[:3] + ["init", "-q"], check=True, capture_output=True)
    fake = "M" + "a" * 23 + "." + "b" * 6 + "." + "c" * 27
    (repo / "config.py").write_text(f'TOKEN = "{fake}"\n', encoding="utf-8")
    subprocess.run(git + ["add", "."], check=True, capture_output=True)
    subprocess.run(git + ["commit", "-qm", "add token"], check=True, capture_output=True)
    (repo / "config.py").write_text("TOKEN = os.environ['DISCORD_TOKEN']\n", encoding="utf-8")
    subprocess.run(git + ["commit", "-qam", "remove token"], check=True, capture_output=True)

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/scan_secrets.py")],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, f"a deleted secret went unseen: {result.stdout!r}"
    assert "discord-token:config.py" in result.stdout


def test_this_repository_is_clean():
    result = subprocess.run(
        [sys.executable, "scripts/scan_secrets.py"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout
