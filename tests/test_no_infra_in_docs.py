"""Docs must not carry this deployment's address, key paths or home directory.

The v1.1.0 plan files were committed with the production address, the SSH key path and the
operator's home directory in them. The tree is sanitised now; this test keeps it that way and
fails on the same leak in any future Markdown file, including plans.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Anything that identifies *this* deployment rather than a documented convention.
# `/opt/angelbot` is deliberately absent: README and the unit file document it as the install path.
PATTERNS = {
    "public IPv4 literal": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "ssh private-key path": re.compile(r"ssh\s+-i\s+(?:~|/|\S*\.key)"),
    "operator key file": re.compile(r"ssh-key-\d{4}-\d{2}-\d{2}\.key|id_(?:rsa|ed25519)\b"),
    "operator home": re.compile(r"/opt/data\b"),
    "provider host label": re.compile(r"hstgr\.cloud|Hostinger", re.IGNORECASE),
}
ALLOWED = {
    "0.0.0.0",
    "127.0.0.1",
    "255.255.255.255",
    "169.254.169.254",  # cloud metadata service, a documented threat-model reference
}


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [REPO / name for name in out]


class NoInfrastructureInDocsTest(unittest.TestCase):
    def test_docs_carry_no_deployment_identifiers(self):
        offences: list[str] = []
        for path in tracked_markdown():
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                for label, pattern in PATTERNS.items():
                    for match in pattern.finditer(line):
                        if match.group(0) in ALLOWED:
                            continue
                        offences.append(
                            f"{path.relative_to(REPO)}:{lineno} {label}: {match.group(0)[:40]}"
                        )
        self.assertEqual(offences, [], "\n".join(offences))

    def test_the_patterns_still_catch_a_leak(self):
        """A guard that cannot fail is decoration."""
        sample = "run `ssh -i " + "deploy" + ".key ubuntu@" + "203.0.113.10` from /opt/" + "data/keys"
        hits = [label for label, pattern in PATTERNS.items() if pattern.search(sample)]
        self.assertIn("public IPv4 literal", hits)
        self.assertIn("ssh private-key path", hits)
        self.assertIn("operator home", hits)


if __name__ == "__main__":
    unittest.main()
