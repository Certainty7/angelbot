"""Configuration validation and time handling (C-009, C-032, P-008).

The module-level checks run at import, so the invalid cases execute in a subprocess.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run_python(code: str, **env_overrides):
    env = dict(os.environ)
    env.update({
        "ANGEL_DB_PATH": os.path.join(tempfile.gettempdir(), "angel-cfg-test.db"),
        "ANGEL_OWNER_ID": "42",
        "ANGEL_AUTO_INSTALL": "0",
        "PYTHONPATH": str(REPO),
        "PYTHONIOENCODING": "utf-8",
    })
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


class OwnerIdValidationTest(unittest.TestCase):
    """C-032: a zero or non-ASCII owner id must fail loudly, not lock the owner out."""

    def test_zero_is_rejected(self):
        result = run_python("import angel.config", ANGEL_OWNER_ID="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("positive numeric Discord user id", result.stderr + result.stdout)

    def test_superscript_is_rejected_without_valueerror(self):
        result = run_python("import angel.config", ANGEL_OWNER_ID="\u00b2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("positive numeric Discord user id", result.stderr + result.stdout)
        self.assertNotIn("ValueError", result.stderr)

    def test_arabic_indic_digits_are_rejected(self):
        result = run_python("import angel.config", ANGEL_OWNER_ID="\u0660\u0661\u0662")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("positive numeric Discord user id", result.stderr + result.stdout)

    def test_a_normal_id_is_accepted(self):
        result = run_python("import angel.config; print(angel.config.MISTRESS_INT_ID)")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "42")


class TimezoneTest(unittest.TestCase):
    """C-009: a missing tzdata must be an explicit error, never a silent UTC."""

    def test_utc_resolves_without_tzdata(self):
        result = run_python(
            "from angel.config import _resolve_timezone; print(_resolve_timezone('UTC'))",
            ANGEL_TIMEZONE="UTC",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("UTC", result.stdout)

    def test_unknown_zone_fails_loudly(self):
        result = run_python(
            "from angel.config import _resolve_timezone; _resolve_timezone('Not/AZone')",
            ANGEL_TIMEZONE="UTC",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ANGEL_TIMEZONE", result.stderr + result.stdout)
        self.assertIn("tzdata", result.stderr + result.stdout)

    def test_a_real_iana_zone_is_resolved(self):
        result = run_python(
            "from angel.config import _resolve_timezone; print(getattr(_resolve_timezone('Asia/Riyadh'), 'key', ''))",
            ANGEL_TIMEZONE="Asia/Riyadh",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Asia/Riyadh")

    def test_pacific_midnight_has_a_fallback(self):
        code = (
            "import zoneinfo\n"
            "def boom(*a, **k):\n"
            "    raise zoneinfo.ZoneInfoNotFoundError('no tzdata')\n"
            "zoneinfo.ZoneInfo = boom\n"
            "from angel.brain import _seconds_until_pacific_midnight\n"
            "print(int(_seconds_until_pacific_midnight()))\n"
        )
        result = run_python(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(int(result.stdout.strip()), 0)


class NoNetworkInstallTest(unittest.TestCase):
    """P-008: importing the bot must never reach PyPI."""

    def test_bootstrap_never_installs(self):
        source = (REPO / "angel" / "config.py").read_text(encoding="utf-8")
        start = source.index("def _ensure_dependencies")
        end = source.index("_ensure_dependencies()", start)
        body = source[start:end]
        self.assertNotIn("pip", body.lower().replace("pip install -r", ""),
                         "the bootstrap must print the command, not run it")
        self.assertNotIn("check_call", body)
        self.assertNotIn("subprocess.run", body)


if __name__ == "__main__":
    unittest.main()
