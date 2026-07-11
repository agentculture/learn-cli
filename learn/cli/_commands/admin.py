"""``learn admin`` — the admin-only CLI read surface (task t8).

One verb today:

* ``admin learners`` — lists every learner + a cheap per-subject progress
  summary via ``GET /api/admin/learners``. Requires a local device-flow
  session (``learn auth login``) — the same authenticated-API pattern
  ``learn auth``/``learn progress``'s sync path already use (see
  :mod:`learn.profile`). Admin-ness itself is a SERVER-SIDE decision (spec
  c12/h4, ``workers/learn-api/src/admin.js``): this CLI makes none of its
  own — a non-admin token gets whatever structured error the server returns
  (403 ``admin_required``), surfaced here as an environment error like any
  other failed API call.
* ``admin overview`` — describes this noun (the agent-first rubric requires
  an ``overview`` on any noun with action-verbs).
"""

from __future__ import annotations

import argparse
from typing import Any

from learn.cli._commands.overview import emit_overview
from learn.cli._errors import EXIT_ENV_ERROR, EXIT_SUCCESS, EXIT_USER_ERROR, CliError
from learn.cli._output import emit_result
from learn.profile import ApiError, admin_list_learners, load_auth

#: Shared ``--json`` help text (repeated per subparser below).
_JSON_HELP = "Emit structured JSON."


def _admin_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "Verbs",
            "items": [
                "admin learners — list every learner + a cheap per-subject progress summary",
                "admin overview — describe this noun (you are here)",
            ],
        },
        {
            "title": "Authorization",
            "items": [
                "requires a local session: run `learn auth login` first",
                "admin-ness is decided SERVER-SIDE against a GitHub-id allow-list "
                "(spec c12/h4) — a non-admin token gets a 403 from the API, "
                "surfaced here as an environment error",
                "LEARN_API_URL overrides the API base (default https://agentculture.org/learn/api)",
            ],
        },
    ]


def cmd_admin_overview(args: argparse.Namespace) -> int:
    emit_overview("learn admin", _admin_sections(), json_mode=bool(getattr(args, "json", False)))
    return EXIT_SUCCESS


def _render_text(resp: dict[str, Any]) -> str:
    lines = [f"learn admin learners — {resp.get('count', 0)} learner(s)", ""]
    for learner in resp.get("learners", []) or []:
        consent = learner.get("consent") or {}
        lines.append(
            f"{learner.get('display_name')} (github:{learner.get('github_user_id')}) "
            f"[{learner.get('visibility')}]"
        )
        lines.append(
            f"  consent: {learner.get('consent_status')}"
            + (f" ({consent.get('terms_version')})" if consent else "")
        )
        lines.append(
            f"  records: {learner.get('records_total', 0)} total {learner.get('records', {})}"
        )
    return "\n".join(lines)


def cmd_admin_learners(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    state = load_auth()
    if state is None:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="not signed in",
            remediation="run `learn auth login` first — an admin must also be signed in",
        )
    try:
        resp = admin_list_learners(state.token)
    except ApiError as err:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"could not list learners: {err}",
            remediation=(
                "check network connectivity and LEARN_API_URL, and confirm your GitHub id "
                "is on the server's admin allow-list"
            ),
        ) from err
    if json_mode:
        emit_result(resp, json_mode=True)
    else:
        emit_result(_render_text(resp), json_mode=False)
    return EXIT_SUCCESS


def _no_verb(args: argparse.Namespace) -> int:
    # `learn admin` with no sub-verb prints the noun's overview.
    return cmd_admin_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "admin",
        help="Admin-only reads (see 'learn admin overview'); requires `learn auth login`.",
    )
    p.add_argument("--json", action="store_true", help=_JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    # Propagate the structured-error parser class so sub-verb parse errors route
    # through the error contract (error:/hint: + exit 1), not argparse's default.
    noun_sub = p.add_subparsers(dest="admin_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the admin noun and its verbs.")
    ov.add_argument("--json", action="store_true", help=_JSON_HELP)
    ov.set_defaults(func=cmd_admin_overview)

    learners = noun_sub.add_parser(
        "learners", help="List every learner + a cheap per-subject progress summary (admin-only)."
    )
    learners.add_argument("--json", action="store_true", help=_JSON_HELP)
    learners.set_defaults(func=cmd_admin_learners)
