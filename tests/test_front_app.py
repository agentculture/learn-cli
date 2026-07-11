"""The agentfront App registry + its tools driving subjects over MCP.

Proves the App wraps the same operations the CLI uses (subject registry +
subprocess driving, never importing subject code) and that an agent can run a
full learning loop through ``call_mcp`` — list, read a story, get a lesson,
practice, and record — plus that failures surface as structured MCP errors.
"""

from __future__ import annotations

import pytest
from agentfront.testing import call_mcp

from learn.front import build_app
from tests.conftest import entry


@pytest.fixture
def fourth_app(install_registry, conformant_prefix):
    """An App whose only registered subject is the installed conformant fixture."""
    install_registry([entry("fourthlang", conformant_prefix)])
    return build_app()


# --- registry contents ------------------------------------------------------


def test_app_docs_and_tools(fourth_app) -> None:
    assert fourth_app.name == "learn"
    assert {d.slug for d in fourth_app.list_docs()} == {
        "portal",
        "subject-plugin-contract",
        "subjects",
    }
    assert {t.name for t in fourth_app.list_tools()} == {
        "subjects_list",
        "subject_doctor",
        "story_list",
        "story_read",
        "progress",
        "advice",
        "lesson_next",
        "practice",
        "record",
    }


def test_contract_doc_is_generated_from_package_data(fourth_app) -> None:
    doc = fourth_app.get_doc("subject-plugin-contract")
    assert doc is not None
    # Generated from learn.contract: version + vocabularies are present.
    assert "1.0" in doc.text
    assert "unknown → introduced → practiced → mastered" in doc.text


# --- the tools drive subjects ----------------------------------------------


def test_subjects_list_tool(fourth_app) -> None:
    result = call_mcp(fourth_app, ["subjects_list"], {})["result"]
    assert result["count"] == 1
    row = result["subjects"][0]
    assert row["name"] == "fourthlang"
    assert row["available"] is True


def test_subject_doctor_tool(fourth_app) -> None:
    result = call_mcp(fourth_app, ["subject_doctor"], {"subject": "fourthlang"})["result"]
    assert result["kind"] == "subject_doctor"
    assert result["healthy"] is True


def test_learning_loop_over_mcp(fourth_app) -> None:
    stories = call_mcp(fourth_app, ["story_list"], {"subject": "fourthlang"})["result"]["stories"]
    assert [s["id"] for s in stories] == ["s1", "dev-smoke"]

    read = call_mcp(fourth_app, ["story_read"], {"subject": "fourthlang", "story_id": "s1"})
    assert read["result"]["kind"] == "story_read"
    assert read["result"]["story"]["id"] == "s1"

    lesson = call_mcp(fourth_app, ["lesson_next"], {"subject": "fourthlang"})["result"]
    assert lesson["kind"] == "lesson_directive"

    practice = call_mcp(fourth_app, ["practice"], {"subject": "fourthlang"})["result"]
    assert practice["kind"] == "practice_directive"

    rec = call_mcp(
        fourth_app,
        ["record"],
        {
            "subject": "fourthlang",
            "item_id": "greetings",
            "result": "pass",
            "activity": "story",
            "exercise_id": "s1-q1",
        },
    )["result"]
    assert rec["kind"] == "record_ack"
    assert rec["mastery"]["level"] == "mastered"


def test_advice_and_progress_tools(fourth_app) -> None:
    advice = call_mcp(fourth_app, ["advice"], {"subject": "fourthlang", "learner": "ori"})["result"]
    assert advice["kind"] == "advice"
    progress = call_mcp(fourth_app, ["progress"], {"subject": "fourthlang"})["result"]
    assert progress["kind"] == "progress"


def test_record_with_counts(fourth_app) -> None:
    rec = call_mcp(
        fourth_app,
        ["record"],
        {
            "subject": "fourthlang",
            "item_id": "greetings",
            "result": "partial",
            "activity": "practice",
            "correct": 1,
            "total": 2,
        },
    )["result"]
    assert rec["recorded"]["correct"] == 1
    assert rec["recorded"]["total"] == 2
    assert rec["mastery"]["level"] == "practiced"


def test_story_list_level_filter(fourth_app) -> None:
    hit = call_mcp(fourth_app, ["story_list"], {"subject": "fourthlang", "level": "beginner"})
    assert len(hit["result"]["stories"]) == 2  # raw list includes the dev- fixture story
    miss = call_mcp(fourth_app, ["story_list"], {"subject": "fourthlang", "level": "advanced"})
    assert miss["result"]["stories"] == []


# --- structured errors ------------------------------------------------------


def test_unknown_subject_is_user_error(fourth_app) -> None:
    err = call_mcp(fourth_app, ["progress"], {"subject": "nope"})["error"]
    assert err["code"] == 1
    assert "unknown subject" in err["message"]
    assert err["remediation"]


def test_uninstalled_subject_is_env_error(install_registry) -> None:
    install_registry([entry("french", ["definitely-not-installed-xyz"])])
    app = build_app()
    err = call_mcp(app, ["progress"], {"subject": "french"})["error"]
    assert err["code"] == 2
    assert "not installed" in err["message"]


def test_unknown_story_id_propagates_subject_error(fourth_app) -> None:
    err = call_mcp(fourth_app, ["story_read"], {"subject": "fourthlang", "story_id": "nope"})[
        "error"
    ]
    # The subject exits 1 with the contract error shape; the driver preserves it.
    assert err["code"] == 1
    assert "unknown story" in err["message"]


# --- criterion 1: 'learn subjects --json' still lists conformant subjects ----


def test_learn_subjects_json_still_lists_conformant(
    install_registry, conformant_prefix, capsys
) -> None:
    import json

    from learn.cli import main

    install_registry([entry("fourthlang", conformant_prefix)])
    rc = main(["subjects", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["subjects"][0]["name"] == "fourthlang"
    assert payload["subjects"][0]["available"] is True
