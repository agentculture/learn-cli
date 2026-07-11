#!/usr/bin/env python3
"""Render the launch gate's PASS/FAIL table from the collected NDJSON results.

Every check in the gate (the web walk, the CLI + agent pytest audiences, the
launch-bar numbers, the static-auth build check, and preflight) appends one
NDJSON line ``{audience, check, status, detail}`` to ``$LAUNCH_GATE_RESULTS``.
This script reads them all, prints a rollup table + the headline launch-bar
numbers + every non-PASS row, and exits non-zero iff any check FAILED (SKIPs are
allowed but surfaced — the gate is green with explicit skips, red with failures).
"""

from __future__ import annotations

import json
import sys
from collections import OrderedDict

AUDIENCE_ORDER = ["preflight", "static", "launch-bar", "web", "cli", "agent"]
AUDIENCE_LABEL = {
    "preflight": "Preflight (subject CLIs)",
    "static": "Static / zero-API (site build)",
    "launch-bar": "Launch bar (measurable)",
    "web": "Web (Playwright signed-in/out)",
    "cli": "CLI (pytest golden --json)",
    "agent": "Agent (MCP harness)",
}


def _load(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _bar(char: str = "─", n: int = 78) -> str:
    return char * n


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else ""
    if not path:
        print("usage: report.py <results.ndjson>", file=sys.stderr)
        return 2
    try:
        rows = _load(path)
    except OSError as err:
        print(f"report: could not read results ({err})", file=sys.stderr)
        return 2

    by_aud: "OrderedDict[str, list[dict]]" = OrderedDict()
    for aud in AUDIENCE_ORDER:
        by_aud[aud] = []
    for r in rows:
        by_aud.setdefault(r.get("audience", "other"), []).append(r)

    print()
    print(_bar("="))
    print(" LEARN-CLI LAUNCH GATE — PASS/FAIL TABLE")
    print(_bar("="))
    print(f" {'AUDIENCE':<34}{'PASS':>6}{'FAIL':>6}{'SKIP':>6}   STATUS")
    print(f" {_bar('-', 76)}")

    total_fail = total_skip = total_pass = 0
    for aud, items in by_aud.items():
        if not items:
            continue
        p = sum(1 for i in items if i["status"] == "PASS")
        f = sum(1 for i in items if i["status"] == "FAIL")
        s = sum(1 for i in items if i["status"] == "SKIP")
        total_pass += p
        total_fail += f
        total_skip += s
        verdict = "FAIL" if f else ("PASS*" if s else "PASS")
        label = AUDIENCE_LABEL.get(aud, aud)
        print(f" {label:<34}{p:>6}{f:>6}{s:>6}   {verdict}")

    print(f" {_bar('-', 76)}")
    print(f" {'TOTAL':<34}{total_pass:>6}{total_fail:>6}{total_skip:>6}")
    print(_bar("="))

    # Headline launch-bar numbers, verbatim.
    lb = by_aud.get("launch-bar", [])
    if lb:
        print("\n Launch bar (every number machine-checked):")
        for i in lb:
            mark = {"PASS": "ok", "FAIL": "FAIL", "SKIP": "skip"}[i["status"]]
            print(f"   [{mark:>4}] {i['check']}")
            if i.get("detail"):
                print(f"          {i['detail']}")

    # Every non-PASS row, called out.
    problems = [r for r in rows if r["status"] != "PASS"]
    if problems:
        print("\n Non-PASS rows:")
        for r in problems:
            print(
                f"   [{r['status']}] ({r.get('audience')}) {r['check']}"
                + (f" — {r['detail']}" if r.get("detail") else "")
            )

    print()
    if total_fail:
        print(f" GATE: FAIL  ({total_fail} failed, {total_skip} skipped, {total_pass} passed)")
        return 1
    if total_skip:
        print(f" GATE: PASS with {total_skip} SKIPPED  ({total_pass} passed) — review skips above")
        return 0
    print(f" GATE: PASS  (all {total_pass} checks green)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
