#!/usr/bin/env python3
"""The measurable launch bar — every number machine-checked, nothing by hand.

Run via ``uv run python tools/launch-gate/launch_bar.py`` from the repo root,
with the three subject CLIs on PATH (the gate's ``run.sh`` arranges that). Emits
one NDJSON result line per check to ``$LAUNCH_GATE_RESULTS`` (when set) and a
human-readable summary to stdout; exits non-zero if any launch-bar check fails.

Checks (spec claims c14/h23, c32/h24):

1. **3 subjects pass ``learn subject doctor``** — subprocesses the real
   ``learn subject doctor <s> --json`` and asserts ``healthy: true``.
2. **Content counts from the real content** — drives each subject's own
   ``story list --json`` (through the same subject driver the product uses, so
   ``culture-guide``'s ``subject`` prefix is honored) and counts NON-dev
   stories: >=10 stories across >=3 levels for french + spanish, >=3 scenarios
   for culture-guide.
3. **Zero new design tokens vs org** — extracts the set of ``--custom-property``
   NAMES *defined* in this site's ``global.css`` and in org's, and asserts
   learn's set is a SUBSET of org's (zero new tokens). Read-only on ../org.

The zero-API static check (``site-astro npm run check``) is a separate step in
run.sh (it needs a node build), not duplicated here.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404 - driving the real CLIs is the whole point
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_FILE = os.environ.get("LAUNCH_GATE_RESULTS", "")

# Content thresholds from the brief's launch bar.
LANGUAGE_MIN_STORIES = 10
LANGUAGE_MIN_LEVELS = 3
CULTURE_GUIDE_MIN_SCENARIOS = 3

_results: list[dict[str, str]] = []


def _emit(check: str, ok: bool, detail: str) -> bool:
    status = "PASS" if ok else "FAIL"
    _results.append({"audience": "launch-bar", "check": check, "status": status, "detail": detail})
    print(f"  [{status:<5}] {check} — {detail}")
    return ok


def _non_dev_stories(payload: dict) -> list[dict]:
    return [s for s in payload.get("stories", []) if not str(s.get("id", "")).startswith("dev-")]


def check_subject_doctors() -> bool:
    ok_all = True
    for subject in ("french", "spanish", "culture-guide"):
        try:
            proc = subprocess.run(  # nosec B603 B607 - literal argv, PATH set by run.sh
                ["learn", "subject", "doctor", subject, "--json"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            report = json.loads(proc.stdout) if proc.stdout.strip() else {}
            healthy = bool(report.get("healthy")) and proc.returncode == 0
            checks = report.get("checks", [])
            detail = f"healthy={healthy}, exit={proc.returncode}, {len(checks)} conformance checks"
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as err:
            healthy = False
            detail = f"error running 'learn subject doctor {subject}': {err}"
        ok_all &= _emit(f"{subject}: passes 'learn subject doctor'", healthy, detail)
    return ok_all


def check_content_counts() -> bool:
    # Import the real subject driver so argv_prefix (culture-guide subject) is honored.
    sys.path.insert(0, str(REPO_ROOT))
    from learn.front._driver import drive  # noqa: E402  (import after sys.path tweak)

    ok_all = True
    for subject in ("french", "spanish"):
        try:
            payload = drive(subject, ("story", "list"))
            stories = _non_dev_stories(payload)
            levels = sorted({s.get("level") for s in stories if s.get("level")})
            ok = len(stories) >= LANGUAGE_MIN_STORIES and len(levels) >= LANGUAGE_MIN_LEVELS
            detail = (
                f"{len(stories)} non-dev stories across {len(levels)} levels "
                f"({', '.join(levels)}) — need >={LANGUAGE_MIN_STORIES} x >={LANGUAGE_MIN_LEVELS}"
            )
        except Exception as err:  # noqa: BLE001 - any driver failure is a FAIL, reported
            ok, detail = False, f"error driving {subject} story list: {err}"
        ok_all &= _emit(f"{subject}: content counts (>=10 stories x >=3 levels)", ok, detail)

    try:
        payload = drive("culture-guide", ("story", "list"))
        scenarios = _non_dev_stories(payload)
        ok = len(scenarios) >= CULTURE_GUIDE_MIN_SCENARIOS
        detail = f"{len(scenarios)} non-dev scenarios — need >={CULTURE_GUIDE_MIN_SCENARIOS}"
    except Exception as err:  # noqa: BLE001
        ok, detail = False, f"error driving culture-guide story list: {err}"
    ok_all &= _emit("culture-guide: content counts (>=3 scenarios)", ok, detail)
    return ok_all


# A defined custom property is `--name:` (a declaration); a usage is `var(--name)`
# — followed by `)`/`,`, never `:`. So a lookahead for `:` selects definitions only.
_TOKEN_DEF_RE = re.compile(r"(?<![\w-])(--[A-Za-z0-9-]+)\s*:")


def _defined_tokens(css_path: Path) -> set[str]:
    text = css_path.read_text(encoding="utf-8")
    return set(_TOKEN_DEF_RE.findall(text))


def _resolve_org_css() -> Path | None:
    """Find org's global.css. In a worktree ``../org`` doesn't resolve, so try a
    few sibling-of-repo locations; ``$LAUNCH_GATE_ORG_CSS`` overrides everything."""
    override = os.environ.get("LAUNCH_GATE_ORG_CSS")
    rel = Path("site-astro") / "src" / "styles" / "global.css"
    candidates = [Path(override)] if override else []
    candidates += [
        REPO_ROOT.parent / "org" / rel,  # ../org (plain checkout)
        REPO_ROOT.parent.parent / "org" / rel,  # ../../org (one-level worktree)
        Path.home() / "git" / "org" / rel,  # ~/git/org (canonical)
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def check_css_tokens() -> bool:
    learn_css = REPO_ROOT / "site-astro" / "src" / "styles" / "global.css"
    org_css = _resolve_org_css()
    if org_css is None:
        return _emit(
            "zero new design tokens vs org's global.css",
            False,
            "org global.css not found (set LAUNCH_GATE_ORG_CSS or check out org as a sibling)",
        )
    learn_tokens = _defined_tokens(learn_css)
    org_tokens = _defined_tokens(org_css)
    extra = sorted(learn_tokens - org_tokens)
    ok = not extra
    detail = (
        f"learn defines {len(learn_tokens)} tokens, all in org's {len(org_tokens)}"
        if ok
        else f"NEW tokens not in org: {', '.join(extra)}"
    )
    return _emit("zero new design tokens vs org's global.css", ok, detail)


def main() -> int:
    print("launch bar:")
    ok = True
    ok &= check_subject_doctors()
    ok &= check_content_counts()
    ok &= check_css_tokens()

    if RESULTS_FILE:
        with open(RESULTS_FILE, "a", encoding="utf-8") as fh:
            for row in _results:
                fh.write(json.dumps(row) + "\n")

    passed = sum(1 for r in _results if r["status"] == "PASS")
    print(f"launch bar: {passed}/{len(_results)} checks passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
