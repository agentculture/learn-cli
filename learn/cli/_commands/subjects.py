"""``learn subjects`` — list the registered subjects and their availability.

The global companion to the ``subject`` noun: ``learn subjects --json`` is the
machine index of everything learn-cli hosts, straight from the data-driven
registry. Each entry reports whether its subject CLI is installed
(``available``) so a driver knows before it tries to drive one. Read-only.
"""

from __future__ import annotations

import argparse

from learn.cli._errors import EXIT_SUCCESS
from learn.cli._output import emit_result
from learn.subjects import is_available, load_registry


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for entry in load_registry():
        row = entry.to_dict()
        row["available"] = is_available(entry)
        rows.append(row)
    return rows


def cmd_subjects(args: argparse.Namespace) -> int:
    rows = _rows()
    if getattr(args, "json", False):
        emit_result({"subjects": rows, "count": len(rows)}, json_mode=True)
        return EXIT_SUCCESS
    if not rows:
        emit_result("(no subjects registered)", json_mode=False)
        return EXIT_SUCCESS
    lines = []
    for row in rows:
        mark = "installed" if row["available"] else "not installed"
        lines.append(f"{row['name']} — {row['display_name']} [{mark}]")
        lines.append(f"  {row['description']}")
        lines.append(f"  drives: {' '.join(row['argv_prefix'])} <verb> --json   ({row['repo']})")
    emit_result("\n".join(lines), json_mode=False)
    return EXIT_SUCCESS


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "subjects",
        help="List registered subjects and whether each subject CLI is installed.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_subjects)
