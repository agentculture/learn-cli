"""``learn auth`` — GitHub device-flow sign-in linking this CLI to the web learner.

Four verbs:

* ``auth login`` — starts the device flow against the learn API
  (``POST /api/auth/device``), prints the verification URL + user code, polls
  until the learner confirms in a browser, and stores the resulting session
  locally (``0600``). Never required: every other verb works with no session.
* ``auth logout`` — best-effort server-side revoke, then always clears the
  local session (offline-safe: the local sign-out succeeds even if the
  network call fails).
* ``auth status`` — reports the local sign-in + sync state. Reads only local
  files — never touches the network, so it stays instant and offline-safe.
* ``auth overview`` — describes this noun (the agent-first rubric requires an
  ``overview`` on any noun with action-verbs).

Sign-in is additive: it links local activity to the same learner account the
web uses and enables cross-device sync (see ``learn.profile``'s push-only v1
sync). It never gates any other verb — anonymous, local-only use is always
fully functional.
"""

from __future__ import annotations

import argparse
import time

from learn.cli._commands.overview import emit_overview
from learn.cli._errors import EXIT_ENV_ERROR, EXIT_SUCCESS, CliError
from learn.cli._output import emit_diagnostic, emit_result
from learn.profile import (
    ApiError,
    AuthState,
    clear_auth,
    device_logout,
    device_poll,
    device_start,
    ledger_count,
    load_auth,
    load_sync_state,
    save_auth,
)

#: Poll interval fallback when the API omits ``interval`` (GitHub's default).
_DEFAULT_INTERVAL = 5

#: Expiry fallback when the API omits ``expires_in`` — 15 minutes at the
#: default interval, matching GitHub's own device-code default lifetime.
_DEFAULT_EXPIRES_IN = _DEFAULT_INTERVAL * 180

#: Shared ``--json`` help text (repeated per subparser below).
_JSON_HELP = "Emit structured JSON."


def _login_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "Verbs",
            "items": [
                "auth login — GitHub device-flow sign-in; links this CLI to the web learner",
                "auth logout — clear the local session (best-effort server-side revoke)",
                "auth status — local sign-in + sync status (no network call)",
                "auth overview — describe this noun (you are here)",
            ],
        },
        {
            "title": "Offline-first",
            "items": [
                "progress/next/record all work fully with no token and no network",
                "signing in only adds cross-device sync/continuity, never a gate",
                "LEARN_API_URL overrides the API base (default https://agentculture.org/learn/api)",
            ],
        },
    ]


def cmd_auth_overview(args: argparse.Namespace) -> int:
    emit_overview("learn auth", _login_sections(), json_mode=bool(getattr(args, "json", False)))
    return EXIT_SUCCESS


def _start_device_flow() -> dict[str, object]:
    """Start the device flow and validate the response has what login needs."""
    try:
        start = device_start()
    except ApiError as err:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"could not start device sign-in: {err}",
            remediation="check network connectivity and LEARN_API_URL, then retry",
        ) from err
    if (
        not start.get("device_code")
        or not start.get("user_code")
        or not start.get("verification_uri")
    ):
        raise CliError(
            code=EXIT_ENV_ERROR,
            message="learn API returned an incomplete device-start response",
            remediation="retry `learn auth login`; if this persists the learn API is misconfigured",
        )
    return start


def _poll_once(device_code: str) -> dict[str, object]:
    """One device-flow poll call, translating a network failure to a CliError."""
    try:
        return device_poll(device_code)
    except ApiError as err:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"device sign-in poll failed: {err}",
            remediation="check network connectivity and retry `learn auth login`",
        ) from err


def _await_device_confirmation(
    device_code: str, interval: int, expires_in: int
) -> dict[str, object]:
    """Poll until the learner confirms; return the 'complete' response.

    Raises :class:`CliError` on an unexpected status or on timeout.
    """
    elapsed = 0
    while elapsed <= expires_in:
        time.sleep(interval)
        elapsed += interval
        resp = _poll_once(device_code)
        status = resp.get("status")
        if status == "complete":
            return resp
        if status == "pending":
            if resp.get("slow_down"):
                interval += 5
            continue
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"unexpected device sign-in status: {status!r}",
            remediation="retry `learn auth login`",
        )
    raise CliError(
        code=EXIT_ENV_ERROR,
        message="device sign-in timed out waiting for confirmation",
        remediation="retry `learn auth login` and confirm before the code expires",
    )


def _emit_login_success(resp: dict[str, object], json_mode: bool) -> None:
    """Persist the signed-in session and print/emit the success payload."""
    learner = resp.get("learner") or {}
    state = AuthState(
        token=resp["token"],
        token_type=resp.get("token_type", "Bearer"),
        expires_at=resp.get("expires_at"),
        github_user_id=str(learner.get("github_user_id", "")),
        display_name=str(learner.get("display_name", "")),
    )
    save_auth(state)
    payload = {
        "signed_in": True,
        "learner": {
            "github_user_id": state.github_user_id,
            "display_name": state.display_name,
        },
        "expires_at": state.expires_at,
    }
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        emit_result(
            f"Signed in as {state.display_name} — linked to the web learner account.",
            json_mode=False,
        )


def cmd_auth_login(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    start = _start_device_flow()
    user_code = start["user_code"]
    verification_uri = start["verification_uri"]
    interval = int(start.get("interval") or _DEFAULT_INTERVAL)
    expires_in = int(start.get("expires_in") or _DEFAULT_EXPIRES_IN)

    emit_diagnostic(f"To sign in, open {verification_uri} and enter code: {user_code}")

    resp = _await_device_confirmation(start["device_code"], interval, expires_in)
    _emit_login_success(resp, json_mode)
    return EXIT_SUCCESS


def cmd_auth_logout(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    state = load_auth()
    server_revoked = False
    if state is not None:
        try:
            device_logout(state.token)
            server_revoked = True
        except ApiError:
            pass  # offline-safe: local sign-out always succeeds regardless
    had_session = clear_auth()
    payload = {"signed_out": True, "had_session": had_session, "server_revoked": server_revoked}
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        msg = "Signed out." if had_session else "Already signed out (no local session)."
        emit_result(msg, json_mode=False)
    return EXIT_SUCCESS


def cmd_auth_status(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    state = load_auth()
    if state is None:
        payload = {"signed_in": False}
        if json_mode:
            emit_result(payload, json_mode=True)
        else:
            emit_result(
                "Not signed in (anonymous, local-only). Run `learn auth login` to link "
                "the web learner account.",
                json_mode=False,
            )
        return EXIT_SUCCESS

    sync_state = load_sync_state()
    rows = ledger_count()
    pending = max(rows - sync_state.cursor, 0)
    payload = {
        "signed_in": True,
        "learner": {"github_user_id": state.github_user_id, "display_name": state.display_name},
        "expires_at": state.expires_at,
        "sync": {"pushed": sync_state.cursor, "ledger_rows": rows, "pending": pending},
    }
    if json_mode:
        emit_result(payload, json_mode=True)
    else:
        lines = [
            f"Signed in as {state.display_name} (github:{state.github_user_id})",
            f"token expires_at: {state.expires_at}",
            f"sync: {sync_state.cursor}/{rows} ledger rows pushed ({pending} pending)",
        ]
        emit_result("\n".join(lines), json_mode=False)
    return EXIT_SUCCESS


def _no_verb(args: argparse.Namespace) -> int:
    # `learn auth` with no sub-verb prints the noun's overview.
    return cmd_auth_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "auth",
        help="Sign in/out and check the linked web learner account (see 'learn auth overview').",
    )
    p.add_argument("--json", action="store_true", help=_JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    # Propagate the structured-error parser class so sub-verb parse errors route
    # through the error contract (error:/hint: + exit 1), not argparse's default.
    noun_sub = p.add_subparsers(dest="auth_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the auth noun and its verbs.")
    ov.add_argument("--json", action="store_true", help=_JSON_HELP)
    ov.set_defaults(func=cmd_auth_overview)

    login = noun_sub.add_parser(
        "login", help="Device-flow sign-in linking this CLI to the web learner account."
    )
    login.add_argument("--json", action="store_true", help=_JSON_HELP)
    login.set_defaults(func=cmd_auth_login)

    logout = noun_sub.add_parser("logout", help="Sign out and clear the local session.")
    logout.add_argument("--json", action="store_true", help=_JSON_HELP)
    logout.set_defaults(func=cmd_auth_logout)

    status = noun_sub.add_parser("status", help="Show local sign-in and sync status.")
    status.add_argument("--json", action="store_true", help=_JSON_HELP)
    status.set_defaults(func=cmd_auth_status)
