"""The subject-plugin contract: versioned schemas + validator, as package data.

This package is the machine-readable half of the contract documented in
``docs/specs/subject-plugin-contract.md``. It ships:

* ``schemas/*.json`` — one JSON Schema per tutor-verb payload, plus the shared
  ``story`` content schema and the ``error`` stderr shape. These are package
  data, loadable from the installed wheel, so ``learn subject doctor`` (t3) can
  validate a subject CLI's ``--json`` output against them at runtime.
* :func:`validate` — stdlib-only validation (no third-party ``jsonschema``;
  runtime dependencies stay empty).

Shared vocabularies (:data:`MASTERY_LEVELS`, :data:`RESULTS`,
:data:`STORY_LEVELS`) are re-exported here so learn-cli's motivation layer (t9)
and the conformance gate agree with the schemas by construction.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from learn.contract._validate import validate as _validate_instance

#: The contract version this package ships. Payloads carry it as
#: ``schema_version``; subjects pin it via ``doctor``'s ``contract_version``.
#: Minor bumps (1.x) are additive-only; a major bump is a breaking change.
CONTRACT_VERSION = "1.0"

#: Ordered mastery ladder every subject reports per item (culture-guide's
#: proven shape, generalized). Index = how well-understood.
MASTERY_LEVELS: tuple[str, ...] = ("unknown", "introduced", "practiced", "mastered")

#: Raw result vocabulary the driver records back. Subjects report these —
#: never numeric scores; learn-cli's motivation layer computes scores.
RESULTS: tuple[str, ...] = ("pass", "partial", "fail")

#: Difficulty ladder for stories (graded readers and narrative scenarios).
STORY_LEVELS: tuple[str, ...] = ("beginner", "intermediate", "advanced")

#: Every schema shipped by this contract version (stem of the ``schemas/*.json``
#: file). ``story`` is the shared content schema; the rest are verb payloads
#: except ``error``, the stderr error shape.
SCHEMA_NAMES: tuple[str, ...] = (
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
)


def _schemas_root() -> Any:
    return resources.files(__package__).joinpath("schemas")


def list_schemas() -> tuple[str, ...]:
    """The schema names present on disk, sorted (should equal SCHEMA_NAMES)."""
    root = _schemas_root()
    return tuple(
        sorted(
            entry.name[: -len(".json")] for entry in root.iterdir() if entry.name.endswith(".json")
        )
    )


def load_schema(name: str) -> dict[str, Any]:
    """Load a contract schema by name (e.g. ``"story"``).

    Raises :class:`KeyError` for a name outside :data:`SCHEMA_NAMES` so callers
    fail loudly on typos rather than reading an unshipped file.
    """
    if name not in SCHEMA_NAMES:
        raise KeyError(f"unknown contract schema '{name}' (valid: {', '.join(SCHEMA_NAMES)})")
    text = _schemas_root().joinpath(f"{name}.json").read_text(encoding="utf-8")
    return json.loads(text)


def _loader(ref: str) -> dict[str, Any] | None:
    """Resolve a sibling-file ``$ref`` (``story.json``) to its schema."""
    stem = ref[: -len(".json")] if ref.endswith(".json") else ref
    if stem in SCHEMA_NAMES:
        return load_schema(stem)
    return None


def validate(instance: Any, schema_name: str) -> list[str]:
    """Validate a payload against a named contract schema; [] means valid."""
    return _validate_instance(instance, load_schema(schema_name), loader=_loader)
