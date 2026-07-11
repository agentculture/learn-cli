"""Tests for ``infra/voice_bridge/tokens.py`` — short-lived voice-token verification.

The token format is byte-for-byte symmetric with learn-api's session tokens
(``workers/learn-api/src/session.js``): ``base64url(JSON payload)`` + ``.`` +
``base64url(HMAC-SHA256(secret, payload))``, unpadded. t16 mints the JS
counterpart in the Worker with the same shared secret; this suite pins the
Python verify side (and the parity ``mint`` helper used by tests) so the two
implementations cannot drift.

Spec honesty condition h7 groundwork: everything that is not a valid, current,
*approved* voice token verifies to ``None`` — and ``None`` means the bridge
never opens an upstream Bedrock connection (see test_voice_bridge_handler.py).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from voice_bridge import tokens

SECRET = "spike-shared-secret"
NOW = 1_800_000_000


def mint(**overrides):
    """A valid approved token, with per-test payload overrides applied post-mint."""
    token = tokens.mint_voice_token(SECRET, uid="20955789", approved=True, ttl_seconds=120, now=NOW)
    if not overrides:
        return token
    body, _sig = token.rsplit(".", 1)
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload.update(overrides)
    new_body = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    )
    new_sig = (
        base64.urlsafe_b64encode(
            hmac.new(SECRET.encode("utf-8"), new_body.encode("ascii"), hashlib.sha256).digest()
        )
        .decode("ascii")
        .rstrip("=")
    )
    return f"{new_body}.{new_sig}"


def test_mint_then_verify_round_trip() -> None:
    payload = tokens.verify_voice_token(SECRET, mint(), now=NOW)
    assert payload is not None
    assert payload["uid"] == "20955789"
    assert payload["approved"] is True
    assert payload["scope"] == tokens.TOKEN_SCOPE == "voice"
    assert payload["v"] == 1
    assert payload["exp"] == NOW + 120


def test_token_format_is_symmetric_with_session_js() -> None:
    """Two unpadded base64url segments; the signature is HMAC-SHA256 of the body string.

    This is exactly what ``session.js``'s ``issueSession``/``hmacSign`` produce,
    so a Worker-minted token with the same secret verifies here unchanged.
    """
    token = mint()
    body, sig = token.rsplit(".", 1)
    assert "=" not in token
    expected = (
        base64.urlsafe_b64encode(
            hmac.new(SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
        )
        .decode("ascii")
        .rstrip("=")
    )
    assert sig == expected
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    assert set(payload) == {"v", "scope", "uid", "approved", "iat", "exp", "sid"}


def test_uid_is_coerced_to_string_like_session_js() -> None:
    token = tokens.mint_voice_token(SECRET, uid=20955789, approved=True, ttl_seconds=60, now=NOW)
    payload = tokens.verify_voice_token(SECRET, token, now=NOW)
    assert payload is not None
    assert payload["uid"] == "20955789"


def test_mint_refuses_an_empty_secret() -> None:
    """Same posture as session.js: no secret configured -> throw, never sign with ''."""
    with pytest.raises(ValueError):
        tokens.mint_voice_token("", uid="1", approved=True, ttl_seconds=60, now=NOW)


def test_mint_refuses_unapproved() -> None:
    """Minting is for approved learners only — the bridge is the approved tier's door."""
    with pytest.raises(ValueError):
        tokens.mint_voice_token(SECRET, uid="1", approved=False, ttl_seconds=60, now=NOW)


@pytest.mark.parametrize(
    "bad_token",
    [
        None,
        "",
        "no-dot-here",
        ".leading-dot",
        "not-base64.!!!",
        "AAAA.BBBB",
    ],
)
def test_malformed_tokens_verify_to_none(bad_token) -> None:
    assert tokens.verify_voice_token(SECRET, bad_token, now=NOW) is None


def test_expired_token_is_rejected() -> None:
    token = mint()
    assert tokens.verify_voice_token(SECRET, token, now=NOW + 121) is None


def test_exp_boundary_is_exclusive_like_session_js() -> None:
    """session.js rejects exp <= now; the Python side must agree exactly."""
    token = mint()
    assert tokens.verify_voice_token(SECRET, token, now=NOW + 120) is None
    assert tokens.verify_voice_token(SECRET, token, now=NOW + 119) is not None


def test_unapproved_payload_is_rejected() -> None:
    assert tokens.verify_voice_token(SECRET, mint(approved=False), now=NOW) is None


def test_missing_approved_claim_is_rejected() -> None:
    token = mint()
    body, _sig = token.rsplit(".", 1)
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    del payload["approved"]
    new_body = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    )
    new_sig = (
        base64.urlsafe_b64encode(
            hmac.new(SECRET.encode("utf-8"), new_body.encode("ascii"), hashlib.sha256).digest()
        )
        .decode("ascii")
        .rstrip("=")
    )
    assert tokens.verify_voice_token(SECRET, f"{new_body}.{new_sig}", now=NOW) is None


def test_wrong_scope_is_rejected() -> None:
    """A learn-api *session* token must not open the voice bridge (no cookie reuse)."""
    assert tokens.verify_voice_token(SECRET, mint(scope="session"), now=NOW) is None


def test_missing_uid_is_rejected() -> None:
    assert tokens.verify_voice_token(SECRET, mint(uid=""), now=NOW) is None


def test_wrong_version_is_rejected() -> None:
    assert tokens.verify_voice_token(SECRET, mint(v=2), now=NOW) is None


def test_tampered_payload_is_rejected() -> None:
    token = mint()
    body, sig = token.rsplit(".", 1)
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["uid"] = "999"
    forged_body = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    )
    assert tokens.verify_voice_token(SECRET, f"{forged_body}.{sig}", now=NOW) is None


def test_wrong_secret_is_rejected() -> None:
    assert tokens.verify_voice_token("other-secret", mint(), now=NOW) is None


def test_empty_secret_verifies_nothing() -> None:
    """The template's VoiceTokenSecretValue defaults to '' — the bridge stays shut."""
    assert tokens.verify_voice_token("", mint(), now=NOW) is None
    assert tokens.verify_voice_token(None, mint(), now=NOW) is None
