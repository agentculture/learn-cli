"""The voice-session page (t16, spec c15/h7 — the voice UI's client half).

Locks the page's gate states and ``src/scripts/voice.js``'s audited structure
against drift, the way ``tests/test_consent_page.py`` does for the consent
notice:

* the page ships all five gate states (``signed-out`` visible by default —
  progressive enhancement, a no-JS visitor sees the sign-in invitation —
  the other four hidden until voice.js drives them);
* voice.js's fetch surface is exactly ``GET /api/me`` + ``POST
  /api/voice/token`` — no ``/progress``, ``/record``, ``/admin``, or the
  inference-spending broker route;
* **h7's client half is structural**: the file constructs exactly ONE
  WebSocket, inside the ``openBridgeSocket`` seam (injectable factory, pure
  in what decides to connect), and the seam's only call site sits inside
  ``startSession`` lexically AFTER the token mint with a non-ok early return
  in between — no token, no WebSocket. The server enforces the same gate
  independently at both ends (the Worker refuses to mint below "approved";
  the bridge re-verifies at $connect), so this is defense in depth plus UX
  honesty, and it's what "the UI never opens a WebSocket without a token"
  means as a testable claim with no browser in the loop;
* the client audio contract pins t4's spike-proven shapes
  (``infra/voice_bridge/relay.py``): 16 kHz upstream, 24 kHz downstream,
  ``{"seq", "audio"}`` frames up, ``{"kind", "content"}`` frames down;
* the check-scripts' whitelists were extended precisely, not blanket-widened.

Deliberately pure file reads — no npm/astro/node subprocess (the CI test job
never provisions Node); ``site-astro/scripts/check-static-auth.mjs`` re-proves
the same structure at build time, including over the built bundle.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOICE_PAGE = ROOT / "site-astro" / "src" / "pages" / "voice" / "index.astro"
VOICE_JS = ROOT / "site-astro" / "src" / "scripts" / "voice.js"
RELAY_PY = ROOT / "infra" / "voice_bridge" / "relay.py"
WORKER_INDEX = ROOT / "workers" / "learn-api" / "src" / "index.js"
WORKER_VOICE = ROOT / "workers" / "learn-api" / "src" / "voice.js"
CHECK_STATIC_AUTH = ROOT / "site-astro" / "scripts" / "check-static-auth.mjs"
CHECK_EXPORT_PAGES = ROOT / "site-astro" / "scripts" / "check-export-pages.mjs"

STATES = ("signed-out", "consent-needed", "not-approved", "ready", "error")


def _read(path: Path) -> str:
    assert path.is_file(), f"expected {path} to exist"
    return path.read_text(encoding="utf-8")


def _strip_js_comments(text: str) -> str:
    """Drop ``//``-prefixed comment lines (voice.js's header documents the
    routes it must NOT call — same rationale as test_consent_page.py)."""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))


def _function_body(source: str, marker: str) -> str:
    """Balanced-brace extraction of the function opened at ``marker``."""
    start = source.index(marker)
    open_brace = source.index("{", start)
    depth = 0
    for i in range(open_brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace : i + 1]
    raise AssertionError(f"unbalanced braces after {marker!r}")


# --- the page: route, script wiring, gate states ---------------------------


def test_voice_page_exists_at_the_expected_route() -> None:
    # site-astro/src/pages/voice/index.astro -> built route /voice/ ->
    # (with astro.config.mjs's base: '/learn') /learn/voice/.
    assert VOICE_PAGE.is_file()


def test_voice_script_is_separate_from_learner_js_and_not_in_layout() -> None:
    # t15 works learner.js/tutor surfaces in parallel — voice keeps its own
    # file footprint: its own page dir, its own script, loaded only by the
    # voice page's <script> block, never via Layout.astro.
    assert VOICE_JS.is_file()
    layout = _read(ROOT / "site-astro" / "src" / "layouts" / "Layout.astro")
    assert "voice.js" not in layout
    page = _read(VOICE_PAGE)
    assert re.search(r'import\s*["\']\.\./\.\./scripts/voice\.js["\']', page)


def test_voice_page_renders_all_five_gate_states() -> None:
    text = _read(VOICE_PAGE)
    for state in STATES:
        assert f'data-state="{state}"' in text, f'missing data-state="{state}" block'
    # signed-out is the only state visible with no JS at all; the rest ship hidden.
    for state in STATES[1:]:
        assert re.search(
            rf'data-state="{state}"\s+hidden', text
        ), f'data-state="{state}" must ship hidden in the static markup'
    assert not re.search(r'data-state="signed-out"\s+hidden', text)


def test_signed_out_state_links_sign_in() -> None:
    text = _read(VOICE_PAGE)
    match = re.search(r'data-state="signed-out"[^>]*>(.*?)</div>', text, re.S)
    assert match, "expected to find the signed-out state's markup"
    assert "/auth/login" in match.group(1)


def test_ready_state_has_mic_controls_timer_limits_and_transcript() -> None:
    text = _read(VOICE_PAGE)
    for attr in (
        "data-voice-start",
        "data-voice-stop",
        "data-voice-timer",
        "data-voice-limits",
        "data-voice-status",
        "data-voice-transcript",
    ):
        assert attr in text, f"missing {attr} in the ready state"


def test_voice_js_drives_all_five_states() -> None:
    text = _read(VOICE_JS)
    for state in STATES:
        assert f'showState("{state}")' in text


# --- voice.js: precise fetch surface ----------------------------------------


def test_voice_js_imports_the_single_api_base_constant() -> None:
    text = _read(VOICE_JS)
    assert re.search(r'import\s*\{\s*API_BASE\s*\}\s*from\s*["\']\.\./lib/api\.js["\']', text)


def test_voice_js_only_calls_me_and_voice_token() -> None:
    text = _read(VOICE_JS)
    fetch_targets = re.findall(r"fetch\(\s*`([^`]*)`", text)
    assert len(fetch_targets) >= 2
    allowed = re.compile(r"^\$\{API_BASE\}(/me|/voice/token)$")
    offenders = [t for t in fetch_targets if not allowed.match(t)]
    assert offenders == [], f"voice.js calls non-whitelisted endpoint(s): {offenders}"


def test_voice_js_never_references_other_learner_routes() -> None:
    code_only = _strip_js_comments(_read(VOICE_JS))
    for route in ("/progress", "/record", "/tutor", "/admin", "/export", "/delete"):
        assert route not in code_only, f"voice.js must not reference {route}"


def test_voice_js_uses_credentials_include_on_both_calls() -> None:
    text = _read(VOICE_JS)
    me_idx = text.index("fetch(`${API_BASE}/me`")
    mint_idx = text.index("fetch(`${API_BASE}/voice/token`")
    assert 'credentials: "include"' in text[me_idx : me_idx + 300]
    assert 'credentials: "include"' in text[mint_idx : mint_idx + 300]


# --- h7's client half: no token => no WebSocket, structurally ---------------


def test_exactly_one_websocket_construction_inside_the_injectable_seam() -> None:
    text = _read(VOICE_JS)
    assert text.count("new WebSocket(") == 1
    seam = _function_body(text, "function openBridgeSocket(")
    assert "new WebSocket(" in seam
    # The seam is injectable (pure for tests): the factory parameter wins.
    assert "socketFactory" in seam


def test_connect_happens_only_after_a_successful_mint() -> None:
    text = _read(VOICE_JS)
    body = _function_body(text, "async function startSession(")
    mint_idx = body.index("fetch(`${API_BASE}/voice/token`")
    connect_idx = body.index("openBridgeSocket(")
    assert connect_idx > mint_idx, "the connect must come lexically after the mint"
    between = body[mint_idx:connect_idx]
    assert re.search(
        r"if\s*\(!res\.ok.*?return;", between, re.S
    ), "a non-ok mint must return before the connect line is reachable"
    # And the seam has exactly one call site outside its own definition.
    code_only = _strip_js_comments(text)
    call_sites = [
        m
        for m in re.finditer(r"openBridgeSocket\(", code_only)
        if "function" not in code_only[code_only.rfind("\n", 0, m.start()) : m.start()]
    ]
    assert len(call_sites) == 1


def test_gate_flow_never_reaches_the_session_ui_below_approved() -> None:
    """bootstrap() mirrors the server's gate order: signed-out, then
    consent, then approval — wireSession is reachable only past all three."""
    text = _read(VOICE_JS)
    body = _function_body(text, "async function bootstrap(")
    wire_idx = body.index("wireSession(")
    for early_state in ("signed-out", "consent-needed", "not-approved"):
        idx = body.index(f'showState("{early_state}")')
        assert idx < wire_idx, f"{early_state} must be decided before wiring the session UI"
    assert "me.learner.approved !== true" in body


# --- the client audio contract pins t4's spike-proven shapes ----------------


def test_audio_rates_match_the_bridge_relay() -> None:
    voice_js = _read(VOICE_JS)
    relay = _read(RELAY_PY)
    assert "UPSTREAM_SAMPLE_RATE = 16000" in voice_js
    assert "DOWNSTREAM_SAMPLE_RATE = 24000" in voice_js
    assert '"sampleRateHertz": 16000' in relay
    assert '"sampleRateHertz": 24000' in relay


def test_upstream_frames_carry_seq_and_audio() -> None:
    # relay.order_frames parses {"seq": n, "audio": base64} — seq is
    # ordering-authoritative because $default invocations can land out of order.
    voice_js = _read(VOICE_JS)
    assert re.search(r"JSON\.stringify\(\{\s*seq:", voice_js)
    assert "audio:" in voice_js
    relay = _read(RELAY_PY)
    assert 'frame["seq"]' in relay and 'frame["audio"]' in relay


def test_downstream_frames_read_kind_and_content() -> None:
    # relay.pump sends {"kind": "audio"|"text", "content": ...} downstream.
    voice_js = _read(VOICE_JS)
    assert 'message.kind === "audio"' in voice_js
    assert 'message.kind === "text"' in voice_js
    assert "message.content" in voice_js


def test_session_timer_enforces_the_granted_limit_client_side() -> None:
    voice_js = _read(VOICE_JS)
    assert "max_session_seconds" in voice_js
    assert re.search(r"elapsed >= session\.maxSeconds", voice_js)


def test_unauthorized_close_code_is_handled() -> None:
    voice_js = _read(VOICE_JS)
    assert "WS_CLOSE_UNAUTHORIZED = 4001" in voice_js
    assert "WS_CLOSE_UNAUTHORIZED" in _strip_js_comments(voice_js).split("onclose", 1)[1]


# --- the check-scripts' whitelists were extended precisely ------------------


def test_check_static_auth_has_a_precise_voice_whitelist() -> None:
    text = _read(CHECK_STATIC_AUTH)
    assert "VOICE_ALLOWED_SUFFIX_RE" in text
    match = re.search(r"VOICE_ALLOWED_SUFFIX_RE\s*=\s*/(.+)/;", text)
    assert match, "expected a literal VOICE_ALLOWED_SUFFIX_RE regex"
    # Exactly two anchored suffixes — /me and /voice/token, nothing open-ended.
    assert match.group(1) == r"^(\/me$|\/voice\/token$)"


def test_check_static_auth_audits_the_websocket_allowance() -> None:
    text = _read(CHECK_STATIC_AUTH)
    assert "new WebSocket(" in text, "the checker must audit WebSocket constructions"
    assert "openBridgeSocket" in text


def test_check_static_auth_excludes_voice_from_the_learner_panel_check() -> None:
    text = _read(CHECK_STATIC_AUTH)
    assert re.search(r'NOT_A_LEARNER_PANEL_PAGE\s*=\s*new Set\(\[[^\]]*"voice"[^\]]*\]\)', text)


def test_check_export_pages_excludes_voice_from_orphan_detection() -> None:
    text = _read(CHECK_EXPORT_PAGES)
    assert re.search(r'KNOWN_NON_SUBJECT_DIRS\s*=\s*new Set\(\[[^\]]*"voice"[^\]]*\]\)', text)


# --- cross-check against the Worker's mint route ----------------------------


def test_worker_routes_the_voice_token_mint() -> None:
    text = _read(WORKER_INDEX)
    assert '"/api/voice/token"' in text
    assert "handleVoiceToken" in text


def test_worker_mint_reuses_the_tutor_gates_not_a_copy() -> None:
    """t9's hook-point note: the mint runs requireConsented then the SAME
    approvedOf check as /api/tutor — reused, not duplicated."""
    text = _read(WORKER_INDEX)
    body = _function_body(text, "async function handleVoiceToken(")
    assert "requireConsented(" in body
    assert "approvedOf(" in body
    consented_idx = body.index("requireConsented(")
    approved_idx = body.index("approvedOf(")
    config_idx = body.index('requireConfig(env, "VOICE_BRIDGE_URL")')
    assert consented_idx < approved_idx < config_idx, (
        "gate order must be consent -> approval -> config, so an unapproved "
        "learner cannot probe whether the bridge is configured"
    )
    # approvedOf is defined ONCE in the module (plus its call sites) — the
    # voice route did not grow a private copy.
    assert text.count("function approvedOf(") == 1


def test_worker_mint_response_field_names_match_what_voice_js_reads() -> None:
    worker = _read(WORKER_INDEX)
    voice_js = _read(VOICE_JS)
    for field in ("wss_url", "expires_at", "max_session_seconds"):
        assert field in worker, f"the Worker must return {field}"
    for field in ("wss_url", "max_session_seconds", "monthly_seconds_remaining"):
        assert field in voice_js, f"voice.js must read {field} off the grant"


def test_worker_voice_module_mirrors_the_bridge_session_cap() -> None:
    """The Worker's booking unit must equal the bridge's per-session cap."""
    worker_voice = _read(WORKER_VOICE)
    config_py = _read(ROOT / "infra" / "voice_bridge" / "config.py")
    js = re.search(r"DEFAULT_VOICE_MAX_SESSION_SECONDS\s*=\s*(\d+)", worker_voice)
    py = re.search(r"DEFAULT_MAX_SESSION_SECONDS\s*=\s*(\d+)", config_py)
    assert js and py and js.group(1) == py.group(1), (
        "workers/learn-api/src/voice.js DEFAULT_VOICE_MAX_SESSION_SECONDS must match "
        "infra/voice_bridge/config.py DEFAULT_MAX_SESSION_SECONDS"
    )
