"""``learn admin`` — the admin-only CLI surface (tasks t8 + t9).

Three verbs today:

* ``admin learners`` — lists every learner + a cheap per-subject progress
  summary via ``GET /api/admin/learners``. Requires a local device-flow
  session (``learn auth login``) — the same authenticated-API pattern
  ``learn auth``/``learn progress``'s sync path already use (see
  :mod:`learn.profile`). Admin-ness itself is a SERVER-SIDE decision (spec
  c12/h4, ``workers/learn-api/src/admin.js``): this CLI makes none of its
  own — a non-admin token gets whatever structured error the server returns
  (403 ``admin_required``), surfaced here as an environment error like any
  other failed API call.
* ``admin approve <github_user_id>`` / ``admin revoke <github_user_id>`` —
  grant/withdraw a learner's tutoring tier via ``POST /api/admin/approve`` /
  ``POST /api/admin/revoke`` (spec c13, task t9). Same server-side trust
  model as ``learners``; the server additionally enforces decision c20 on
  approve (the target's consent must cover the CURRENT terms version — a
  ``409 consent_stale`` otherwise). Both take effect on the learner's very
  next tutor call, no re-login on their side.
* ``admin overview`` — describes this noun (the agent-first rubric requires
  an ``overview`` on any noun with action-verbs).
"""

from __future__ import annotations

import argparse
from typing import Any, Callable

from learn.cli._commands.overview import emit_overview
from learn.cli._errors import EXIT_ENV_ERROR, EXIT_SUCCESS, EXIT_USER_ERROR, CliError
from learn.cli._output import emit_result
from learn.profile import (
    ApiError,
    admin_approve_learner,
    admin_list_learners,
    admin_revoke_learner,
    load_auth,
)

#: Shared ``--json`` help text (repeated per subparser below).
_JSON_HELP = "Emit structured JSON."


def _admin_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "Verbs",
            "items": [
                "admin learners — list every learner + a cheap per-subject progress summary",
                "admin approve <github_user_id> — grant a learner the tutoring tier",
                "admin revoke <github_user_id> — withdraw a learner's tutoring tier",
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
                "approve additionally requires the target learner's consent to be "
                "CURRENT (decision c20) — the server 409s `consent_stale` otherwise",
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
        # t9: the tutoring-tier flag — additive on the server payload; absent
        # (an older server) renders as "not approved", the safe reading.
        lines.append(f"  tutoring: {'approved' if learner.get('approved') else 'not approved'}")
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


def _admin_mutate(
    args: argparse.Namespace,
    *,
    action: str,
    api_call: Callable[[str, str], dict[str, Any]],
) -> int:
    """Shared approve/revoke driver (t9) — mirrors cmd_admin_learners exactly:
    local session required, one API call, ApiError -> environment error."""
    json_mode = bool(getattr(args, "json", False))
    state = load_auth()
    if state is None:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="not signed in",
            remediation="run `learn auth login` first — an admin must also be signed in",
        )
    try:
        resp = api_call(state.token, args.github_user_id)
    except ApiError as err:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"could not {action} learner: {err}",
            remediation=(
                "check network connectivity and LEARN_API_URL; confirm your GitHub id is on "
                "the server's admin allow-list; and (approve only, decision c20) confirm the "
                "target learner's consent covers the CURRENT terms version — the server 409s "
                "`consent_stale` until they re-accept"
            ),
        ) from err
    if json_mode:
        emit_result(resp, json_mode=True)
    else:
        verdict = "approved" if resp.get("approved") else "not approved"
        emit_result(
            f"learner {resp.get('github_user_id')}: tutoring {verdict}",
            json_mode=False,
        )
    return EXIT_SUCCESS


def cmd_admin_approve(args: argparse.Namespace) -> int:
    return _admin_mutate(args, action="approve", api_call=admin_approve_learner)


def cmd_admin_revoke(args: argparse.Namespace) -> int:
    return _admin_mutate(args, action="revoke", api_call=admin_revoke_learner)


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

    approve = noun_sub.add_parser(
        "approve",
        help="Grant a learner the tutoring tier (admin-only; requires their consent "
        "to be current — decision c20).",
    )
    approve.add_argument(
        "github_user_id",
        help="The target learner's GitHub user id (see `learn admin learners`).",
    )
    approve.add_argument("--json", action="store_true", help=_JSON_HELP)
    approve.set_defaults(func=cmd_admin_approve)

    revoke = noun_sub.add_parser(
        "revoke",
        help="Withdraw a learner's tutoring tier (admin-only; effective on their next "
        "tutor call).",
    )
    revoke.add_argument(
        "github_user_id",
        help="The target learner's GitHub user id (see `learn admin learners`).",
    )
    revoke.add_argument("--json", action="store_true", help=_JSON_HELP)
    revoke.set_defaults(func=cmd_admin_revoke)
