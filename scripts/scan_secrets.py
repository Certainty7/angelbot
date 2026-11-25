#!/usr/bin/env python3
"""Fail on token-shaped strings in the working tree or anywhere in git history.

The patterns are deliberately narrow: a false positive costs one allowlist entry, a missed Discord
token costs an incident. Binary blobs over 1 MiB and known placeholder files are skipped.
"""

from __future__ import annotations

import re
import subprocess
import sys

PATTERNS = [
    ("discord-token", re.compile(r"[MNO][A-Za-z\d_-]{23,25}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,38}")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("openai-key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    # Real key ids carry digits; a base64 blob of "A"s does not. Lighthouse reports are full of those.
    ("aws-key", re.compile(r"(?<![A-Za-z0-9+/])AKIA(?=[A-Z0-9]*[0-9])[A-Z0-9]{16}(?![A-Za-z0-9+/=])")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
]
ALLOW = {".env.example"}
MAX_BYTES = 1_048_576


def _blobs() -> list[tuple[str, bytes]]:
    out = subprocess.run(
        ["git", "rev-list", "--objects", "--all"], capture_output=True, text=True, check=True
    ).stdout
    seen: dict[str, bytes] = {}
    for line in out.splitlines():
        sha, _, path = line.partition(" ")
        if not path or path in ALLOW or path in seen:
            continue
        size = subprocess.run(
            ["git", "cat-file", "-s", sha], capture_output=True, text=True, check=True
        ).stdout.strip()
        if int(size) > MAX_BYTES:
            continue
        data = subprocess.run(["git", "cat-file", "-p", sha], capture_output=True, check=True).stdout
        seen[path] = data
    return list(seen.items())


def scan(files: list[tuple[str, bytes]]) -> list[str]:
    hits = []
    for path, data in files:
        if path in ALLOW:
            continue
        text = data.decode("utf-8", "ignore")
        for name, pattern in PATTERNS:
            for match in pattern.finditer(text):
                hits.append(f"{name}:{path}:{match.group(0)[:8]}…")
    return hits


def main() -> int:
    hits = scan(_blobs())
    print("\n".join(hits) if hits else "no secrets found")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
