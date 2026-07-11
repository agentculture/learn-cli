"""``learn subject`` — the noun fronting per-subject tutor CLIs.

Two verbs today:

* ``subject doctor <name>`` — the **conformance gate**. Drives the registered
  subject's verbs as subprocesses and checks each ``--json`` answer against the
  subject-plugin contract (see :mod:`learn.subjects.conformance`). Emits the
  standard doctor payload and exits 0 when the subject conforms, 2 when it has
  drifted or its executable is missing.
* ``subject overview`` — describes this noun and the registered subjects. The
  agent-first rubric requires an ``overview`` on any noun with action-verbs.

Unknown subject names are a *user* error (exit 1, raised by
:func:`learn.subjects.get_subject`); a drifted or uninstalled subject is an
*environment* error (exit 2).
"""

from __future__ import annotations

import argparse

from learn.cli._commands.overview import emit_overview
from learn.cli._errors import EXIT_ENV_ERROR, EXIT_SUCCESS
from learn.cli._output import emit_result
from learn.subjects import get_subject, is_available, load_registry
from learn.subjects.conformance import run_conformance


def _subject_sections() -> list[dict[str, object]]:
    entries = load_registry()
    listed = [
        f"{e.name} ({e.display_name}) — {'installed' if is_available(e) else 'not installed'}; "
        f"drives `{' '.join(e.argv_prefix)} <verb> --json`"
        for e in entries
    ] or ["(no subjects registered)"]
    return [
        {
            "title": "Verbs",
            "items": [
                "subject doctor <name> — check a subject CLI against the subject-plugin contract",
                "subject overview — describe this noun (you are here)",
            ],
        },
        {"title": "Registered subjects", "items": listed},
        {
            "title": "How subjects are hosted",
            "items": [
                "subjects are registry data, not code — deleting an entry removes it everywhere",
                "learn-cli drives subjects only via subprocess + --json; it never imports them",
                "learn-cli holds no subject content or progression logic — that is the repo's",
            ],
        },
    ]


def cmd_subject_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "learn subject",
        _subject_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return EXIT_SUCCESS


def cmd_subject_doctor(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    entry = get_subject(args.name)  # raises CliError (exit 1) when unknown
    report = run_conformance(entry)
    if json_mode:
        emit_result(report, json_mode=True)
    else:
        status = "conforms" if report["healthy"] else "DRIFTED"
        lines = [f"learn subject doctor {entry.name}: {status}", ""]
        for check in report["checks"]:
            mark = "ok" if check["passed"] else "FAIL"
            lines.append(f"[{mark}] {check['id']}: {check['message']}")
            if not check["passed"] and check["remediation"]:
                lines.append(f"  hint: {check['remediation']}")
        emit_result("\n".join(lines), json_mode=False)
    return EXIT_SUCCESS if report["healthy"] else EXIT_ENV_ERROR


def _no_verb(args: argparse.Namespace) -> int:
    # `learn subject` with no sub-verb prints the noun's overview.
    return cmd_subject_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "subject",
        help="Host and check per-subject tutor CLIs (see 'learn subject overview').",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=_no_verb, json=False)
    # Propagate the structured-error parser class so sub-verb parse errors route
    # through the error contract (error:/hint: + exit 1), not argparse's default.
    noun_sub = p.add_subparsers(dest="subject_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the subject noun and registered subjects.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_subject_overview)

    doc = noun_sub.add_parser(
        "doctor",
        help="Check a subject CLI's contract conformance (verbs, payloads, exit codes).",
    )
    doc.add_argument("name", help="Registered subject id (see 'learn subjects').")
    doc.add_argument("--json", action="store_true", help="Emit structured JSON.")
    doc.set_defaults(func=cmd_subject_doctor)
