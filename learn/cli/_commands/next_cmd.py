"""``learn next`` — the single best cross-subject action right now.

A thin CLI wrapper over :func:`learn.motivation.what_next`: folds every
registered+installed subject's own ``progress`` facts (so the layer knows which
subjects still have new material) together with the local ledger, and renders
the one typed :class:`~learn.motivation.Recommendation` it returns — never
``None``, even for a learner who has mastered everything (the never-ending
maintenance mode).

Fully offline: with zero subjects installed and an empty ledger, every subject
is treated as "unknown, assume more remains" (the layer's own documented
default), so ``learn next`` still returns a sensible recommendation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from learn import motivation as m
from learn.cli._errors import EXIT_SUCCESS, CliError
from learn.cli._output import emit_result
from learn.profile import read_ledger
from learn.subjects import is_available, load_registry
from learn.subjects.driver import run_subject_verb


def _subject_facts() -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for entry in load_registry():
        if not is_available(entry):
            continue
        try:
            payload = run_subject_verb(entry, ("progress",))
        except CliError:
            continue  # an unhealthy subject just falls back to "unknown, assume more remains"
        facts.append(
            {
                "subject": entry.name,
                "items_total": payload.get("items_total"),
                "items_mastered": payload.get("items_mastered"),
                "done": bool((payload.get("next") or {}).get("done", False)),
            }
        )
    return facts


def _as_payload(rec: m.Recommendation) -> dict[str, Any]:
    return {
        "action": rec.action.value,
        "mode": rec.mode,
        "reason": rec.reason,
        "subject": rec.subject,
        "item_id": rec.item_id,
        "items": [list(pair) for pair in rec.items],
    }


def cmd_next(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    now = datetime.now(timezone.utc)

    ledger_rows = read_ledger()
    state = m.build_state(ledger_rows, subjects=_subject_facts())
    rec = m.what_next(state, now)

    if json_mode:
        emit_result(_as_payload(rec), json_mode=True)
    else:
        lines = [f"next: {rec.action.value} ({rec.mode})", rec.reason]
        if rec.subject:
            lines.append(f"subject: {rec.subject}")
        if rec.item_id:
            lines.append(f"item: {rec.item_id}")
        if rec.items:
            lines.append("batch: " + ", ".join(f"{s}:{i}" for s, i in rec.items))
        emit_result("\n".join(lines), json_mode=False)
    return EXIT_SUCCESS


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "next",
        help="The single best next action across every subject (learn.motivation.what_next).",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_next)
