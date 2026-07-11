#!/usr/bin/env python3
"""A *drifted* subject CLI — used to prove the conformance gate FAILS on drift.

Everything the gate probes is valid EXCEPT two deliberate contract violations:

* ``overview`` emits ``schema_version: "2.0"`` (an incompatible major) and omits
  the required ``modules`` field, so the payload fails schema validation — this
  is *payload drift*.
* a bad invocation exits ``0`` and prints to STDOUT instead of emitting the
  ``{code, message, remediation}`` error shape to STDERR — this is *exit/stream
  contract drift*.

``learn subject doctor`` must catch both: report ``healthy: false``, fail the
``verb-overview`` and ``error-contract`` checks, and exit 2.
"""

from __future__ import annotations

import json
import sys
from typing import Any

SUBJECT = "brokenlang"
SCHEMA_VERSION = "1.0"
CONTRACT_VERSION = "1.0"


def _emit(payload: dict[str, Any]) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def _drifted_overview() -> dict[str, Any]:
    # schema_version 2.0 is an incompatible major, and `modules` is missing.
    return {
        "schema_version": "2.0",
        "kind": "subject_overview",
        "subject": SUBJECT,
        "display_name": "Broken Language",
        "description": "A subject that has drifted from contract v1.",
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
                "message": "content loads",
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
        "items_total": 1,
        "items_touched": 0,
        "items_mastered": 0,
        "mastery": {},
        "next": {
            "done": False,
            "text": "start",
            "command": "brokenlang lesson start --json",
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
        "stories": [],
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
        return _emit(_drifted_overview())
    if verb == "doctor":
        return _emit(_doctor())
    if verb == "progress":
        return _emit(_progress(learner))
    if verb == "advice":
        return _emit(_advice(learner))
    if verb == "story" and rest[:1] == ["list"]:
        return _emit(_story_list())
    # Exit/stream contract drift: a failure that exits 0 and writes to stdout.
    sys.stdout.write(f"oops, no such verb: {' '.join(tokens)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
