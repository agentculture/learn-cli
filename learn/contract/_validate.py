"""Minimal stdlib JSON-Schema validator for the subject-plugin contract.

The runtime package carries zero third-party dependencies, so contract payloads
are validated with this module instead of the ``jsonschema`` package. It
implements exactly the keyword subset the shipped schemas use — pinned by
:data:`SUPPORTED_KEYWORDS` and guarded by a test that walks every schema with
:func:`unsupported_keywords`, so a schema can never quietly rely on a keyword
this validator ignores.

Semantics follow JSON Schema draft 2020-12 for the supported subset:

* ``type`` — a name or list of names; ``integer``/``number`` exclude booleans
  (Python ``bool`` is an ``int`` subclass, JSON's is not).
* ``$ref`` — two forms only: local ``#/$defs/<name>`` pointers, and sibling
  schema files (``story.json``) resolved through the ``loader`` callable.
* ``pattern`` — an unanchored regex search, per the spec.
* ``additionalProperties`` — when a schema object, it validates the values of
  properties not named in ``properties`` (used for mastery maps).
"""

from __future__ import annotations

import re
from typing import Any, Callable

# A loader maps a sibling-file ref ("story.json") to its parsed schema, or None.
Loader = Callable[[str], "dict[str, Any] | None"]

#: The ``$defs`` keyword name (draft 2020-12's local-definitions container),
#: named once since it recurs across the keyword set, the local-$ref resolver,
#: and the keyword walker.
_DEFS = "$defs"

SUPPORTED_KEYWORDS = frozenset(
    {
        # validation
        "type",
        "enum",
        "const",
        "pattern",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minItems",
        "minimum",
        "minLength",
        # combinators / references
        "anyOf",
        "not",
        "$ref",
        _DEFS,
        # annotations (ignored by validation)
        "$schema",
        "$id",
        "title",
        "description",
        "examples",
        "default",
        "deprecated",
    }
)

_SIMPLE_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _matches_type(value: Any, name: str) -> bool:
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected = _SIMPLE_TYPES.get(name)
    return expected is not None and isinstance(value, expected)


def validate(
    instance: Any,
    schema: dict[str, Any],
    *,
    loader: Loader | None = None,
) -> list[str]:
    """Validate ``instance`` against ``schema``; return error strings ([] = valid).

    Each error names the failing JSON path (``$.stories[0].level``) and the
    violated rule, so a conformance gate can surface it as a remediation.
    """
    errors: list[str] = []
    _check(instance, schema, schema, "$", errors, loader)
    return errors


def _subcheck(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    loader: Loader | None,
) -> list[str]:
    sub: list[str] = []
    _check(value, schema, root, path, sub, loader)
    return sub


def _resolve_ref(
    ref: str,
    root: dict[str, Any],
    loader: Loader | None,
) -> tuple[dict[str, Any], dict[str, Any]] | str:
    """Resolve ``$ref`` → ``(schema, new_root)``, or an error string."""
    if ref.startswith(f"#/{_DEFS}/"):
        name = ref[len(f"#/{_DEFS}/") :]
        target = root.get(_DEFS, {}).get(name)
        if target is None:
            return f"unresolvable local $ref '{ref}'"
        return target, root
    loaded = loader(ref) if loader is not None else None
    if loaded is None:
        return f"unresolvable $ref '{ref}' (no loader for sibling schema files)"
    return loaded, loaded


def _check_ref(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
    loader: Loader | None,
) -> None:
    """Resolve and recurse through ``$ref``, if present."""
    ref = schema.get("$ref")
    if ref is None:
        return
    resolved = _resolve_ref(ref, root, loader)
    if isinstance(resolved, str):
        errors.append(f"{path}: {resolved}")
    else:
        target, new_root = resolved
        _check(value, target, new_root, path, errors, loader)


def _check_type(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> bool:
    """Check ``type``; return True when it mismatches (caller should stop early)."""
    type_rule = schema.get("type")
    if type_rule is None:
        return False
    names = type_rule if isinstance(type_rule, list) else [type_rule]
    if any(_matches_type(value, n) for n in names):
        return False
    errors.append(f"{path}: expected type {'|'.join(names)}")
    return True


def _check_enum_const(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")


def _check_string(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if not isinstance(value, str):
        return
    pattern = schema.get("pattern")
    if pattern is not None and re.search(pattern, value) is None:
        errors.append(f"{path}: {value!r} does not match pattern {pattern!r}")
    min_length = schema.get("minLength")
    if min_length is not None and len(value) < min_length:
        errors.append(f"{path}: shorter than minLength {min_length}")


def _check_numeric(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if not (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return
    minimum = schema.get("minimum")
    if minimum is not None and value < minimum:
        errors.append(f"{path}: {value} is below minimum {minimum}")


def _check_object(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
    loader: Loader | None,
) -> None:
    if not isinstance(value, dict):
        return
    for key in schema.get("required", []):
        if key not in value:
            errors.append(f"{path}: missing required property '{key}'")
    properties = schema.get("properties", {})
    for key, subschema in properties.items():
        if key in value:
            _check(value[key], subschema, root, f"{path}.{key}", errors, loader)
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        for key, item in value.items():
            if key not in properties:
                _check(item, additional, root, f"{path}.{key}", errors, loader)
    elif additional is False:
        for key in value:
            if key not in properties:
                errors.append(f"{path}: additional property '{key}' is not allowed")


def _check_array(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
    loader: Loader | None,
) -> None:
    if not isinstance(value, list):
        return
    min_items = schema.get("minItems")
    if min_items is not None and len(value) < min_items:
        errors.append(f"{path}: fewer than minItems {min_items}")
    items = schema.get("items")
    if items is not None:
        for i, element in enumerate(value):
            _check(element, items, root, f"{path}[{i}]", errors, loader)


def _check_any_of(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
    loader: Loader | None,
) -> None:
    any_of = schema.get("anyOf")
    if any_of is None:
        return
    if all(_subcheck(value, option, root, path, loader) for option in any_of):
        errors.append(f"{path}: does not match any allowed variant (anyOf)")


def _check_not(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
    loader: Loader | None,
) -> None:
    negated = schema.get("not")
    if negated is not None and not _subcheck(value, negated, root, path, loader):
        errors.append(f"{path}: matches a forbidden shape (not)")


def _check(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
    loader: Loader | None,
) -> None:
    _check_ref(value, schema, root, path, errors, loader)

    if _check_type(value, schema, path, errors):
        return  # structure is wrong; per-keyword checks below would misfire

    _check_enum_const(value, schema, path, errors)
    _check_string(value, schema, path, errors)
    _check_numeric(value, schema, path, errors)
    _check_object(value, schema, root, path, errors, loader)
    _check_array(value, schema, root, path, errors, loader)
    _check_any_of(value, schema, root, path, errors, loader)
    _check_not(value, schema, root, path, errors, loader)


def unsupported_keywords(schema: dict[str, Any]) -> set[str]:
    """Every keyword in ``schema`` (recursively) this validator does not implement.

    The contract test suite asserts this returns an empty set for every shipped
    schema — the guard that keeps schemas within the validated subset.
    """
    found: set[str] = set()
    _walk_keywords(schema, found)
    return found


def _walk_keyword_map(value: Any, found: set[str]) -> None:
    """Recurse into a keyword whose value is a name → subschema map."""
    if not isinstance(value, dict):
        return
    for sub in value.values():
        if isinstance(sub, dict):
            _walk_keywords(sub, found)


def _walk_keyword_list(value: Any, found: set[str]) -> None:
    """Recurse into a keyword whose value is a list of subschemas."""
    if not isinstance(value, list):
        return
    for sub in value:
        if isinstance(sub, dict):
            _walk_keywords(sub, found)


def _walk_keyword_value(key: str, value: Any, found: set[str]) -> None:
    """Recurse into ``value`` per the shape its keyword ``key`` implies."""
    if key in ("properties", _DEFS):
        _walk_keyword_map(value, found)
    elif key in ("items", "not", "additionalProperties") and isinstance(value, dict):
        _walk_keywords(value, found)
    elif key == "anyOf":
        _walk_keyword_list(value, found)


def _walk_keywords(schema: dict[str, Any], found: set[str]) -> None:
    for key, value in schema.items():
        if key not in SUPPORTED_KEYWORDS:
            found.add(key)
        _walk_keyword_value(key, value, found)
