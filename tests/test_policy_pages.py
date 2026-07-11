"""Terms of Use + Privacy Policy — the versioned /learn-local pages (t1).

Cross-checks the policy pages' *claims* against what the rest of the repo
actually does, rather than trusting the prose:

* the published TERMS_VERSION/TERMS_EFFECTIVE_DATE live in exactly ONE place
  (``shared/terms-version.mjs``) and both the Astro site and the Worker
  re-export from that same path, never a hardcoded copy;
* both policy pages render the version by importing those constants, not by
  spelling the version number out themselves — so what's rendered cannot
  drift from the shared source (spec #11, honesty condition h9);
* the Privacy Policy names all three data processors the code actually
  calls (GitHub, Cloudflare, AWS Bedrock) and states the Bedrock disclosure
  explicitly (speech/text leaves to the model provider, approved tier only);
* the Privacy Policy's "no email, no password" claim is checked against
  ``workers/learn-api/schema.sql`` itself, not just against the prose next to
  it — if a future migration ever added an email/password column, this test
  would fail even though nobody touched this file.

Deliberately pure file reads (like ``tests/conftest.py``'s fixtures and
``tests/test_site_export.py``) — no ``npm``/``astro build``/Node subprocess,
since the CI ``test`` job (``uv run pytest``, see ``.github/workflows/tests.yml``)
never provisions Node. ``site-astro/scripts/check-export-pages.mjs`` and
``check-static-auth.mjs`` (run via ``npm run check`` after ``npm run build``,
wired into ``deploy-site.yml``) are the complementary build-time proof that
the pages actually compile and stay consistent with the rest of the site.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED_TERMS = ROOT / "shared" / "terms-version.mjs"
WORKER_TERMS = ROOT / "workers" / "learn-api" / "src" / "terms.js"
SITE_TERMS = ROOT / "site-astro" / "src" / "lib" / "terms.ts"
TERMS_PAGE = ROOT / "site-astro" / "src" / "pages" / "terms" / "index.astro"
PRIVACY_PAGE = ROOT / "site-astro" / "src" / "pages" / "privacy" / "index.astro"
SCHEMA = ROOT / "workers" / "learn-api" / "schema.sql"
FOOTER = ROOT / "site-astro" / "src" / "components" / "Footer.astro"

REEXPORT_PATH = "../../../shared/terms-version.mjs"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected {path} to exist"
    return path.read_text(encoding="utf-8")


def _shared_terms() -> dict[str, str]:
    text = _read(SHARED_TERMS)
    version = re.search(r'export const TERMS_VERSION = "([^"]+)";', text)
    date = re.search(r'export const TERMS_EFFECTIVE_DATE = "([^"]+)";', text)
    assert version, "shared/terms-version.mjs must export TERMS_VERSION"
    assert date, "shared/terms-version.mjs must export TERMS_EFFECTIVE_DATE"
    return {"version": version.group(1), "date": date.group(1)}


# --- the single source of truth ------------------------------------------------


def test_shared_terms_version_starts_at_1_0_0_dated_today() -> None:
    terms = _shared_terms()
    assert terms["version"] == "1.0.0"
    assert terms["date"] == "2026-07-11"


def test_shared_terms_version_is_semver() -> None:
    assert re.match(r"^\d+\.\d+\.\d+$", _shared_terms()["version"])


def test_worker_reexports_the_shared_source_not_a_copy() -> None:
    text = _read(WORKER_TERMS)
    assert REEXPORT_PATH in text, "workers/learn-api/src/terms.js must re-export the shared file"
    assert '"1.0.0"' not in text, "the worker wrapper must not hardcode the version itself"


def test_site_reexports_the_shared_source_not_a_copy() -> None:
    text = _read(SITE_TERMS)
    assert REEXPORT_PATH in text, "site-astro/src/lib/terms.ts must re-export the shared file"
    assert '"1.0.0"' not in text, "the site wrapper must not hardcode the version itself"


# --- both pages render the version by importing it, not by copying it ---------


def _assert_page_imports_terms(page: Path) -> None:
    text = _read(page)
    import_re = (
        r"import\s*\{\s*TERMS_VERSION\s*,\s*TERMS_EFFECTIVE_DATE\s*\}"
        r'\s*from\s*"\.\./\.\./lib/terms"'
    )
    assert re.search(
        import_re, text
    ), f"{page.name} must import TERMS_VERSION/TERMS_EFFECTIVE_DATE from ../../lib/terms"
    # The literal version string must appear nowhere in the page source — if
    # it did, the page could drift from shared/terms-version.mjs by editing
    # only one of the two files.
    assert "1.0.0" not in text


def test_terms_page_renders_the_version_via_the_shared_import() -> None:
    _assert_page_imports_terms(TERMS_PAGE)
    text = _read(TERMS_PAGE)
    assert "{TERMS_VERSION}" in text
    assert "{TERMS_EFFECTIVE_DATE}" in text
    assert "Version" in text and "Effective" in text


def test_privacy_page_renders_the_version_via_the_shared_import() -> None:
    _assert_page_imports_terms(PRIVACY_PAGE)
    text = _read(PRIVACY_PAGE)
    assert "{TERMS_VERSION}" in text
    assert "{TERMS_EFFECTIVE_DATE}" in text
    assert "Version" in text and "Effective" in text


def test_rendered_version_matches_the_shared_source_when_built() -> None:
    """If `npm run build` has produced dist/, the literal version string must
    appear in both built pages — the strongest available proof once a build
    exists. Skips gracefully when dist/ hasn't been built (the normal case
    in the Python test job, which never runs Node — see module docstring)."""
    terms = _shared_terms()
    dist = ROOT / "site-astro" / "dist"
    terms_html = dist / "terms" / "index.html"
    privacy_html = dist / "privacy" / "index.html"
    if not terms_html.is_file() or not privacy_html.is_file():
        return
    for built in (terms_html, privacy_html):
        html = built.read_text(encoding="utf-8")
        assert terms["version"] in html
        assert terms["date"] in html


# --- footer links both pages ---------------------------------------------------


def test_footer_links_terms_and_privacy() -> None:
    text = _read(FOOTER)
    assert "terms/" in text
    assert "privacy/" in text


# --- Privacy Policy: processors, collected data, retention, rights ------------


def test_privacy_policy_names_all_three_processors() -> None:
    text = _read(PRIVACY_PAGE)
    assert "GitHub" in text
    assert "Cloudflare" in text
    assert "AWS Bedrock" in text


def test_privacy_policy_calls_out_bedrock_speech_text_disclosure() -> None:
    text = _read(PRIVACY_PAGE)
    assert "Nova Sonic 2" in text
    assert "Nova Pro" in text
    # The explicit "your data leaves to the model provider" callout, scoped
    # to the approved tier only (spec requirement, honesty condition h9).
    assert "sent to AWS Bedrock" in text
    assert "approved" in text.lower()


def test_privacy_policy_states_what_is_collected() -> None:
    text = _read(PRIVACY_PAGE)
    assert "GitHub numeric id" in text
    assert "display name" in text
    assert "ledger" in text.lower()
    assert "mastery" in text.lower()
    assert "session cookie" in text.lower()


def test_privacy_policy_explicitly_disclaims_email_and_password() -> None:
    text = _read(PRIVACY_PAGE)
    assert "do not collect or store your email" in text.lower()
    assert "do not collect or store a password" in text.lower()


def test_privacy_policy_states_why_data_is_collected() -> None:
    text = _read(PRIVACY_PAGE)
    lowered = text.lower()
    assert "authenticate" in lowered
    assert "progress across subjects" in lowered
    assert "personalize" in lowered


def test_privacy_policy_states_retention() -> None:
    text = _read(PRIVACY_PAGE).lower()
    assert "kept for as long as your account exists" in text
    assert "hard-deleted" in text


def test_privacy_policy_states_the_learner_rights() -> None:
    text = _read(PRIVACY_PAGE).lower()
    for right in ("access", "export", "delete", "withdraw consent"):
        assert right in text, f"Privacy Policy must state the right to {right}"


def test_privacy_policy_contact_point_is_the_issue_tracker_not_an_email() -> None:
    text = _read(PRIVACY_PAGE)
    assert "github.com/agentculture/learn-cli" in text
    assert "@" not in text, "no personal email address should be published in the policy"


# --- Terms of Use: the decisions recorded in the plan (risk r5) ---------------


def test_terms_of_use_covers_the_recorded_drafting_decisions() -> None:
    text = _read(TERMS_PAGE)
    lowered = text.lower()
    assert "github" in lowered  # GitHub-based accounts
    assert "as is" in lowered  # service provided "as is"
    assert "approved" in lowered and ("bedrock" in lowered or "tutoring" in lowered)
    assert "belongs to you" in lowered or "yours" in lowered  # data ownership
    assert "termination" in lowered or "suspend" in lowered  # termination/suspension
    assert "re-consent" in lowered  # changes -> version bump -> re-consent
    assert "github.com/agentculture/learn-cli" in text  # contact point


def test_terms_of_use_contact_point_is_the_issue_tracker_not_an_email() -> None:
    text = _read(TERMS_PAGE)
    assert "@" not in text, "no personal email address should be published in the terms"


# --- the schema itself backs the "no email, no password" claim ----------------


def test_schema_has_no_email_or_password_column_anywhere() -> None:
    # Strip `--` comment lines first: schema.sql's own header comment SAYS
    # "no password, no email" in prose, which would otherwise trip a naive
    # whole-file substring check on the very sentence declaring the
    # invariant. What must actually be absent is a COLUMN, not the word.
    code_only = "\n".join(
        line for line in _read(SCHEMA).lower().splitlines() if not line.strip().startswith("--")
    )
    assert "email" not in code_only
    assert "password" not in code_only


def test_schema_learners_table_columns_have_no_email_or_password() -> None:
    schema = _read(SCHEMA)
    match = re.search(r"CREATE TABLE IF NOT EXISTS learners \((.*?)\n\);", schema, re.S)
    assert match, "expected a `learners` table definition in schema.sql"
    columns = match.group(1).lower()
    assert "email" not in columns
    assert "password" not in columns
