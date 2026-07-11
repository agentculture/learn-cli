"""The cross-surface agreement gate — CLI, MCP, and HTTP enumerate identically.

This is the acceptance-criterion-1 proof: the three faces learn-cli derives from
one agentfront App cannot present different sets of docs/tools. It runs
agentfront's own dogfood check (``surfaces_agree`` / ``assert_surfaces_agree``)
against ``learn.front.build_app()``.

``agentfront[mcp]`` is a runtime dependency of learn-cli, so this normally never
skips; the ``importorskip`` only degrades gracefully (with a reason) if a
stripped environment lacks agentfront rather than hard-failing collection.
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "agentfront.testing",
    reason="agentfront[mcp] is a learn-cli runtime dependency; skip only if it is unavailable",
)

from agentfront.serve import surface_inventory  # noqa: E402
from agentfront.testing import assert_surfaces_agree  # noqa: E402

from learn.front import build_app  # noqa: E402

_EXPECTED_TOOLS = {
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
_EXPECTED_DOCS = {"portal", "subject-plugin-contract", "subjects"}


def test_surfaces_agree() -> None:
    # Raises AssertionError naming any drift; returns None when all faces agree.
    assert_surfaces_agree(build_app())


def test_cli_mcp_http_enumerate_identically() -> None:
    inv = surface_inventory(build_app())
    # Tools: registry == CLI == MCP == TAUI.
    assert inv["registry_tools"] == _EXPECTED_TOOLS
    assert inv["cli_tools"] == inv["mcp_tools"] == inv["registry_tools"]
    assert inv["taui_tools"] == inv["registry_tools"]
    # Docs: registry == HTTP == CLI.
    assert inv["registry_docs"] == _EXPECTED_DOCS
    assert inv["http_docs"] == inv["cli_docs"] == inv["registry_docs"]


def test_registry_override_flows_into_the_app(install_registry, conformant_prefix) -> None:
    from tests.conftest import entry

    install_registry([entry("fourthlang", conformant_prefix)])
    app = build_app()
    # The subjects catalog doc reflects the overridden registry.
    subjects_doc = app.get_doc("subjects")
    assert subjects_doc is not None
    assert "fourthlang" in subjects_doc.text
    # Tools are registry-independent (the same nine drive whatever is registered).
    assert {"/".join(list(t.group) + [t.name]) for t in app.list_tools()} == _EXPECTED_TOOLS
