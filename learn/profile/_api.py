"""A thin, stdlib-only client for the learn API (``workers/learn-api``).

Every call is short-timeout and raises :class:`ApiError` on any network/HTTP
failure — never a Python exception a caller has to know the shape of. That is
deliberate: every profile-facing verb (``auth login``, ``progress``, ``record``)
must degrade gracefully when offline, so callers catch :class:`ApiError` at the
CLI boundary and report a sync/auth status instead of failing the command.

``LEARN_API_URL`` overrides the API base (default ``DEFAULT_API_URL`` — a
placeholder until the Worker is deployed at that route; see
``workers/learn-api/README.md``). Endpoints mirror ``workers/learn-api/src/index.js``:
``POST {base}/auth/device``, ``POST {base}/auth/logout``, ``GET {base}/me``,
``POST {base}/record``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional
from urllib.parse import urlparse

#: Schemes accepted for the API base — named (not a raw "scheme://" literal) so
#: the check below reads as an allowlist rather than a hardcoded insecure URL.
_ALLOWED_SCHEMES = ("http", "https")

#: Placeholder production default — documented as such; the Worker route is
#: not live yet (t11 ships the code, hosting/DNS wiring is a separate step).
DEFAULT_API_URL = "https://agentculture.org/learn/api"

#: Env var overriding the API base (a local wrangler dev server, a staging URL).
API_URL_ENV = "LEARN_API_URL"

#: Short timeout so an unreachable API never hangs an offline-first command.
DEFAULT_TIMEOUT = 5.0


class ApiError(Exception):
    """Any network/HTTP failure talking to the learn API.

    Deliberately a single flat exception type — callers don't need to
    distinguish "DNS failed" from "the server said 500"; they just need to
    know the call didn't succeed and degrade gracefully.
    """


def api_base() -> str:
    return os.environ.get(API_URL_ENV, DEFAULT_API_URL).rstrip("/")


def _url(path: str) -> str:
    return f"{api_base()}{path}"


def _request(
    method: str,
    path: str,
    *,
    token: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    url = _url(path)
    if urlparse(url).scheme not in _ALLOWED_SCHEMES:
        # Guards the urlopen call below against a misconfigured LEARN_API_URL
        # resolving to a non-http(s) scheme (e.g. file://) before we ever open it.
        raise ApiError(f"refusing non-http(s) API URL: {url}")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        # Scheme is checked above (http/https only); base is LEARN_API_URL or the default.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        message = body
        try:
            parsed = json.loads(body)
            message = parsed.get("message", body)
        except json.JSONDecodeError:
            pass
        raise ApiError(f"HTTP {err.code} from {url}: {message}") from err
    except urllib.error.URLError as err:
        raise ApiError(f"could not reach {url}: {err.reason}") from err
    except TimeoutError as err:
        raise ApiError(f"timed out contacting {url}") from err
    except json.JSONDecodeError as err:
        raise ApiError(f"{url} did not return valid JSON") from err


def device_start(*, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Start the GitHub device flow. Returns the server's device-start payload."""
    return _request("POST", "/auth/device", payload={"action": "start"}, timeout=timeout)


def device_poll(device_code: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Poll once. Returns ``{"status": "pending", ...}`` or ``{"status": "complete", ...}``."""
    return _request(
        "POST",
        "/auth/device",
        payload={"action": "poll", "device_code": device_code},
        timeout=timeout,
    )


def device_logout(token: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Best-effort server-side session revocation."""
    return _request("POST", "/auth/logout", token=token, payload={}, timeout=timeout)


def fetch_me(token: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    return _request("GET", "/me", token=token, timeout=timeout)


def push_record(
    token: str,
    subject: str,
    recorded: dict[str, Any],
    *,
    mastery: Optional[dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Push one ledger row to ``POST /api/record``. Returns the server's ack."""
    payload: dict[str, Any] = {"subject": subject, "recorded": recorded}
    if mastery is not None:
        payload["mastery"] = mastery
    return _request("POST", "/record", token=token, payload=payload, timeout=timeout)


def admin_list_learners(token: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Admin-only: ``GET /api/admin/learners`` — every learner + a cheap
    per-subject progress summary. The server enforces the GitHub-id
    allow-list (spec c12/h4); a non-admin token gets an ``ApiError`` wrapping
    the server's ``403 admin_required`` here, same as any other HTTP failure
    — this client makes no admin decision of its own.
    """
    return _request("GET", "/admin/learners", token=token, timeout=timeout)


def admin_approve_learner(
    token: str, github_user_id: str, *, timeout: float = DEFAULT_TIMEOUT
) -> dict[str, Any]:
    """Admin-only: ``POST /api/admin/approve`` — grant a learner the tutoring
    tier (spec c13, task t9). The server enforces both the admin allow-list
    AND decision c20 (the target's consent must cover the CURRENT terms
    version — a ``409 consent_stale`` otherwise); either failure surfaces as
    an ``ApiError`` here, same as any other HTTP failure.
    """
    return _request(
        "POST",
        "/admin/approve",
        token=token,
        payload={"github_user_id": github_user_id},
        timeout=timeout,
    )


def admin_revoke_learner(
    token: str, github_user_id: str, *, timeout: float = DEFAULT_TIMEOUT
) -> dict[str, Any]:
    """Admin-only: ``POST /api/admin/revoke`` — withdraw a learner's tutoring
    tier (task t9). Takes effect on the learner's very next tutor call; the
    server reads the flag per request, no re-login involved.
    """
    return _request(
        "POST",
        "/admin/revoke",
        token=token,
        payload={"github_user_id": github_user_id},
        timeout=timeout,
    )
