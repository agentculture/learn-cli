"""Short-lived voice tokens — the verify side of learn-api's mint (task t16).

Byte-for-byte symmetric with ``workers/learn-api/src/session.js``:

    token   = base64url(JSON payload) + "." + base64url(signature)
    signature = HMAC-SHA256(secret, base64url(JSON payload))

both base64url segments unpadded, the HMAC computed over the *encoded body
string*. The Worker mints with the same shared secret (a template Parameter
here, a Worker secret there); this module only ever verifies.

The payload carries ``{v, scope, uid, approved, iat, exp, sid}``. Three claims
distinguish a voice token from the session tokens whose format it shares:

- ``scope: "voice"`` — a learn-api *session* token must never open the
  bridge (no session-cookie reuse; the plan's t4 acceptance verbatim);
- ``approved: true`` — minted only for learners the admin approved for the
  Bedrock tier, making the bridge entry the approval gate (h7 groundwork);
- a short ``exp`` — minutes, not the session's hour.

``verify_voice_token`` returns the payload dict when every check passes and
``None`` otherwise — the session.js contract. It never raises on bad input.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

TOKEN_VERSION = 1
TOKEN_SCOPE = "voice"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, body: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return _b64url(digest)


def mint_voice_token(
    secret: str,
    uid: str | int,
    *,
    approved: bool,
    ttl_seconds: int,
    now: int | None = None,
    scope: str = TOKEN_SCOPE,
) -> str:
    """Mint a voice token — the Python parity twin of the Worker's minter.

    Production minting happens in learn-api (t16); this helper exists so the
    verify side can be tested against the exact format the Worker produces,
    and doubles as an operator tool for local smoke tests.
    """
    if not secret:
        raise ValueError("voice-token secret is not configured")
    if approved is not True:
        raise ValueError("voice tokens are minted for approved learners only")
    iat = int(time.time()) if now is None else int(now)
    payload = {
        "v": TOKEN_VERSION,
        "scope": scope,
        "uid": str(uid),
        "approved": True,
        "iat": iat,
        "exp": iat + int(ttl_seconds),
        "sid": str(uuid.uuid4()),
    }
    body = _b64url(json.dumps(payload).encode("utf-8"))
    return f"{body}.{_sign(secret, body)}"


def verify_voice_token(secret: str | None, token: object, *, now: int | None = None):
    """Return the payload if the token is valid, current, and approved — else ``None``."""
    if not secret or not isinstance(secret, str):
        return None
    if not token or not isinstance(token, str):
        return None
    dot = token.rfind(".")
    if dot <= 0:
        return None
    body, signature = token[:dot], token[dot + 1 :]
    if not hmac.compare_digest(signature, _sign(secret, body)):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("v") != TOKEN_VERSION:
        return None
    if payload.get("scope") != TOKEN_SCOPE:
        return None
    if payload.get("approved") is not True:
        return None
    uid = payload.get("uid")
    if not uid or not isinstance(uid, str):
        return None
    exp = payload.get("exp")
    current = int(time.time()) if now is None else int(now)
    if not isinstance(exp, (int, float)) or exp <= current:
        return None
    return payload
