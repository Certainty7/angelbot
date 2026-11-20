"""Installation, deployment and quality-gate regressions.

C-001, C-002, C-024, C-025, C-028, C-029, C-034, P-006, P-007.
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


class FreshInstallGateTest(unittest.TestCase):
    """C-001: the pre-start gate must not require the database it is about to create."""

    def _run(self, args, db_path):
        env = dict(os.environ)
        env["ANGEL_DB_PATH"] = db_path
        env["ANGEL_OWNER_ID"] = "42"
        env["ANGEL_AUTO_INSTALL"] = "0"
        env["PYTHONPATH"] = str(REPO)
        return subprocess.run(
            [sys.executable, "bot.py", *args],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

    def test_checkpoint_db_on_fresh_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "brand-new.db")
            result = self._run(["--checkpoint-db"], db_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("No database yet", result.stdout)
            self.assertFalse(os.path.exists(db_path), "the gate must not create the file")

    def test_verify_db_still_fails_without_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(["--verify-db"], os.path.join(tmp, "missing.db"))
            self.assertEqual(result.returncode, 1)


class SystemdUnitTest(unittest.TestCase):
    """C-002: the shipped unit must be writable and bounded."""

    def setUp(self):
        self.unit = _read("deploy/angelbot.service")

    def test_database_path_is_explicit_and_writable(self):
        self.assertRegex(self.unit, r"(?m)^Environment=ANGEL_DB_PATH=/opt/angelbot/data/angel\.db$")
        self.assertRegex(self.unit, r"(?m)^ReadWritePaths=.*(?<!private)/opt/angelbot/data")

    def test_restart_is_bounded(self):
        self.assertRegex(self.unit, r"(?m)^Restart=on-failure$")
        self.assertRegex(self.unit, r"(?m)^StartLimitBurst=\d+$")
        self.assertRegex(self.unit, r"(?m)^StartLimitIntervalSec=\d+$")
        self.assertRegex(self.unit, r"(?m)^TimeoutStopSec=\d+$")

    def test_timers_ship_with_the_repository(self):
        # P-006: the backup and persona jobs existed only on the host.
        for name in ("angelbot-backup.service", "angelbot-backup.timer",
                     "angelbot-persona.service", "angelbot-persona.timer"):
            self.assertTrue((REPO / "deploy" / name).is_file(), name)


class ContainerAssetsTest(unittest.TestCase):
    """C-025: current Deno, no secret-bearing env files, hardened runtime."""

    def test_deno_is_29_or_newer_with_real_hashes(self):
        dockerfile = _read("Dockerfile")
        version = re.search(r"ARG DENO_VERSION=v([\d.]+)", dockerfile)
        self.assertIsNotNone(version)
        major, minor = (int(x) for x in version.group(1).split(".")[:2])
        self.assertGreaterEqual((major, minor), (2, 9), "yt-dlp-ejs needs Deno 2.9+")
        hashes = re.findall(r"ARG DENO_SHA256_(?:AMD64|ARM64)=([0-9a-f]{64})", dockerfile)
        self.assertEqual(len(set(hashes)), 2, "both architecture hashes must be present")

    def test_dockerignore_excludes_every_env_variant(self):
        ignored = _read(".dockerignore").splitlines()
        self.assertIn(".env", ignored)
        self.assertIn(".env.*", ignored)
        self.assertIn("!.env.example", ignored)

    def test_compose_runs_read_only_and_capped(self):
        compose = _read("docker-compose.yml")
        self.assertIn("read_only: true", compose)
        self.assertIn("tmpfs:", compose)
        self.assertIn("pids_limit:", compose)


class WindowsLauncherTest(unittest.TestCase):
    """C-034: dependencies are reconciled on every run and the console is UTF-8."""

    def setUp(self):
        self.script = _read("scripts/run_windows.ps1")

    def test_pip_runs_outside_the_venv_creation_branch(self):
        lines = self.script.splitlines()
        pip_lines = [line for line in lines if "-m pip install -r requirements.txt" in line]
        self.assertTrue(pip_lines, "the launcher must install requirements")
        for line in pip_lines:
            self.assertFalse(line.startswith(" "), f"pip is nested inside a block: {line!r}")
        self.assertIn('if (-not (Test-Path ".venv\\Scripts\\python.exe"))', self.script)

    def test_console_is_switched_to_utf8(self):
        self.assertIn("[Console]::OutputEncoding", self.script)


class BackupScriptTest(unittest.TestCase):
    """C-024: atomic publish, lock, sidecar cleanup."""

    def setUp(self):
        self.script = _read("scripts/backup_db.sh")

    def test_writes_to_a_partial_file_and_renames(self):
        self.assertIn(".partial", self.script)
        self.assertIn("mv -n", self.script)
        self.assertIn("trap cleanup EXIT", self.script)

    def test_locks_and_removes_sidecars(self):
        self.assertIn("flock -n", self.script)
        self.assertIn('-wal', self.script)
        self.assertIn('-shm', self.script)

    def test_image_ships_sqlite3(self):
        self.assertIn("sqlite3", _read("Dockerfile"))


class ToolingGatesTest(unittest.TestCase):
    """C-028 and C-029: a gate must fail closed."""

    def test_token_verifier_rejects_inconclusive_statuses(self):
        spec = importlib.util.spec_from_file_location(
            "verify_cloudflare_token", REPO / "tools" / "verify_cloudflare_token.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for status in (0, 429, 500, 503):
            self.assertFalse(module.authorised(status), f"HTTP {status} must not be PASS")
        for status in (200, 400, 404):
            self.assertTrue(module.authorised(status), f"HTTP {status} is proof of permission")

    def test_late_binding_gate_does_not_swallow_syntax_errors(self):
        sys.path.insert(0, str(REPO / "tools"))
        try:
            import gate_checks
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.py"
            broken.write_text("def x(:\n", encoding="utf-8")
            with self.assertRaises(SyntaxError):
                gate_checks._late_binding_offences(str(broken))

    def test_shell_gate_catches_keyword_and_sh_c(self):
        sys.path.insert(0, str(REPO / "tools"))
        try:
            import gate_checks
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "sample.py"
            sample.write_text(
                "import subprocess, os\n"
                "subprocess.run('id', shell=1)\n"
                "subprocess.run(['sh', '-c', 'id'])\n"
                "subprocess.run('id', **{'shell': True})\n",
                encoding="utf-8",
            )
            old_root, old_roots = gate_checks.ROOT, gate_checks._RUNTIME_ROOTS
            gate_checks.ROOT = tmp
            gate_checks._RUNTIME_ROOTS = ("sample.py",)
            try:
                with self.assertRaises(AssertionError):
                    gate_checks.no_shell_subprocess()
            finally:
                gate_checks.ROOT, gate_checks._RUNTIME_ROOTS = old_root, old_roots


class DependencyPolicyTest(unittest.TestCase):
    """P-007: the scheduled audit must be blocking, not advisory."""

    def test_scheduled_audit_fails_the_job(self):
        workflow = _read(".github/workflows/checks.yml")
        audit_job = workflow.split("dependency-audit:", 1)[1]
        self.assertNotIn("continue-on-error: true", audit_job,
                         "a weekly CVE scan that cannot fail is not a gate")


class HeadersFileTest(unittest.TestCase):
    """C-026: Cloudflare only understands `#` comments."""

    def setUp(self):
        self.text = _read("website/public/_headers")

    def test_no_c_style_comments(self):
        lines = self.text.splitlines()
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "/*":
                # The only legitimate `/*` is a rule, so the next non-empty line is a header.
                following = next((l.strip() for l in lines[index + 1:] if l.strip()), "")
                self.assertRegex(following, r"^[A-Za-z-]+:", "`/*` is not followed by a header")
            self.assertFalse(stripped.startswith("*/"), f"invalid C comment: {line!r}")
            self.assertFalse(
                stripped.startswith("/*") and stripped not in {"/*", "/*/"},
                f"invalid C comment: {line!r}",
            )

    def test_global_rule_carries_the_csp(self):
        blocks = re.split(r"\n(?=\S)", self.text.strip())
        global_blocks = [b for b in blocks if b.splitlines()[0].strip() == "/*"]
        self.assertTrue(global_blocks, "a `/*` rule must exist")
        self.assertIn("Content-Security-Policy:", global_blocks[0])

    def test_no_dead_html_rule(self):
        # Astro builds directories (`/commands/index.html`), so `/*.html` matches nothing.
        for line in self.text.splitlines():
            self.assertNotEqual(line.strip(), "/*.html")


if __name__ == "__main__":
    unittest.main()
