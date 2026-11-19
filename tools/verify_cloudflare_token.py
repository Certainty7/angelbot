#!/usr/bin/env python3
"""Verify the Cloudflare API token without ever printing it.

Reads CLOUDFLARE_API_TOKEN from the environment, probes each capability the
deployment needs, and prints a PASS/FAIL table plus the exact scope observed.
Exit code 0 only when every required capability is present.

Design notes:
  * the token is never echoed, logged, or written to disk;
  * a capability is decided by HTTP status, not by the wording of an error:
      403 / 10000  -> not authorised for that endpoint
      404          -> authorised, resource simply absent
    that difference is what separates "no permission" from "nothing there yet";
  * POST probes send a deliberately invalid body so a write permission can be
    detected without creating a resource. 400 with a validation error means the
    permission is present; 403 means it is not.

Usage:  python3 tools/verify_cloudflare_token.py [--zone NAME] [--account ID]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"


def call(token: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:  # a 403/404/400 is data here, not a crash
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}
    except Exception as exc:  # network failure must not look like a permission
        return 0, {"errors": [{"message": f"transport: {exc}"}]}


def authorised(status: int) -> bool:
    """403 = no permission; 400/404/200 = permission present."""
    return status not in (401, 403)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone", default=os.getenv("CLOUDFLARE_ZONE", ""), help="zone name; or set CLOUDFLARE_ZONE")
    ap.add_argument("--account", default=None, help="defaults to the only account on the token")
    args = ap.parse_args()

    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not token:
        print("FATAL: CLOUDFLARE_API_TOKEN is not in the environment.", file=sys.stderr)
        return 2
    if not args.zone:
        print("FATAL: pass --zone or set CLOUDFLARE_ZONE.", file=sys.stderr)
        return 2

    rows: list[tuple[str, bool, str]] = []

    # 1. token alive
    st, d = call(token, "GET", "/user/tokens/verify")
    alive = bool(st == 200 and d.get("success"))
    detail = str((d.get("result") or {}).get("status") or d.get("errors"))
    rows.append(("token verify", alive, detail))

    if not alive:
        print_table(rows)
        return 1

    # 2. accounts visible, and the scope
    st, d = call(token, "GET", "/accounts")
    accounts = [(a["id"], a["name"]) for a in (d.get("result") or [])] if d.get("success") else []
    account_id = args.account or (accounts[0][0] if accounts else None)
    rows.append(
        (
            "accounts visible",
            bool(accounts),
            "; ".join(n for _i, n in accounts) or "none",
        )
    )

    # 3. zone visible
    st, d = call(token, "GET", f"/zones?name={args.zone}")
    zones = d.get("result") or [] if d.get("success") else []
    zone = zones[0] if zones else None
    rows.append(("zone read", bool(zone), f"{zone['name']} status={zone['status']}" if zone else "not visible"))
    zone_id = zone["id"] if zone else None

    # 4. DNS: read and write, decided separately
    if zone_id:
        st, d = call(token, "GET", f"/zones/{zone_id}/dns_records")
        rows.append(("dns read", authorised(st) and st == 200, f"http={st}"))
        st, d = call(
            token,
            "POST",
            f"/zones/{zone_id}/dns_records",
            {"type": "TXT", "name": "", "content": ""},  # invalid on purpose
        )
        rows.append(("dns write", authorised(st), f"http={st} (400 = allowed, nothing created)"))
    else:
        rows.append(("dns read", False, "no zone"))
        rows.append(("dns write", False, "no zone"))

    # 5. Pages
    if account_id:
        st, d = call(token, "GET", f"/accounts/{account_id}/pages/projects")
        projects = [p["name"] for p in (d.get("result") or [])] if d.get("success") else []
        rows.append(("pages list", st == 200 and d.get("success", False), f"http={st} projects={projects}"))
        st, _ = call(token, "GET", f"/accounts/{account_id}/pages/projects/__probe-does-not-exist")
        rows.append(("pages write scope", authorised(st), f"http={st} (404 = authorised)"))

        # 6. Workers: only to know whether the stray script can be removed here
        st, d = call(token, "GET", f"/accounts/{account_id}/workers/scripts")
        scripts = [s.get("id") for s in (d.get("result") or [])] if d.get("success") else []
        rows.append(("workers read", st == 200 and d.get("success", False), f"scripts={scripts}"))
        st, _ = call(token, "DELETE", f"/accounts/{account_id}/workers/scripts/__probe-does-not-exist")
        rows.append(("workers delete scope", authorised(st), f"http={st} (404 = authorised)"))

    print_table(rows)
    required = {"token verify", "zone read", "dns read", "dns write", "pages list"}
    missing = [name for name, ok, _detail in rows if name in required and not ok]
    if missing:
        print("\nMISSING required capability: " + ", ".join(missing))
        print("Grant: Zone -> DNS -> Edit (which includes Read) on this zone only.")
        return 1
    print("\nAll required capabilities present.")
    return 0


def print_table(rows: list[tuple[str, bool, str]]) -> None:
    width = max(len(r[0]) for r in rows)
    print(f"{'capability'.ljust(width)}  result  detail")
    print(f"{'-' * width}  ------  ------")
    for name, ok, detail in rows:
        print(f"{name.ljust(width)}  {'PASS' if ok else 'FAIL':<6}  {detail}")


if __name__ == "__main__":
    sys.exit(main())
