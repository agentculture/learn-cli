#!/usr/bin/env python3
"""A conformant subject CLI whose one story ships a well-formed pick-the-right-word
cloze exercise (``text`` + ``blanks``, docs/specs/subject-plugin-contract.md
§3.6.1) alongside a legacy single-blank free-text cloze exercise (``prompt`` +
``answer`` only, no ``blanks``) — proving the two coexist under the same
``type: "cloze"`` value exactly as the contract decision requires.

Not installed as a dependency and never imported by learn-cli: driven purely as
an external subprocess over ``--json``, same as ``conformant_subject.py``. Used
by ``tests/test_subject_doctor.py``'s PASS case for the ``cloze-items`` check.
"""

from __future__ import annotations

import json
import sys
from typing import Any

SUBJECT = "clozelang"
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
        "display_name": "Cloze Language",
        "tagline": "A dummy subject proving the pick-the-right-word cloze shape.",
        "description": "The cloze-fixture subject: a hand-rolled conformant CLI used to prove "
        "`learn subject doctor` verifies well-formed cloze blanks.",
        "modules": [
            {
                "id": "m1",
                "title": "First Module",
                "summary": "One story, one of each cloze flavor.",
                "level": "beginner",
            }
        ],
        "content": {"stories": 1, "lessons": 0, "exercises": 2},
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
        "items_total": 2,
        "items_touched": 0,
        "items_mastered": 0,
        "completed": [],
        "mastery": {},
        "next": {
            "done": False,
            "module_id": "m1",
            "item_id": "greetings",
            "text": "read the first story",
            "command": "clozelang story read s-cloze --json",
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
                "id": "s-cloze",
                "title": "Cloze Story",
                "level": "beginner",
                "level_detail": "A1",
                "summary": "A tiny passage exercising both cloze flavors.",
                "exercises": 2,
            }
        ],
    }


#: The one full story the fixture serves, keyed by id (for `story read <id>`).
_STORIES: dict[str, dict[str, Any]] = {
    "s-cloze": {
        "schema_version": SCHEMA_VERSION,
        "kind": "story",
        "id": "s-cloze",
        "subject": SUBJECT,
        "title": "Cloze Story",
        "level": "beginner",
        "level_detail": "A1",
        "summary": "A tiny passage exercising both cloze flavors.",
        "body": "Bonjour, je m'appelle Marie et j'ai dix ans.",
        "glossary": [{"term": "bonjour", "definition": "hello"}],
        "exercises": [
            {
                "id": "cloze-good-1",
                "type": "cloze",
                "item_id": "greetings",
                "prompt": "Fill in each blank with the right word.",
                "text": "Bonjour, je m'appelle {{name}} et j'ai {{age}} ans.",
                "blanks": [
                    {"id": "name", "options": ["Marie", "Paris", "bleu"], "answer": "Marie"},
                    {"id": "age", "options": ["dix", "rouge", "vite"], "answer": "dix"},
                ],
            },
            {
                # The legacy single-blank free-text cloze shape (contract 1.0,
                # unchanged): no `text`/`blanks`, so `_is_cloze_blanks_item`
                # skips it entirely — it is not subject to the new check.
                "id": "cloze-legacy-1",
                "type": "cloze",
                "item_id": "numbers-money",
                "prompt": "« C'est ___ ? » — « Dix euros, madame. »",
                "answer": "combien",
            },
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
                "clozelang record --item greetings --exercise cloze-good-1 "
                "--activity story --correct 2 --total 2 --result pass --json"
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
                "run 'clozelang story list --json' to see valid story ids",
            )
        return _emit(payload)
    return _fail(
        f"unknown verb: {' '.join(tokens) or '<none>'}",
        "run 'clozelang overview --json' to see valid verbs",
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
