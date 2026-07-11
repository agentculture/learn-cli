"""Tests for the data-driven subject registry and the ``learn subjects`` verb.

Cover: the shipped registry registers french/spanish/culture-guide with the
pinned ``argv_prefix`` shapes; the registry API; the ``learn subjects`` list
face; and the two structural guarantees of criterion 3 — deleting a registry
entry removes the subject everywhere, and learn-cli holds no subject content or
progression logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import learn
from learn.cli import main
from learn.cli._errors import CliError
from learn.subjects import SubjectEntry, get_subject, load_registry
from tests.conftest import entry

# --- the shipped registry --------------------------------------------------


def test_shipped_registry_registers_the_three_launch_subjects() -> None:
    names = {e.name for e in load_registry()}
    assert {"french", "spanish", "culture-guide"} <= names


def test_argv_prefix_shapes_match_the_orchestrator_pins() -> None:
    by_name = {e.name: e for e in load_registry()}
    assert by_name["french"].argv_prefix == ("french",)
    assert by_name["spanish"].argv_prefix == ("spanish",)
    # culture-guide mounts the contract verbs under a `subject` noun.
    assert by_name["culture-guide"].argv_prefix == ("culture-guide", "subject")


# --- registry API ----------------------------------------------------------


def test_get_subject_returns_entry() -> None:
    e = get_subject("french")
    assert e.name == "french"
    assert e.contract_version == "1.0"


def test_get_subject_unknown_raises_user_error() -> None:
    with pytest.raises(CliError) as exc:
        get_subject("klingon")
    assert exc.value.code == 1  # user error, not environment
    assert "unknown subject" in exc.value.message


def test_env_override_replaces_the_registry(install_registry, conformant_prefix) -> None:
    install_registry([entry("fourthlang", conformant_prefix)])
    names = {e.name for e in load_registry()}
    assert names == {"fourthlang"}


def test_entry_from_dict_rejects_unknown_keys() -> None:
    # A content-ish key must be rejected — the registry carries metadata only.
    with pytest.raises(CliError) as exc:
        SubjectEntry.from_dict(
            {
                "name": "x",
                "argv_prefix": ["x"],
                "description": "d",
                "repo": "r",
                "stories": [{"id": "s1"}],
            }
        )
    assert exc.value.code == 2  # malformed registry = environment error
    assert "unsupported keys" in exc.value.message


def test_entry_requires_argv_prefix() -> None:
    with pytest.raises(CliError):
        SubjectEntry.from_dict({"name": "x", "description": "d", "repo": "r", "argv_prefix": []})


# --- `learn subjects` list face --------------------------------------------


def test_subjects_json_lists_registry_with_availability(capsys) -> None:
    rc = main(["subjects", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == len(payload["subjects"])
    french = next(s for s in payload["subjects"] if s["name"] == "french")
    assert french["argv_prefix"] == ["french"]
    assert isinstance(french["available"], bool)


def test_subjects_text(capsys) -> None:
    rc = main(["subjects"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "french" in out


# --- criterion 3: no subject content, registry is the sole source ----------


def test_registry_entries_are_metadata_only() -> None:
    metadata = {"name", "display_name", "description", "repo", "argv_prefix", "contract_version"}
    for e in load_registry():
        assert set(e.to_dict()) == metadata
    # No content-ish key can ever appear (unknown keys are rejected at load).
    forbidden = {"stories", "lessons", "exercises", "mastery", "content", "body", "progression"}
    assert SubjectEntry.ALLOWED_KEYS.isdisjoint(forbidden)


def test_package_ships_no_subject_content_files() -> None:
    pkg = Path(learn.__file__).parent
    # The only committed content dirs would be a subject's — learn-cli has none.
    content_dirs = [
        p.name
        for p in pkg.rglob("*")
        if p.is_dir() and p.name in {"stories", "lessons", "exercises", "content"}
    ]
    assert content_dirs == []
    # The only JSON data shipped is contract schemas and the registry itself.
    for j in pkg.rglob("*.json"):
        rel = j.relative_to(pkg).as_posix()
        assert rel.startswith("contract/schemas/") or rel == "subjects/registry.json", rel


def test_deleting_registry_entry_removes_subject_everywhere(
    install_registry, conformant_prefix, capsys
) -> None:
    # Two subjects registered → both listed, both resolvable.
    install_registry([entry("fourthlang", conformant_prefix), entry("fifthlang", ["fifthlang"])])
    payload = json.loads(_subjects_json(capsys))
    assert {s["name"] for s in payload["subjects"]} == {"fourthlang", "fifthlang"}

    # Delete `fifthlang` from the registry data → gone from the list face...
    install_registry([entry("fourthlang", conformant_prefix)])
    payload = json.loads(_subjects_json(capsys))
    assert {s["name"] for s in payload["subjects"]} == {"fourthlang"}

    # ...and gone from the doctor face (unknown subject, user error exit 1).
    rc = main(["subject", "doctor", "fifthlang", "--json"])
    err = capsys.readouterr().err
    assert rc == 1
    assert json.loads(err)["code"] == 1


def _subjects_json(capsys) -> str:
    assert main(["subjects", "--json"]) == 0
    return capsys.readouterr().out
