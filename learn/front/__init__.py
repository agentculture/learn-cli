"""The agentfront App — learn-cli's three faces from one registry.

:func:`build_app` returns an :class:`agentfront.App` whose docs and tools are the
single source the CLI additions (`learn mcp serve`, `learn site serve`,
`learn site export`), the MCP server, and the HTTP site all derive from. Because
every face reads this one registry, they cannot enumerate different things — a
property proven in CI by ``agentfront.serve.surfaces_agree`` (see
``tests/test_surfaces_agree.py``).

The App is a **parallel** registry, not a replacement for learn-cli's hand-rolled
argparse CLI (which passes the agent-first rubric and stays as-is). Its tools wrap
the same underlying operations that CLI uses — the subject registry
(:mod:`learn.subjects`) plus subprocess driving (:mod:`learn.front._driver`) — so
an agent over MCP drives the identical subjects the CLI does, never importing
subject code.

Tools (each read-only-safe except ``record``, the graded write-back that closes
the learning loop): ``subjects_list``, ``subject_doctor``, ``story_list``,
``story_read``, ``progress``, ``advice``, ``lesson_next``, ``practice``,
``record``.
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from agentfront import App
from agentfront.errors import AgentfrontError

from learn import __version__
from learn.cli._errors import CliError
from learn.front import _docs
from learn.front._driver import drive
from learn.subjects import get_subject, is_available, load_registry
from learn.subjects.conformance import run_conformance

__all__ = ["build_app", "TOOL_FUNCS"]

_APP_DESCRIPTION = (
    "learn-cli — the learning portal fronting per-subject tutor CLIs. One registry, "
    "three faces (CLI, MCP, HTTP) for humans and agents to learn a subject step by step."
)


def _tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a tool so a portal :class:`CliError` surfaces as a structured MCP error.

    The tool bodies raise learn-cli's native ``CliError`` (via the subject
    driver); over MCP that must become an :class:`AgentfrontError` so the ``run``
    tool emits the structured ``{code, message, remediation}`` payload instead of
    a flattened generic error. ``functools.wraps`` preserves the name, docstring,
    and signature agentfront reads to build the tool's schema.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except CliError as err:
            raise AgentfrontError(
                code=err.code, message=err.message, remediation=err.remediation
            ) from err

    return wrapper


# --- tools: each wraps the same op the CLI uses (registry + subprocess) --------


def subjects_list() -> dict[str, Any]:
    """List every registered subject and whether its CLI is installed."""
    rows = []
    for entry in load_registry():
        row = entry.to_dict()
        row["available"] = is_available(entry)
        rows.append(row)
    return {"subjects": rows, "count": len(rows)}


def subject_doctor(subject: str) -> dict[str, Any]:
    """Run the subject-plugin conformance gate against a registered subject."""
    return run_conformance(get_subject(subject))


def story_list(subject: str, level: str = "") -> dict[str, Any]:
    """List a subject's stories; optionally filter to one level (beginner/…)."""
    payload = drive(subject, ("story", "list"))
    if level:
        stories = [s for s in payload.get("stories", []) if s.get("level") == level]
        payload = {**payload, "stories": stories}
    return payload


def story_read(subject: str, story_id: str) -> dict[str, Any]:
    """Read one full story from a subject, wrapped in its teaching directive."""
    return drive(subject, ("story", "read"), extra=(story_id,))


def progress(subject: str, learner: str = "") -> dict[str, Any]:
    """Report a learner's within-subject progress on the mastery ladder."""
    return drive(subject, ("progress",), learner=learner or None)


def advice(subject: str, learner: str = "") -> dict[str, Any]:
    """Get a subject's deterministic study advice for a learner."""
    return drive(subject, ("advice",), learner=learner or None)


def lesson_next(subject: str, learner: str = "") -> dict[str, Any]:
    """Get the next lesson directive for a learner (`lesson next`)."""
    return drive(subject, ("lesson", "next"), learner=learner or None)


def practice(subject: str, scope: str = "", learner: str = "") -> dict[str, Any]:
    """Get a batch of practice exercises, optionally scoped to an item/module/review."""
    extra = (scope,) if scope else ()
    return drive(subject, ("practice",), extra=extra, learner=learner or None)


def record(
    subject: str,
    item_id: str,
    result: str,
    activity: str = "practice",
    exercise_id: str = "",
    correct: int = 0,
    total: int = 0,
    learner: str = "",
) -> dict[str, Any]:
    """Write one graded outcome back to a subject (the learning-loop write-back)."""
    extra: list[str] = ["--item", item_id, "--result", result, "--activity", activity]
    if exercise_id:
        extra += ["--exercise", exercise_id]
    if correct:
        extra += ["--correct", str(correct)]
    if total:
        extra += ["--total", str(total)]
    return drive(subject, ("record",), extra=tuple(extra), learner=learner or None)


#: The tool functions, in registration order — also the export/agreement surface.
TOOL_FUNCS: tuple[Callable[..., Any], ...] = (
    subjects_list,
    subject_doctor,
    story_list,
    story_read,
    progress,
    advice,
    lesson_next,
    practice,
    record,
)

#: Doc pages registered into the App: (slug, title, body-generator).
_DOCS: tuple[tuple[str, str, Callable[[], str]], ...] = (
    ("portal", "learn-cli — the learning portal", _docs.portal_doc),
    ("subject-plugin-contract", "The subject-plugin contract", _docs.contract_doc),
    ("subjects", "Subjects catalog", _docs.subjects_doc),
)


def build_app() -> App:
    """Build the learn-cli agentfront App from the current registry + contract.

    A fresh App each call, so a ``LEARN_SUBJECTS_REGISTRY`` override (tests, a
    subject author's local registry) is reflected in the subjects catalog doc and
    the tools every time.
    """
    app = App(name="learn", version=__version__, description=_APP_DESCRIPTION)
    for slug, title, generate in _DOCS:
        app.add_doc(slug=slug, title=title, text=generate())
    for func in TOOL_FUNCS:
        app.tool(_tool(func))
    return app
