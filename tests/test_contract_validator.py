"""Unit tests for the stdlib mini JSON-Schema validator behind the subject contract.

The runtime package has zero third-party dependencies, so the contract ships its
own validator (:mod:`learn.contract._validate`) supporting exactly the keyword
subset the contract schemas use. These tests pin that subset's semantics.
"""

from __future__ import annotations

from learn.contract._validate import SUPPORTED_KEYWORDS, unsupported_keywords, validate

# --- type ------------------------------------------------------------------


def test_type_string_ok() -> None:
    assert validate("hello", {"type": "string"}) == []


def test_type_mismatch_reports_path() -> None:
    errors = validate({"a": 1}, {"type": "object", "properties": {"a": {"type": "string"}}})
    assert len(errors) == 1
    assert "$.a" in errors[0]


def test_bool_is_not_integer() -> None:
    assert validate(True, {"type": "integer"}) != []
    assert validate(1, {"type": "integer"}) == []


def test_bool_is_not_number() -> None:
    assert validate(True, {"type": "number"}) != []
    assert validate(1.5, {"type": "number"}) == []
    assert validate(2, {"type": "number"}) == []


def test_type_union_accepts_null() -> None:
    schema = {"type": ["object", "null"]}
    assert validate(None, schema) == []
    assert validate({}, schema) == []
    assert validate("x", schema) != []


# --- required / properties / additionalProperties ---------------------------


def test_required_missing() -> None:
    errors = validate({}, {"type": "object", "required": ["id"]})
    assert errors and "id" in errors[0]


def test_additional_properties_schema_validates_values() -> None:
    schema = {"type": "object", "additionalProperties": {"enum": ["a", "b"]}}
    assert validate({"x": "a", "y": "b"}, schema) == []
    assert validate({"x": "nope"}, schema) != []


# --- enum / const / pattern / bounds ----------------------------------------


def test_enum() -> None:
    schema = {"enum": ["pass", "partial", "fail"]}
    assert validate("pass", schema) == []
    assert validate("mastered", schema) != []


def test_const() -> None:
    schema = {"const": "story"}
    assert validate("story", schema) == []
    assert validate("lesson", schema) != []


def test_pattern() -> None:
    schema = {"type": "string", "pattern": "^1\\.[0-9]+$"}
    assert validate("1.0", schema) == []
    assert validate("2.0", schema) != []


def test_min_length_and_minimum_and_min_items() -> None:
    assert validate("", {"type": "string", "minLength": 1}) != []
    assert validate(-1, {"type": "integer", "minimum": 0}) != []
    assert validate([], {"type": "array", "minItems": 1}) != []
    assert validate(["x"], {"type": "array", "minItems": 1}) == []


def test_items_schema_applies_to_every_element() -> None:
    schema = {"type": "array", "items": {"type": "string"}}
    assert validate(["a", "b"], schema) == []
    errors = validate(["a", 3], schema)
    assert errors and "$[1]" in errors[0]


# --- combinators -------------------------------------------------------------


def test_any_of() -> None:
    schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert validate("x", schema) == []
    assert validate(None, schema) == []
    assert validate(3, schema) != []


def test_not() -> None:
    schema = {"type": "object", "not": {"required": ["score"]}}
    assert validate({"result": "pass"}, schema) == []
    assert validate({"score": 0.9}, schema) != []


# --- $ref --------------------------------------------------------------------


def test_local_defs_ref() -> None:
    schema = {
        "$defs": {"slug": {"type": "string", "pattern": "^[a-z-]+$"}},
        "type": "object",
        "properties": {"id": {"$ref": "#/$defs/slug"}},
    }
    assert validate({"id": "ok-slug"}, schema) == []
    assert validate({"id": "Not A Slug"}, schema) != []


def test_cross_file_ref_uses_loader() -> None:
    other = {"type": "object", "required": ["title"]}
    schema = {"type": "object", "properties": {"story": {"$ref": "other.json"}}}
    loader = {"other.json": other}.get
    assert validate({"story": {"title": "x"}}, schema, loader=loader) == []
    assert validate({"story": {}}, schema, loader=loader) != []


def test_cross_file_ref_without_loader_errors() -> None:
    schema = {"$ref": "missing.json"}
    errors = validate({}, schema)
    assert errors and "missing.json" in errors[0]


# --- keyword guard ------------------------------------------------------------


def test_unsupported_keywords_detected() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"oneOf": [{"type": "string"}]}},
    }
    assert "oneOf" in unsupported_keywords(schema)


def test_supported_schema_reports_nothing() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"x": {"type": "string"}},
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/x"}},
        "required": ["a"],
    }
    assert unsupported_keywords(schema) == set()


def test_supported_keywords_is_frozen_contract() -> None:
    # The guard test over shipped schemas relies on this set staying explicit.
    assert "oneOf" not in SUPPORTED_KEYWORDS
    assert "$ref" in SUPPORTED_KEYWORDS
