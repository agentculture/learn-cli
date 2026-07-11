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
            },
            {
                "id": "dev-smoke",
                "title": "Dev Smoke Story",
                "level": "beginner",
                "level_detail": "A1",
                "summary": "In-repo test fixture; excluded from the public export.",
                "exercises": 0,
            },
        ],
    }


#: The one full story the fixture serves, keyed by id (for `story read <id>`).
_STORIES: dict[str, dict[str, Any]] = {
    "s1": {
        "schema_version": SCHEMA_VERSION,
        "kind": "story",
        "id": "s1",
        "subject": SUBJECT,
        "title": "The First Story",
        "level": "beginner",
        "level_detail": "A1",
        "summary": "A tiny graded reader for the fourth language.",
        "body": "The learner meets the fourth language and says hello.",
        "glossary": [{"term": "hello", "definition": "a greeting"}],
        "exercises": [
            {
                "id": "s1-q1",
                "type": "multiple_choice",
                "item_id": "greetings",
                "prompt": "What does the character say first?",
                "choices": ["Hello", "Goodbye"],
                "answer": "Hello",
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
            "instructions": [
                "Present the story one paragraph at a time.",
                "Run each comprehension exercise and record every result.",
            ],
            "record_with": [
                "fourthlang record --item greetings --exercise s1-q1 "
                "--activity story --result pass --json"
            ],
        },
    }


def _lesson(learner: str, mode: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "lesson_directive",
        "subject": SUBJECT,
        "learner": learner,
        "mode": mode,
        "lesson": {
            "id": "l1",
            "module_id": "m1",
            "title": "First Lesson",
            "level": "beginner",
            "difficulty": 1,
            "objectives": ["Greet someone in the fourth language."],
            "items": [
                {"id": "greetings", "label": "Greetings", "points": ["Say hello and goodbye."]}
            ],
        },
        "directive": {
            "instructions": ["Teach one point at a time.", "Record each check."],
            "record_with": [
                "fourthlang record --item greetings --activity lesson --result pass --json"
            ],
        },
    }


def _practice(learner: str, scope: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "practice_directive",
        "subject": SUBJECT,
        "learner": learner,
        "scope": scope or "review",
        "exercises": [
            {
                "id": "p1",
                "type": "translation",
                "item_id": "greetings",
                "prompt": "Say hello in the fourth language.",
                "answer": "hello",
            }
        ],
        "directive": {
            "instructions": ["Run each exercise conversationally.", "Record each result."],
            "record_with": [
                "fourthlang record --item greetings --exercise p1 "
                "--activity practice --result pass --json"
            ],
        },
    }


#: Result → mastery inference (never regresses on inference; culture-guide's mapping).
_MASTERY_OF = {"fail": "introduced", "partial": "practiced", "pass": "mastered"}


def _opt(tokens: list[str], flag: str) -> str | None:
    if flag in tokens:
        i = tokens.index(flag)
        if i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def _record(learner: str, rest: list[str]) -> dict[str, Any] | None:
    item = _opt(rest, "--item")
    result = _opt(rest, "--result")
    if not item or result not in _MASTERY_OF:
        return None
    recorded: dict[str, Any] = {
        "item_id": item,
        "activity": _opt(rest, "--activity") or "practice",
        "result": result,
        "at": "2026-07-11T00:00:00+00:00",
    }
    exercise = _opt(rest, "--exercise")
    if exercise:
        recorded["exercise_id"] = exercise
    correct = _opt(rest, "--correct")
    total = _opt(rest, "--total")
    if correct is not None:
        recorded["correct"] = int(correct)
    if total is not None:
        recorded["total"] = int(total)
    duration = _opt(rest, "--duration-seconds")
    if duration is not None:
        recorded["duration_seconds"] = float(duration)
    story = _opt(rest, "--story")
    if story:
        recorded["story_id"] = story
    lesson = _opt(rest, "--lesson")
    if lesson:
        recorded["lesson_id"] = lesson
    notes = _opt(rest, "--notes")
    if notes:
        recorded["notes"] = notes
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "record_ack",
        "subject": SUBJECT,
        "learner": learner,
        "recorded": recorded,
        "mastery": {"item_id": item, "level": _MASTERY_OF[result]},
        "next": {
            "done": False,
            "module_id": "m1",
            "item_id": item,
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
    if verb == "story" and rest[:1] == ["read"]:
        payload = _story_read(learner, rest[1] if len(rest) > 1 else "")
        if payload is None:
            return _fail(
                f"unknown story: {rest[1] if len(rest) > 1 else '<none>'}",
                "run 'fourthlang story list --json' to see valid story ids",
            )
        return _emit(payload)
    if verb == "lesson" and rest[:1] in (["start"], ["next"], ["repeat"]):
        return _emit(_lesson(learner, rest[0]))
    if verb == "practice":
        return _emit(_practice(learner, rest[0] if rest else ""))
    if verb == "record":
        payload = _record(learner, rest)
        if payload is None:
            return _fail(
                "record requires --item <id> and --result pass|partial|fail",
                "e.g. fourthlang record --item greetings --result pass --json",
            )
        return _emit(payload)
    return _fail(
        f"unknown verb: {' '.join(tokens) or '<none>'}",
        "run 'fourthlang overview --json' to see valid verbs",
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
