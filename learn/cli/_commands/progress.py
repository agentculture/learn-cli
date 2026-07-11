"""``learn progress [subject]`` — cross-subject learning standing.

For each registered (and installed) subject, drives its own ``progress --json``
subprocess for the authoritative facts (items total/touched/mastered, its
mastery map, and its own within-subject ``next``), then blends those facts with
the local ledger via :mod:`learn.motivation` for the numbers only the ledger
can produce: per-exercise scores and day-based streaks. A subject that isn't
installed is reported ``available: false`` rather than failing the whole
command — this is read-only and must stay useful with zero subject CLIs on
PATH (the local ledger alone still yields per-subject scores/streaks for
whatever was recorded through ``learn record``).

Anonymous-safe: this never manages a learner id of its own. It drives each
subject with no ``--learner`` flag, so a subject resolves its own default
(env var, then OS user) exactly as if run directly by hand.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any, Optional

from learn import motivation as m
from learn.cli._errors import EXIT_SUCCESS, CliError
from learn.cli._output import emit_result
from learn.profile import read_ledger
from learn.subjects import SubjectEntry, get_subject, is_available, load_registry
from learn.subjects.driver import run_subject_verb


def _drive(entry: SubjectEntry) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Drive ``<subject> progress --json``; never raises — errors come back as a message."""
    if not is_available(entry):
        return None, "subject CLI is not installed"
    try:
        return run_subject_verb(entry, ("progress",)), None
    except CliError as err:
        return None, err.message


def _mastery_overrides(
    payload: Optional[dict[str, Any]], subject: str
) -> dict[tuple[str, str], str]:
    if not payload:
        return {}
    return {(subject, item_id): level for item_id, level in (payload.get("mastery") or {}).items()}


def _subject_fact(payload: Optional[dict[str, Any]], subject: str) -> Optional[dict[str, Any]]:
    if payload is None:
        return None
    return {
        "subject": subject,
        "items_total": payload.get("items_total"),
        "items_mastered": payload.get("items_mastered"),
        "done": bool((payload.get("next") or {}).get("done", False)),
    }


def _streak_dict(streak: Optional[m.Streak]) -> dict[str, Any]:
    if streak is None:
        streak = m.Streak(current_days=0, longest_days=0, last_active=None, active_today=False)
    return {
        "current_days": streak.current_days,
        "longest_days": streak.longest_days,
        "last_active": streak.last_active,
        "active_today": streak.active_today,
    }


def _row(
    entry: SubjectEntry, payload: Optional[dict[str, Any]], error: Optional[str]
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "subject": entry.name,
        "display_name": entry.display_name,
        "available": payload is not None,
    }
    if error:
        row["note"] = error
    if payload is not None:
        row["items_total"] = payload.get("items_total")
        row["items_touched"] = payload.get("items_touched")
        row["items_mastered"] = payload.get("items_mastered")
        row["mastery"] = payload.get("mastery", {})
        row["done"] = bool((payload.get("next") or {}).get("done", False))
        row["next"] = payload.get("next")
    return row


def _render_text(result: dict[str, Any]) -> str:
    lines = ["learn progress", ""]
    for row in result["subjects"]:
        mark = "installed" if row["available"] else "not installed"
        lines.append(f"{row['subject']} — {row['display_name']} [{mark}]")
        if row.get("note"):
            lines.append(f"  note: {row['note']}")
        if row["available"]:
            lines.append(
                f"  items: {row.get('items_touched')}/{row.get('items_total')} touched, "
                f"{row.get('items_mastered')} mastered (done: {row.get('done')})"
            )
        if row.get("score") is not None:
            lines.append(f"  score: {row['score']}")
        streak = row["streak"]
        lines.append(
            f"  streak: {streak['current_days']}d current / {streak['longest_days']}d longest"
        )
        if row.get("item_history"):
            lines.append(f"  ledger items: {len(row['item_history'])}")
    overall = result["overall"]
    lines.append("")
    lines.append(
        f"overall streak: {overall['streak']['current_days']}d current / "
        f"{overall['streak']['longest_days']}d longest ({overall['ledger_rows']} ledger rows)"
    )
    return "\n".join(lines)


def cmd_progress(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    now = datetime.now(timezone.utc)

    subject_arg = getattr(args, "subject", None)
    entries: tuple[SubjectEntry, ...] = (
        (get_subject(subject_arg),) if subject_arg else load_registry()
    )

    ledger_rows = read_ledger()

    rows: list[dict[str, Any]] = []
    subject_facts: list[dict[str, Any]] = []
    mastery_overrides: dict[tuple[str, str], str] = {}
    for entry in entries:
        payload, error = _drive(entry)
        rows.append(_row(entry, payload, error))
        fact = _subject_fact(payload, entry.name)
        if fact is not None:
            subject_facts.append(fact)
        mastery_overrides.update(_mastery_overrides(payload, entry.name))

    # The blend: subject-authoritative mastery (when known) overrides the
    # ledger's own never-regress inference, per item — this is what lets an
    # item recorded before the subject reported it (or vice versa) still show
    # one consistent mastery level in `item_history` below.
    state = m.build_state(ledger_rows, subjects=subject_facts, mastery=mastery_overrides)
    streak_report = m.streaks(ledger_rows, now)

    for row in rows:
        subject_ledger = [r for r in ledger_rows if r.get("subject") == row["subject"]]
        row["score"] = m.mean_score(subject_ledger) if subject_ledger else None
        row["streak"] = _streak_dict(streak_report.by_subject.get(row["subject"]))
        row["item_history"] = [
            {
                "item_id": item.item_id,
                "mastery": item.mastery,
                "last_seen": item.last_seen.isoformat(),
                "entry_count": item.entry_count,
                "last_result": item.last_result,
            }
            for item in state.items
            if item.subject == row["subject"]
        ]

    result = {
        "subjects": rows,
        "overall": {
            "streak": _streak_dict(streak_report.overall),
            "ledger_rows": len(ledger_rows),
        },
    }

    if json_mode:
        emit_result(result, json_mode=True)
    else:
        emit_result(_render_text(result), json_mode=False)
    return EXIT_SUCCESS


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "progress",
        help="Cross-subject learning standing (blends each subject's facts with the local ledger).",
    )
    p.add_argument(
        "subject",
        nargs="?",
        help="Limit to one registered subject (default: every registered subject).",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_progress)
