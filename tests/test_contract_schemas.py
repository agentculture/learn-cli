"""The machine-readable subject-plugin contract: schemas parse, version, and validate.

Every verb payload schema ships as package data under ``learn/contract/schemas/``
so t3's ``learn subject doctor`` conformance gate can load them from the installed
package. These tests pin:

* every schema file parses and carries ``$id`` + ``title``;
* every payload schema requires a ``schema_version`` field (contract c18);
* schemas stay within the stdlib validator's supported keyword subset;
* one golden example payload per verb validates against its schema.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from learn import contract
from learn.contract._validate import unsupported_keywords

FIXTURES = Path(__file__).parent / "fixtures"

# error.json describes the CliError stderr shape ({code, message, remediation})
# already emitted by the chassis — it predates the contract and carries no
# schema_version of its own.
_NO_SCHEMA_VERSION = {"error"}


# --- inventory ----------------------------------------------------------------


def test_schema_names_match_disk() -> None:
    assert contract.list_schemas() == tuple(sorted(contract.SCHEMA_NAMES))


def test_expected_verb_schemas_present() -> None:
    expected = {
        "overview",
        "progress",
        "advice",
        "story",
        "story_list",
        "story_read",
        "lesson",
        "practice",
        "record",
        "doctor",
        "error",
    }
    assert set(contract.SCHEMA_NAMES) == expected


def test_contract_version_is_1_x() -> None:
    assert contract.CONTRACT_VERSION.startswith("1.")


@pytest.mark.parametrize("name", sorted(contract.SCHEMA_NAMES))
def test_schema_parses_and_self_describes(name: str) -> None:
    schema = contract.load_schema(name)
    assert schema["$id"].endswith(f"/{name}.json")
    assert contract.CONTRACT_VERSION in schema["$id"]
    assert schema["title"]
    assert schema["description"]


@pytest.mark.parametrize("name", sorted(set(contract.SCHEMA_NAMES) - _NO_SCHEMA_VERSION))
def test_payload_schema_requires_schema_version(name: str) -> None:
    schema = contract.load_schema(name)
    assert "schema_version" in schema["required"]
    version_rule = schema["properties"]["schema_version"]
    assert version_rule["pattern"] == "^1\\.[0-9]+$"


@pytest.mark.parametrize("name", sorted(contract.SCHEMA_NAMES))
def test_schema_uses_only_supported_keywords(name: str) -> None:
    assert unsupported_keywords(contract.load_schema(name)) == set()


def test_load_schema_rejects_unknown_name() -> None:
    with pytest.raises(KeyError):
        contract.load_schema("bogus")


# --- golden example payloads ----------------------------------------------------


def _example(name: str) -> dict:
    return json.loads((FIXTURES / "payloads" / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(contract.SCHEMA_NAMES))
def test_example_payload_validates(name: str) -> None:
    errors = contract.validate(_example(name), name)
    assert errors == [], f"{name} example: {errors}"


@pytest.mark.parametrize("name", sorted(set(contract.SCHEMA_NAMES) - _NO_SCHEMA_VERSION))
def test_example_payload_pins_contract_version(name: str) -> None:
    assert _example(name)["schema_version"] == contract.CONTRACT_VERSION


def test_wrong_kind_fails() -> None:
    payload = _example("progress")
    payload["kind"] = "advice"
    assert contract.validate(payload, "progress") != []


def test_future_major_schema_version_fails() -> None:
    payload = _example("progress")
    payload["schema_version"] = "2.0"
    assert contract.validate(payload, "progress") != []


# --- the no-scores rule (c27: subjects report raw results, never scores) --------


@pytest.mark.parametrize("forbidden", ["score", "grade", "points"])
def test_record_ack_with_score_like_field_fails(forbidden: str) -> None:
    payload = copy.deepcopy(_example("record"))
    payload["recorded"][forbidden] = 0.9
    errors = contract.validate(payload, "record")
    assert errors != [], f"record ack must reject raw-result field '{forbidden}'"


def test_record_ack_raw_result_has_no_derived_score() -> None:
    recorded = _example("record")["recorded"]
    for field in ("score", "grade", "points"):
        assert field not in recorded


# --- mastery / result vocabularies are the shared enums --------------------------


def test_progress_mastery_values_use_shared_ladder() -> None:
    schema = contract.load_schema("progress")
    ladder = schema["properties"]["mastery"]["additionalProperties"]["enum"]
    assert tuple(ladder) == contract.MASTERY_LEVELS


def test_record_result_uses_shared_vocabulary() -> None:
    schema = contract.load_schema("record")
    result = schema["properties"]["recorded"]["properties"]["result"]["enum"]
    assert tuple(result) == contract.RESULTS
