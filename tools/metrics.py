#!/usr/bin/env python3
"""One-line daily metrics for angelbot. Appends JSON to tools/metrics.log.

Latency/spend/refusal numbers come from the per-call lines the bot writes itself
(`ai-reply ...` in angel/brain.py, `ai-guard reason=...` in angel/guard.py),
read back from the last 24 h of journalctl. Latency counts user-facing replies
only (`cmd=message`/`cmd=chat`); background calls (summary, facts, ambient) would
otherwise drag p95 down and hide a slow chat path. Spend counts every call.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import subprocess
from pathlib import Path

from tools import dbpath

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "tools" / "metrics.log"
DB = Path(dbpath.resolve())

AI_REPLY = re.compile(r"ai-reply ms=([0-9.]+) model=(\S+) usd=([0-9.]+) cmd=(\S+) user=(\S+)")
AI_GUARD = re.compile(r"ai-guard reason=([\w-]+)")
SOCIAL = re.compile(r"social outcome=(\w+) url=\S+ n=(\d+) ms=(\d+) class=(\S+)")
REPLY_CMDS = {"message", "chat"}
REFUSAL_REASONS = {"harem-gate", "probe", "budget"}
# The deploy gate runs tools/selftest.py through the unit, and the fixture logs
# `ai-reply model=m1` into the same journal. Those lines are not traffic: counting them
# once produced a false baseline (3 replies, p50=0.0 on a bot nobody had spoken to).
GATE_MODELS = {"m1"}
# ExecStartPre runs the selftest through the unit. Its aiosqlite teardown writes a traceback
# into the journal on some runs, and the gate's own [PASS]/[FAIL] lines mention "Traceback".
# Counting those as production errors made every restart look like an incident.
_GATE_NOISE = ("Event loop is closed", "_connection_worker_thread", "Exception in thread Thread-",
               "aiosqlite/core.py", "[PASS]", "[FAIL]")


def _is_gate_noise(line: str) -> bool:
    return any(marker in line for marker in _GATE_NOISE)


def sh(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def journal_24h() -> list[str]:
    return sh("sudo", "-n", "journalctl", "-u", "angelbot", "--since", "24 hours ago",
              "--no-pager", "-o", "cat").splitlines()


def errors_24h(lines: list[str]) -> int:
    return sum(1 for line in lines if ("ERROR" in line or "Traceback" in line) and not _is_gate_noise(line))


def error_incidents_24h(lines: list[str]) -> int:
    """One exception logs one `| ERROR |` line but several `Traceback` lines."""
    return sum(1 for line in lines if ("| ERROR" in line or "| CRITICAL" in line) and not _is_gate_noise(line))


def traceback_lines_24h(lines: list[str]) -> int:
    return sum(1 for line in lines
               if "Traceback (most recent call last)" in line and not _is_gate_noise(line))


def pct(values: list[float], p: int) -> float | None:
    """Nearest-rank percentile (no interpolation): cheap and easy to read."""
    if not values:
        return None
    return round(sorted(values)[max(0, math.ceil(p / 100 * len(values)) - 1)], 1)


def _is_gate_block(lines: list[str], index: int) -> bool:
    """True when this line sits inside the gate fixture block (selftest runs through the unit).

    The fixture writes `ai-reply model=m1` and its `ai-guard` companions together, so a guard
    line within two lines of a fixture reply is the gate talking, not a real refusal.
    """
    for near in lines[max(0, index - 2): index + 3]:
        match = AI_REPLY.search(near)
        if match and match.group(2) in GATE_MODELS:
            return True
    return False


def ai_stats(lines: list[str]) -> dict:
    """Aggregate the instrumented lines into the five conversation fields."""
    latencies: list[float] = []
    cost = 0.0
    refusals = 0
    for index, line in enumerate(lines):
        reply = AI_REPLY.search(line)
        if reply:
            if reply.group(2) in GATE_MODELS:
                continue
            cost += float(reply.group(3))
            if reply.group(4) in REPLY_CMDS:
                latencies.append(float(reply.group(1)))
            continue
        guard = AI_GUARD.search(line)
        if guard and guard.group(1) in REFUSAL_REASONS and not _is_gate_block(lines, index):
            refusals += 1
    ok = fail = 0
    last_fail = "-"
    for line in lines:
        social = SOCIAL.search(line)
        if not social:
            continue
        outcome = social.group(1)
        if outcome in ("files", "fallback"):
            ok += 1
        else:
            fail += 1
            last_fail = f"{outcome}:{social.group(4)}"

    return {
        "social_ok_24h": ok,
        "social_fail_24h": fail,
        "social_fail_last": last_fail,
        "latency_p50_ms": pct(latencies, 50),
        "latency_p95_ms": pct(latencies, 95),
        "replies_24h": len(latencies),
        "cost_usd_24h": round(cost, 6),
        "refusals_24h": refusals,
    }


def rss_mb() -> float | None:
    """Resident set size of the bot process, not cgroup MemoryCurrent.

    MemoryCurrent includes page cache, so it reads higher than the process RSS while the
    process itself sits near 70 MB; using it for alerting produced false growth reports.
    """
    pid = sh("systemctl", "show", "angelbot", "-p", "MainPID", "--value")
    try:
        with open(f"/proc/{int(pid)}/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024.0, 1)
    except (ValueError, OSError):
        pass
    return None


def uptime_hours() -> float | None:
    raw = sh("systemctl", "show", "angelbot", "-p", "ActiveEnterTimestampMonotonic", "--value")
    try:
        started = int(raw) / 1_000_000
    except ValueError:
        return None
    try:
        now = float(sh("cat", "/proc/uptime").split()[0])
    except (ValueError, IndexError):
        return None
    return round(max(0.0, (now - started) / 3600), 2)


def dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def main() -> None:
    lines = journal_24h()
    db_size = DB.stat().st_size if DB.exists() else 0
    stage = REPO / "stage"
    legacy_stage = Path("/tmp/angelbot_audio")
    record = {
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rss_mb": rss_mb(),
        "uptime_h": uptime_hours(),
        "errors_24h": errors_24h(lines),
        "error_incidents_24h": error_incidents_24h(lines),
        "traceback_lines_24h": traceback_lines_24h(lines),
        **ai_stats(lines),
        "db_bytes": db_size,
        "stage_bytes": dir_size(stage) + dir_size(legacy_stage),
        "load1": os.getloadavg()[0] if hasattr(os, "getloadavg") else None,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
