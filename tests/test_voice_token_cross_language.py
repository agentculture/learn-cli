"""The cross-language voice-token contract (task t16, spec c15/h7 groundwork).

``workers/learn-api/src/voice.js`` mints voice tokens (JavaScript, Cloudflare
Worker); ``infra/voice_bridge/tokens.py`` verifies them (Python, Lambda).
This suite pins the two to ONE format forever through a committed fixture,
``tests/fixtures/voice_token_cross_language.json``: a token minted once by the
actual JS minter with deterministic inputs (test-only secret, fixed ``now``,
fixed ``sid``).

- ``workers/learn-api/test/voice.test.js`` asserts the JS minter still
  reproduces the fixture token **byte-for-byte** — a JS-side format change
  goes red there.
- THIS file asserts the Python verifier still **accepts** the fixture token
  and reads back exactly the claims the JS side wrote — a Python-side format
  change goes red here.

Either side drifting breaks one of the two suites; neither can drift
silently. (``tests/test_voice_bridge_tokens.py`` separately pins the format's
internals via the Python parity minter; this file is the *actual JS output*
crossing the boundary.)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from voice_bridge import tokens

FIXTURE = Path(__file__).parent / "fixtures" / "voice_token_cross_language.json"


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_documents_its_own_provenance(fixture: dict) -> None:
    assert fixture["minted_by"] == "workers/learn-api/src/voice.js#mintVoiceToken"
    assert fixture["verified_by"] == "infra/voice_bridge/tokens.py#verify_voice_token"
    assert "test" in fixture["secret"], "the committed secret must be self-evidently test-only"


def test_python_verifier_accepts_the_js_minted_token(fixture: dict) -> None:
    payload = tokens.verify_voice_token(fixture["secret"], fixture["token"], now=fixture["now"])
    assert payload is not None, "tokens.py must accept a token the Worker minted"
    assert payload["uid"] == fixture["uid"]
    assert payload["scope"] == tokens.TOKEN_SCOPE == "voice"
    assert payload["approved"] is True
    assert payload["v"] == tokens.TOKEN_VERSION
    assert payload["iat"] == fixture["now"]
    assert payload["exp"] == fixture["now"] + fixture["ttl_seconds"]
    assert payload["sid"] == fixture["sid"]


def test_js_minted_claim_set_is_exactly_what_tokens_py_pins(fixture: dict) -> None:
    """Same claim-set guard as test_voice_bridge_tokens.py, on the JS output."""
    payload = tokens.verify_voice_token(fixture["secret"], fixture["token"], now=fixture["now"])
    assert payload is not None
    assert set(payload) == {"v", "scope", "uid", "approved", "iat", "exp", "sid"}


def test_js_minted_token_is_unpadded_two_segment_base64url(fixture: dict) -> None:
    token = fixture["token"]
    assert "=" not in token, "segments must be unpadded (session.js/tokens.py contract)"
    assert token.count(".") == 1


def test_js_minted_token_expires_exclusively_at_exp(fixture: dict) -> None:
    """tokens.py rejects exp <= now; the JS-minted exp must honor that boundary."""
    exp = fixture["now"] + fixture["ttl_seconds"]
    assert tokens.verify_voice_token(fixture["secret"], fixture["token"], now=exp) is None
    assert tokens.verify_voice_token(fixture["secret"], fixture["token"], now=exp - 1) is not None


def test_js_minted_token_fails_with_the_wrong_secret(fixture: dict) -> None:
    other = tokens.verify_voice_token("some-other-secret", fixture["token"], now=fixture["now"])
    assert other is None


def test_js_minted_token_fails_when_tampered(fixture: dict) -> None:
    body, sig = fixture["token"].rsplit(".", 1)
    # Re-encode the body with a forged uid but keep the JS signature.
    import base64

    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["uid"] = "999"
    forged_body = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    )
    assert (
        tokens.verify_voice_token(fixture["secret"], f"{forged_body}.{sig}", now=fixture["now"])
        is None
    )
