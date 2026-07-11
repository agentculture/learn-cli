"""``learn record <subject> --item <id> --result pass|partial|fail ...``

Proxies a graded outcome to the subject's own ``record`` verb — the subject
stays the source of truth for its mastery ladder (per the subject-plugin
contract, §3.7) — then appends the acknowledged ``recorded`` object to the
local cross-subject ledger (the input the motivation layer scores/streaks
from), and, when signed in, makes a best-effort push of every unsynced ledger
row to the learn API. A network failure during that push never fails the
command: ``learn record`` always succeeds once the subject has acked and the
row is ledgered locally, and the payload's ``sync`` block reports what
happened (or didn't).
"""

from __future__ import annotations

import argparse

from learn.cli._errors import EXIT_ENV_ERROR, EXIT_SUCCESS, CliError
from learn.cli._output import emit_result
from learn.contract import validate
from learn.profile import append_ledger, load_auth, pending_sync_count, push_pending
from learn.subjects import get_subject
from learn.subjects.driver import run_subject_verb

_RESULTS = ("pass", "partial", "fail")
_ACTIVITIES = ("lesson", "practice", "story")


def _extra_args(args: argparse.Namespace) -> tuple[str, ...]:
    extra: list[str] = ["--item", args.item, "--result", args.result, "--activity", args.activity]
    if args.exercise:
        extra += ["--exercise", args.exercise]
    if args.story:
        extra += ["--story", args.story]
    if args.lesson:
        extra += ["--lesson", args.lesson]
    if args.correct is not None:
        extra += ["--correct", str(args.correct)]
    if args.total is not None:
        extra += ["--total", str(args.total)]
    if args.duration_seconds is not None:
        extra += ["--duration-seconds", str(args.duration_seconds)]
    if args.notes:
        extra += ["--notes", args.notes]
    return tuple(extra)


def cmd_record(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    entry = get_subject(args.subject)  # unknown subject -> user error (exit 1)

    payload = run_subject_verb(entry, ("record",), extra_args=_extra_args(args))

    errors = validate(payload, "record")
    if errors:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"subject '{entry.name}' emitted a non-conformant record_ack: {errors[0]}",
            remediation=f"run 'learn subject doctor {entry.name}' to check conformance",
        )

    recorded = dict(payload["recorded"])
    append_ledger({"subject": entry.name, **recorded})

    auth_state = load_auth()
    if auth_state is not None:
        sync_result = push_pending(auth_state.token)
        sync_payload = {"signed_in": True, **sync_result.to_dict()}
    else:
        sync_payload = {
            "signed_in": False,
            "ok": True,
            "attempted": 0,
            "synced": 0,
            "pending": pending_sync_count(),
            "error": None,
        }

    result = {
        "subject": entry.name,
        "recorded": recorded,
        "mastery": payload.get("mastery"),
        "next": payload.get("next"),
        "sync": sync_payload,
    }

    if json_mode:
        emit_result(result, json_mode=True)
    else:
        mastery_level = (payload.get("mastery") or {}).get("level")
        emit_result(
            f"recorded {recorded.get('item_id')} = {recorded.get('result')} for {entry.name} "
            f"(mastery: {mastery_level})",
            json_mode=False,
        )
    return EXIT_SUCCESS


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "record",
        help="Record a graded outcome: proxies to the subject CLI, then ledgers it locally.",
    )
    p.add_argument("subject", help="Registered subject id (see 'learn subjects').")
    p.add_argument("--item", required=True, help="Item id being graded.")
    p.add_argument("--result", required=True, choices=_RESULTS, help="Raw grading outcome.")
    p.add_argument(
        "--activity",
        choices=_ACTIVITIES,
        default="practice",
        help="Which activity produced this result (default: practice).",
    )
    p.add_argument("--exercise", help="Exercise id, when the activity is scoped to one.")
    p.add_argument("--story", help="Story id, when the activity is a story.")
    p.add_argument("--lesson", help="Lesson id, when the activity is a lesson.")
    p.add_argument("--correct", type=int, help="Raw count of correct responses, when countable.")
    p.add_argument("--total", type=int, help="Raw count of graded responses, when countable.")
    p.add_argument("--duration-seconds", type=float, dest="duration_seconds", help="Time on task.")
    p.add_argument("--notes", help="Free-text note to attach to the record.")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_record)
