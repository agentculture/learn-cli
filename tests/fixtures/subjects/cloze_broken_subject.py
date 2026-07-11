#!/usr/bin/env python3
"""A subject CLI whose one cloze exercise is malformed: the blank's `answer`
is not among its own `options`. Every OTHER verb the gate probes is valid, so
`learn subject doctor` must fail on exactly the `cloze-items` check — proving
the check actually inspects content, not just plumbing.

Used by tests/test_subject_doctor.py's FAIL case for the `cloze-items` check.
"""

from __future__ import annotations

import json
import sys
from typing import Any

SUBJECT = "clozebroken"
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
        "display_name": "Cloze Broken Language",
        "tagline": "A dummy subject proving `cloze-items` catches malformed blanks.",
        "description": "The broken-cloze fixture: every verb is contract-valid EXCEPT the "
        "cloze exercise's blank, whose answer is missing from its own options.",
        "modules": [
            {
                "id": "m1",
                "title": "First Module",
                "summary": "One story, one malformed cloze item.",
                "level": "beginner",
            }
        ],
        "content": {"stories": 1, "lessons": 0, "exercises": 1},
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
                "message": "content and story files load and validate",
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
        "completed": [],
        "mastery": {},
        "next": {
            "done": False,
            "module_id": "m1",
            "item_id": "greetings",
            "text": "read the first story",
            "command": "clozebroken story read s-cloze-bad --json",
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
                "id": "s-cloze-bad",
                "title": "Broken Cloze Story",
                "level": "beginner",
                "level_detail": "A1",
                "summary": "A passage whose cloze answer is not in its own options.",
                "exercises": 1,
            }
        ],
    }


_STORIES: dict[str, dict[str, Any]] = {
    "s-cloze-bad": {
        "schema_version": SCHEMA_VERSION,
        "kind": "story",
        "id": "s-cloze-bad",
        "subject": SUBJECT,
        "title": "Broken Cloze Story",
        "level": "beginner",
        "level_detail": "A1",
        "summary": "A passage whose cloze answer is not in its own options.",
        "body": "Bonjour, je m'appelle Marie.",
        "glossary": [],
        "exercises": [
            {
                "id": "cloze-bad-1",
                "type": "cloze",
                "item_id": "greetings",
                "prompt": "Fill in the blank with the right word.",
                "text": "Bonjour, je m'appelle {{name}}.",
                # The blank's `answer` ("Marie") is NOT one of `options` —
                # exactly the violation the `cloze-items` check must catch.
                "blanks": [{"id": "name", "options": ["Paris", "bleu"], "answer": "Marie"}],
            }
        ],
        "audio": None,
    }
}


def _story_read(learner: str, story_id: str) -> dict[str, Any] | None:
    story = _STORIES.get(story_id)
    if story is None:
        return None
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "story_read",
        "subject": SUBJECT,
        "learner": learner,
        "story": story,
        "directive": {
            "instructions": ["Present the story one paragraph at a time."],
            "record_with": [
                "clozebroken record --item greetings --exercise cloze-bad-1 "
                "--activity story --result pass --json"
            ],
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
    if verb == "story" and rest[:1] == ["read"]:
        payload = _story_read(learner, rest[1] if len(rest) > 1 else "")
        if payload is None:
            return _fail(
                f"unknown story: {rest[1] if len(rest) > 1 else '<none>'}",
                "run 'clozebroken story list --json' to see valid story ids",
            )
        return _emit(payload)
    return _fail(
        f"unknown verb: {' '.join(tokens) or '<none>'}",
        "run 'clozebroken overview --json' to see valid verbs",
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
