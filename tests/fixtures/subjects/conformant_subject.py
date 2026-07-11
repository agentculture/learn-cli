#!/usr/bin/env python3
"""A minimal *conformant* subject CLI — the dummy fourth subject.

This is not installed as a dependency and is never imported by learn-cli: the
conformance gate (``learn subject doctor``) drives it purely as an external
subprocess over ``--json``, exactly as it would a real subject console script
(``french``, ``spanish``, ``culture-guide``). It exists to prove that adding a
subject is *registration, not a fork* — a data-only registry entry plus a
conformant executable, with zero new learn-cli platform code.

It emits schema-valid v1.x payloads for the read-only contract verbs the gate
probes (``overview``, ``doctor``, ``progress``, ``advice``, ``story list``) and
honours the error/exit contract on a bad invocation: stderr carries the
``{code, message, remediation}`` shape, stdout stays empty, and it exits 1.

It also implements ``record`` (not probed by the conformance gate — mutating
verbs are validated by golden payloads in each subject repo's own CI per
``learn/subjects/conformance.py``'s module docstring) so learn-cli's runtime
``learn record`` proxy (t12) has something conformant to drive in tests.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

_LEVEL_FOR_RESULT = {"fail": "introduced", "partial": "practiced", "pass": "mastered"}

SUBJECT = "fourthlang"
SCHEMA_VERSION = "1.0"
CONTRACT_VERSION = "1.0"


def _emit(payload: dict[str, Any]) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def _fail(message: str, remediation: str) -> int:
    json.dump(
        {"code": 1, "message": message, "remediation": remediation},
        sys.stderr,
        ensure_ascii=False,
    )
    sys.stderr.write("\n")
    return 1


def _overview() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "subject_overview",
        "subject": SUBJECT,
        "display_name": "Fourth Language",
        "tagline": "A dummy subject proving registration is data, not code.",
        "description": "The fourth-subject fixture: a hand-rolled conformant CLI "
        "used to prove learn-cli hosts any subject via registration alone.",
        "modules": [
            {
                "id": "m1",
                "title": "First Module",
                "summary": "The survival core of the fourth language.",
                "level": "beginner",
            }
        ],
        "content": {"stories": 1, "lessons": 1, "exercises": 2},
    }


def _doctor() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "subject_doctor",
        "subject": SUBJECT,
        "contract_version": CONTRACT_VERSION,
        "healthy": True,
        "checks": [
            {
                "id": "content-present",
                "passed": True,
                "severity": "info",
                "message": "content and lesson files load and validate",
                "remediation": "",
            }
        ],
    }


def _progress(learner: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "progress",
        "subject": SUBJECT,
        "learner": learner,
        "items_total": 3,
        "items_touched": 0,
        "items_mastered": 0,
        "completed": [],
        "mastery": {},
        "next": {
            "done": False,
            "module_id": "m1",
            "item_id": "greetings",
            "text": "start the first module",
            "command": "fourthlang lesson start m1 --json",
        },
    }


def _advice(learner: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "advice",
        "subject": SUBJECT,
        "learner": learner,
        "advice": [],
    }


def _story_list() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "story_list",
        "subject": SUBJECT,
        "stories": [
            {
                "id": "s1",
                "title": "The First Story",
                "level": "beginner",
                "level_detail": "A1",
                "summary": "A tiny graded reader for the fourth language.",
                "exercises": 2,
            }
        ],
    }


def _parse_flags(tokens: list[str]) -> dict[str, str]:
    """A tiny ``--flag value`` scanner — enough for the fixture's own verbs."""
    opts: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--") and i + 1 < len(tokens):
            opts[tok[2:]] = tokens[i + 1]
            i += 2
        else:
            i += 1
    return opts


def _record(learner: str, tokens: list[str]) -> dict[str, Any]:
    opts = _parse_flags(tokens)
    item_id = opts.get("item", "unknown-item")
    result = opts.get("result", "pass")
    activity = opts.get("activity", "practice")
    recorded: dict[str, Any] = {
        "item_id": item_id,
        "activity": activity,
        "result": result,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if "exercise" in opts:
        recorded["exercise_id"] = opts["exercise"]
    if "story" in opts:
        recorded["story_id"] = opts["story"]
    if "lesson" in opts:
        recorded["lesson_id"] = opts["lesson"]
    if "correct" in opts:
        recorded["correct"] = int(opts["correct"])
    if "total" in opts:
        recorded["total"] = int(opts["total"])
    if "duration-seconds" in opts:
        recorded["duration_seconds"] = float(opts["duration-seconds"])
    if "notes" in opts:
        recorded["notes"] = opts["notes"]
    level = _LEVEL_FOR_RESULT.get(result, "unknown")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "record_ack",
        "subject": SUBJECT,
        "learner": learner,
        "recorded": recorded,
        "mastery": {"item_id": item_id, "level": level},
        "next": {
            "done": False,
            "module_id": "m1",
            "item_id": item_id,
            "text": "keep going",
            "command": "fourthlang lesson next --json",
        },
    }


def main(argv: list[str]) -> int:
    tokens = [t for t in argv if t != "--json"]
    learner = "anonymous"
    if "--learner" in tokens:
        i = tokens.index("--learner")
        if i + 1 < len(tokens):
            learner = tokens[i + 1]
            del tokens[i : i + 2]
        else:
            del tokens[i]
    verb = tokens[0] if tokens else ""
    rest = tokens[1:]

    if verb == "overview":
        return _emit(_overview())
    if verb == "doctor":
        return _emit(_doctor())
    if verb == "progress":
        return _emit(_progress(learner))
    if verb == "advice":
        return _emit(_advice(learner))
    if verb == "story" and rest[:1] == ["list"]:
        return _emit(_story_list())
    if verb == "record":
        return _emit(_record(learner, rest))
    return _fail(
        f"unknown verb: {' '.join(tokens) or '<none>'}",
        "run 'fourthlang overview --json' to see valid verbs",
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
