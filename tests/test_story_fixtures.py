"""Acceptance tests for the shared story schema (t2, spec c29).

One story schema validates for all three launch subjects: a french graded story,
a spanish graded story, and a culture-guide narrative scenario. The fixtures
under ``tests/fixtures/stories/`` are the reference content files t4/t5/t7/t8
will pattern their committed story libraries on.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from learn import contract

STORIES = Path(__file__).parent / "fixtures" / "stories"

FIXTURE_FILES = {
    "french": "french-beginner-le-marche.json",
    "spanish": "spanish-beginner-la-panaderia.json",
    "culture-guide": "culture-guide-scenario-overloaded-agent.json",
}


def _story(subject: str) -> dict:
    return json.loads((STORIES / FIXTURE_FILES[subject]).read_text(encoding="utf-8"))


# --- the acceptance criterion: all three subjects validate ----------------------


@pytest.mark.parametrize("subject", sorted(FIXTURE_FILES))
def test_story_fixture_validates(subject: str) -> None:
    errors = contract.validate(_story(subject), "story")
    assert errors == [], f"{subject} story fixture: {errors}"


@pytest.mark.parametrize("subject", sorted(FIXTURE_FILES))
def test_story_fixture_identity(subject: str) -> None:
    story = _story(subject)
    assert story["subject"] == subject
    assert story["kind"] == "story"
    assert story["schema_version"] == contract.CONTRACT_VERSION


def test_language_stories_are_graded() -> None:
    assert _story("french")["level"] == "beginner"
    assert _story("spanish")["level"] == "beginner"


def test_culture_guide_story_is_a_narrative_scenario() -> None:
    story = _story("culture-guide")
    assert story["level_detail"] == "scenario"
    # Scenarios reason through open questions, not vocab drills.
    assert any(ex["type"] in ("open", "discussion") for ex in story["exercises"])


# --- schema strictness: the required surface ------------------------------------


@pytest.mark.parametrize(
    "field",
    ["schema_version", "kind", "id", "subject", "title", "level", "body", "glossary", "exercises"],
)
def test_story_missing_required_field_fails(field: str) -> None:
    story = _story("french")
    del story[field]
    assert contract.validate(story, "story") != [], f"story without '{field}' must fail"


def test_story_bad_level_fails() -> None:
    story = _story("french")
    story["level"] = "A1"  # CEFR detail belongs in level_detail, not level
    assert contract.validate(story, "story") != []


def test_story_requires_at_least_one_exercise() -> None:
    story = _story("french")
    story["exercises"] = []
    assert contract.validate(story, "story") != []


def test_story_glossary_entries_are_structured() -> None:
    story = _story("french")
    story["glossary"] = ["le marché = the market"]  # strings, not term/definition objects
    assert contract.validate(story, "story") != []


def test_story_future_schema_version_fails() -> None:
    story = _story("french")
    story["schema_version"] = "2.0"
    assert contract.validate(story, "story") != []


# --- the reserved audio slot ------------------------------------------------------


def test_story_audio_slot_accepts_null_and_object() -> None:
    story = _story("french")
    story["audio"] = None
    assert contract.validate(story, "story") == []
    story["audio"] = {"url": "https://example.org/a.mp3", "duration_seconds": 42.5}
    assert contract.validate(story, "story") == []


def test_story_audio_slot_rejects_bare_string() -> None:
    story = _story("french")
    story["audio"] = "https://example.org/a.mp3"
    assert contract.validate(story, "story") != []


# --- story_read wraps the same schema ---------------------------------------------


def test_story_read_payload_embeds_a_contract_story() -> None:
    payload = {
        "schema_version": contract.CONTRACT_VERSION,
        "kind": "story_read",
        "subject": "french",
        "learner": "ori",
        "story": _story("french"),
        "directive": {
            "instructions": ["Present the story one paragraph at a time."],
            "record_with": ["french record --item food-vocab --result pass"],
        },
    }
    assert contract.validate(payload, "story_read") == []
    broken = copy.deepcopy(payload)
    del broken["story"]["body"]
    assert contract.validate(broken, "story_read") != []
