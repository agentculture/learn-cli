"""The consent notice page (t10, spec c9/c19 — "the consent UX shape").

Locks the page's key claims and its wiring against drift, the same way
``tests/test_policy_pages.py`` does for Terms/Privacy:

* the notice states WHAT is stored (GitHub id + public display name, the
  append-only learning ledger, a session cookie — explicitly no email, no
  password), WHY (authenticate, cross-subject progress, personalize),
  RETENTION (kept while the account exists, hard-deleted on withdrawal), and
  WHO CAN SEE IT (private by default, admin can see learner data, visibility
  controls coming);
* both policy pages are linked, and the version rendered comes from the
  shared ``TERMS_VERSION``/``TERMS_EFFECTIVE_DATE`` import
  (``site-astro/src/lib/terms.ts``) rather than a hardcoded "1.0.0" — the
  same drift the version bump in t6 depends on being impossible;
* ``src/scripts/consent.js`` calls the pending-consent API surface
  documented in ``workers/learn-api/README.md``'s "For t10" section
  (``GET /api/me``, ``GET /api/consent``, ``POST /api/consent/accept``,
  ``POST /api/consent/decline``) and nothing wider — no ``/progress``,
  ``/record``, or ``/tutor`` reference, ever;
* the field names ``consent.js`` reads off the API response
  (``terms_version``, ``effective_date``, ``terms_url``, ``privacy_url``)
  match ``workers/learn-api/src/consent.js``'s ``consentRequirement()``
  shape, not a guessed/renamed copy.

Deliberately pure file reads (like ``test_policy_pages.py``) — no
``npm``/``astro build``/Node subprocess; the CI ``test`` job never
provisions Node. ``site-astro/scripts/check-static-auth.mjs`` (run via
``npm run check`` after ``npm run build``) is the complementary build-time
proof that the page actually compiles and that consent.js's fetch surface
stays inside its whitelist in the BUILT bundle too.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONSENT_PAGE = ROOT / "site-astro" / "src" / "pages" / "consent" / "index.astro"
CONSENT_JS = ROOT / "site-astro" / "src" / "scripts" / "consent.js"
TERMS_PAGE = ROOT / "site-astro" / "src" / "pages" / "terms" / "index.astro"
PRIVACY_PAGE = ROOT / "site-astro" / "src" / "pages" / "privacy" / "index.astro"
WORKER_CONSENT = ROOT / "workers" / "learn-api" / "src" / "consent.js"
CHECK_STATIC_AUTH = ROOT / "site-astro" / "scripts" / "check-static-auth.mjs"
CHECK_EXPORT_PAGES = ROOT / "site-astro" / "scripts" / "check-export-pages.mjs"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected {path} to exist"
    return path.read_text(encoding="utf-8")


def _collapsed(text: str) -> str:
    """Collapse runs of whitespace (including line wraps inside a single
    sentence, which this page's prose does for line length) to a single
    space, so a phrase check isn't brittle against where the author happened
    to wrap a line."""
    return re.sub(r"\s+", " ", text)


# --- the page and script exist where the API contract expects them --------


def test_consent_page_exists_at_the_expected_route() -> None:
    # site-astro/src/pages/consent/index.astro -> built route /consent/ ->
    # (with astro.config.mjs's base: '/learn') /learn/consent/, which is
    # exactly what workers/learn-api's callback 302s unconsented sign-ins to.
    assert CONSENT_PAGE.is_file()


def test_consent_script_is_a_separate_file_from_learner_js() -> None:
    # Not merged into learner.js and not imported by Layout.astro (that
    # would run it, and its API calls, on every page) — only the consent
    # page's own <script> block pulls it in.
    assert CONSENT_JS.is_file()
    layout = _read(ROOT / "site-astro" / "src" / "layouts" / "Layout.astro")
    assert "consent.js" not in layout
    page = _read(CONSENT_PAGE)
    assert re.search(r'import\s*["\']\.\./\.\./scripts/consent\.js["\']', page)


# --- version: imported, never hardcoded ------------------------------------


def test_consent_page_imports_terms_version_rather_than_hardcoding_it() -> None:
    text = _read(CONSENT_PAGE)
    import_re = (
        r"import\s*\{\s*TERMS_VERSION\s*,\s*TERMS_EFFECTIVE_DATE\s*\}"
        r'\s*from\s*"\.\./\.\./lib/terms"'
    )
    assert re.search(
        import_re, text
    ), "consent page must import TERMS_VERSION/TERMS_EFFECTIVE_DATE from ../../lib/terms"
    assert "{TERMS_VERSION}" in text
    assert "{TERMS_EFFECTIVE_DATE}" in text
    # The literal version string must appear nowhere in the page source — see
    # test_policy_pages.py's identical guard for why this matters (t6's
    # re-consent trigger depends on there being exactly one place to bump).
    assert "1.0.0" not in text


def test_consent_page_overwrites_the_build_time_version_with_the_live_api_value() -> None:
    """Acceptance criterion: 'also render the live terms_version from
    GET /api/consent at runtime as the authoritative value.'"""
    text = _read(CONSENT_JS)
    assert "/consent" in text
    assert "renderRequirement" in text or "terms_version" in text
    assert "terms_version" in text
    assert "effective_date" in text


# --- WHAT is stored ----------------------------------------------------


def test_consent_notice_states_what_is_stored() -> None:
    text = _collapsed(_read(CONSENT_PAGE))
    assert "GitHub numeric id" in text
    assert "display name" in text
    assert "ledger" in text.lower()
    assert "session cookie" in text.lower()


def test_consent_notice_explicitly_disclaims_email_and_password() -> None:
    text = _collapsed(_read(CONSENT_PAGE).lower())
    assert "do not collect or store your email" in text
    assert "do not collect or store a password" in text


# --- WHY -----------------------------------------------------------------


def test_consent_notice_states_why_data_is_collected() -> None:
    text = _collapsed(_read(CONSENT_PAGE).lower())
    assert "authenticate" in text
    assert "progress across subjects" in text
    assert "personalize" in text


# --- RETENTION -------------------------------------------------------------


def test_consent_notice_states_retention() -> None:
    text = _collapsed(_read(CONSENT_PAGE).lower())
    assert "kept for as long as your account exists" in text
    assert "hard-deleted" in text


# --- WHO CAN SEE IT ----------------------------------------------------


def test_consent_notice_states_who_can_see_it() -> None:
    text = _collapsed(_read(CONSENT_PAGE).lower())
    assert "private by default" in text
    assert "admin can see" in text
    # Visibility controls are a *later* task in this same uplift (t8) — the
    # notice must not overclaim they exist today.
    assert "visibility controls" in text
    assert "coming" in text


# --- links both policy pages, with version ----------------------------------


def test_consent_notice_links_both_policy_pages() -> None:
    text = _read(CONSENT_PAGE)
    assert 'href="../terms/"' in text
    assert 'href="../privacy/"' in text


def test_consent_notice_links_agree_with_the_worker_s_own_urls() -> None:
    # workers/learn-api/src/consent.js's consentRequirement() hands back
    # absolute paths; consent.js must render those OVER the page's own
    # relative defaults once the live response arrives (see
    # test_consent_page_overwrites_the_build_time_version_with_the_live_api_value).
    worker_text = _read(WORKER_CONSENT)
    assert '"/learn/terms/"' in worker_text
    assert '"/learn/privacy/"' in worker_text
    js_text = _read(CONSENT_JS)
    assert "terms_url" in js_text
    assert "privacy_url" in js_text


# --- flow states: pending/expired/already-signed-in/declined ---------------


def test_consent_page_renders_all_required_states() -> None:
    text = _read(CONSENT_PAGE)
    for state in ("notice", "expired", "already-in", "declined", "error"):
        assert f'data-state="{state}"' in text, f'missing data-state="{state}" block'
    # "notice" is the only state visible with no JS at all (progressive
    # enhancement) — the other four are JS-driven outcomes and ship hidden.
    for state in ("expired", "already-in", "declined", "error"):
        assert re.search(
            rf'data-state="{state}"\s+hidden', text
        ), f'data-state="{state}" must ship with the hidden attribute in the static markup'
    assert not re.search(r'data-state="notice"\s+hidden', text)


def test_consent_page_has_accept_and_decline_controls() -> None:
    text = _read(CONSENT_PAGE)
    assert "data-consent-accept" in text
    assert "data-consent-decline" in text


def test_consent_js_drives_all_four_dynamic_states() -> None:
    text = _read(CONSENT_JS)
    for state in ("expired", "already-in", "declined", "error"):
        assert f'showState("{state}")' in text


def test_declined_confirms_nothing_was_stored() -> None:
    # Find the declined block specifically, not just anywhere on the page.
    match = re.search(r'data-state="declined"[^>]*>(.*?)</div>', _read(CONSENT_PAGE), re.S)
    assert match, "expected to find the declined state's markup"
    declined_text = match.group(1).lower()
    assert "nothing" in declined_text and "stored" in declined_text


def test_expired_state_links_sign_in_again() -> None:
    text = _read(CONSENT_PAGE)
    match = re.search(r'data-state="expired"[^>]*>(.*?)</div>', text, re.S)
    assert match, "expected to find the expired state's markup"
    assert "/auth/login" in match.group(1)


# --- consent.js's own fetch surface: precise, not blanket ------------------


def test_consent_js_imports_the_single_api_base_constant() -> None:
    text = _read(CONSENT_JS)
    assert re.search(r'import\s*\{\s*API_BASE\s*\}\s*from\s*["\']\.\./lib/api\.js["\']', text)


def test_consent_js_only_calls_the_pending_consent_endpoints() -> None:
    text = _read(CONSENT_JS)
    fetch_targets = re.findall(r"fetch\(\s*`([^`]*)`", text)
    assert len(fetch_targets) >= 3
    allowed = re.compile(r"^\$\{API_BASE\}(/me|/consent|/consent/accept|/consent/decline)$")
    offenders = [t for t in fetch_targets if not allowed.match(t)]
    assert offenders == [], f"consent.js calls non-whitelisted endpoint(s): {offenders}"


def _strip_js_comments(text: str) -> str:
    """Drop `//`-prefixed comment lines. consent.js's own header comment
    documents the whitelist in prose (naming the routes it must NOT call),
    which would otherwise trip a naive whole-file substring check on the
    very sentence declaring the invariant — mirrors
    test_policy_pages.py's identical comment-stripping for schema.sql."""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))


def test_consent_js_never_references_progress_record_or_tutor_routes() -> None:
    code_only = _strip_js_comments(_read(CONSENT_JS))
    assert "/progress" not in code_only
    assert "/record" not in code_only
    assert "/tutor" not in code_only


def test_consent_js_credentials_include_on_state_changing_calls() -> None:
    # accept/decline must carry the session cookie (credentials: "include"),
    # matching learner.js's own convention for every authenticated call.
    # Anchor on the actual fetch() call site (the template-literal target),
    # not a bare substring search — consent.js's own header comment also
    # mentions "/consent/accept" in prose, earlier in the file.
    text = _read(CONSENT_JS)
    accept_idx = text.index("fetch(`${API_BASE}/consent/accept`")
    decline_idx = text.index("fetch(`${API_BASE}/consent/decline`")
    # Look at a reasonable window after each call site for the credentials
    # option, tolerant of formatting rather than pinned to exact spacing.
    assert 'credentials: "include"' in text[accept_idx : accept_idx + 300]
    assert 'credentials: "include"' in text[decline_idx : decline_idx + 300]


# --- the check-scripts' whitelists were extended, precisely ----------------


def test_check_static_auth_excludes_consent_from_the_learner_panel_invitation_check() -> None:
    text = _read(CHECK_STATIC_AUTH)
    assert re.search(r'NOT_A_LEARNER_PANEL_PAGE\s*=\s*new Set\(\[[^\]]*"consent"[^\]]*\]\)', text)


def test_check_static_auth_has_a_precise_consent_whitelist_not_a_blanket_one() -> None:
    text = _read(CHECK_STATIC_AUTH)
    assert "CONSENT_ALLOWED_SUFFIX_RE" in text
    # Precise: an enumerated set of exact suffixes, not an open prefix like
    # learner.js's `/auth/` (which allows any /auth/* sub-route).
    assert r"/consent\/accept$" in text or r"\/consent\/accept$" in text
    assert r"/consent\/decline$" in text or r"\/consent\/decline$" in text


def test_check_export_pages_excludes_consent_from_orphan_page_detection() -> None:
    text = _read(CHECK_EXPORT_PAGES)
    assert re.search(r'KNOWN_NON_SUBJECT_DIRS\s*=\s*new Set\(\[[^\]]*"consent"[^\]]*\]\)', text)


# --- cross-check against the worker's actual response shape ----------------


def test_worker_consent_requirement_field_names_match_what_consent_js_reads() -> None:
    worker_text = _read(WORKER_CONSENT)
    js_text = _read(CONSENT_JS)
    for field in ("terms_version", "effective_date", "terms_url", "privacy_url"):
        assert field in worker_text, f"workers/learn-api/src/consent.js must return {field}"
        assert field in js_text, f"consent.js must read {field} off the response"


def test_rendered_consent_page_matches_the_shared_version_when_built() -> None:
    """Same proof test_policy_pages.py runs for terms/privacy: once
    `npm run build` has produced dist/, the literal version string must
    appear in the built consent page. Skips gracefully when dist/ hasn't
    been built (the normal case in the Python test job — see module
    docstring; Node/npm build+check is the complementary proof)."""
    text = _read(ROOT / "shared" / "terms-version.mjs")
    version_match = re.search(r'export const TERMS_VERSION = "([^"]+)";', text)
    assert version_match
    dist_html = ROOT / "site-astro" / "dist" / "consent" / "index.html"
    if not dist_html.is_file():
        return
    html = dist_html.read_text(encoding="utf-8")
    assert version_match.group(1) in html
