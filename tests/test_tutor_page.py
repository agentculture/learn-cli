"""The tutor surface (t15, spec c24/h11 — Nova Pro through the existing broker).

Locks the approved-tier tutor panel's key claims and wiring against drift,
the same way ``tests/test_consent_page.py`` does for the consent page:

* the surface renders ONLY for approved learners (``me.learner.approved``):
  the tutor controls ship hidden and are revealed by ``tutor.js`` after the
  approved check; a signed-in but non-approved learner sees a "tutoring is
  admin-approved" note instead; a signed-out visitor sees nothing (the whole
  panel is ``signedin-only``, hidden by the global CSS default);
* ``src/scripts/tutor.js`` is a dedicated script (NOT merged into
  ``learner.js``, NOT loaded globally by ``Layout.astro``) whose fetch
  surface is precisely three routes: ``POST /api/tutor``,
  ``GET /api/progress/:subject``, and ``POST /api/record`` — nothing wider;
* ``src/scripts/tutor-core.js`` is the PURE half (prompt builders, Converse
  parsers, the §3.6.1 cloze validator): no fetch, no DOM — importable by
  ``site-astro/scripts/check-tutor-logic.mjs``, the node-side unit suite
  that actually executes it (this file only locks source shape; execution
  coverage lives there, wired into ``npm run check``);
* payloads are Bedrock **Converse**-shaped (the live-verified target —
  Bedrock's OpenAI-compat surface does NOT serve Nova Pro), the system
  prompts pin the grading rubric and strict-JSON response format, and the
  generated cloze story is validated client-side against the contract
  (§3.6.1) INCLUDING the stable-``item_id`` join-key rule before it is shown
  or recorded;
* ``scripts/check-static-auth.mjs`` was extended precisely: an anchored
  tutor whitelist, not a blanket allowance, replacing the pre-t15 "never
  references /tutor" rule with "ONLY tutor.js's whitelisted fetch may";
* the wiring itself is config-only (h11): ``wrangler.toml`` records the
  exact Converse URL commented out (t17 flips it live), and the worker
  README documents the NO-GO/GO probe results.

Deliberately pure file reads (no npm/astro/node subprocess) — see
``test_consent_page.py``'s module docstring for why.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TUTOR_PANEL = ROOT / "site-astro" / "src" / "components" / "TutorPanel.astro"
SUBJECT_PAGE = ROOT / "site-astro" / "src" / "pages" / "[subject]" / "index.astro"
TUTOR_JS = ROOT / "site-astro" / "src" / "scripts" / "tutor.js"
TUTOR_CORE = ROOT / "site-astro" / "src" / "scripts" / "tutor-core.js"
LEARNER_JS = ROOT / "site-astro" / "src" / "scripts" / "learner.js"
LAYOUT = ROOT / "site-astro" / "src" / "layouts" / "Layout.astro"
CHECK_STATIC_AUTH = ROOT / "site-astro" / "scripts" / "check-static-auth.mjs"
CHECK_TUTOR_LOGIC = ROOT / "site-astro" / "scripts" / "check-tutor-logic.mjs"
SITE_PACKAGE_JSON = ROOT / "site-astro" / "package.json"
WRANGLER_TOML = ROOT / "workers" / "learn-api" / "wrangler.toml"
WORKER_README = ROOT / "workers" / "learn-api" / "README.md"

CONVERSE_URL = (
    "https://bedrock-runtime.us-east-1.amazonaws.com/model/us.amazon.nova-pro-v1:0/converse"
)


def _read(path: Path) -> str:
    assert path.is_file(), f"expected {path} to exist"
    return path.read_text(encoding="utf-8")


def _strip_js_comments(text: str) -> str:
    """Drop ``//``-prefixed comment lines (same rationale as
    test_consent_page.py: header comments document the routes a script must
    NOT call, which would trip a naive substring check)."""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))


# --- the surface exists, in the right places -------------------------------


def test_tutor_panel_component_exists_and_subject_pages_render_it() -> None:
    assert TUTOR_PANEL.is_file()
    page = _read(SUBJECT_PAGE)
    assert re.search(r"import\s+TutorPanel\s+from", page)
    assert "<TutorPanel" in page


def test_tutor_scripts_are_separate_files_not_a_learner_js_bloat() -> None:
    # tutor.js is a dedicated script pulled in by the panel component only —
    # Layout.astro (which loads learner.js on every page) must not import it.
    assert TUTOR_JS.is_file()
    assert TUTOR_CORE.is_file()
    assert "tutor" not in _read(LAYOUT)
    panel = _read(TUTOR_PANEL)
    assert re.search(r'import\s*["\']\.\./scripts/tutor\.js["\']', panel)


def test_learner_js_hook_is_minimal() -> None:
    # The ONE hook learner.js gains for t15: publish the already-fetched
    # /api/me payload for sibling scripts (tutor.js), so tutor.js needs no
    # /api/me call of its own. No tutor logic lives in learner.js.
    text = _read(LEARNER_JS)
    assert "__learnMe" in text
    assert "learn:me" in text
    code_only = _strip_js_comments(text)
    assert "/tutor" not in code_only
    assert "wireGrade" not in code_only and "hydrateTutorPanel" not in code_only


# --- the gate: approved-only, honest note for everyone else ----------------


def test_panel_is_signedin_only_so_signed_out_sees_nothing() -> None:
    text = _read(TUTOR_PANEL)
    root = re.search(r"<div[^>]*data-tutor-panel[^>]*>", text)
    assert root, "expected a data-tutor-panel root element"
    assert "signedin-only" in root.group(0)


def test_non_approved_learners_see_the_admin_approved_note() -> None:
    text = _read(TUTOR_PANEL)
    note = re.search(r"<p\b[^>]*data-tutor-gate-note[^>]*>(.*?)</p>", text, re.S)
    assert note, "expected a data-tutor-gate-note block"
    opening_tag = note.group(0).split(">")[0]
    assert "hidden" not in opening_tag, "the gate note must be visible by default"
    lowered = re.sub(r"\s+", " ", note.group(1)).lower()
    assert "admin" in lowered and "approv" in lowered


def test_tutor_controls_ship_hidden_until_the_approved_check() -> None:
    text = _read(TUTOR_PANEL)
    assert re.search(
        r"data-tutor-surface[^>]*\bhidden\b|\bhidden\b[^>]*data-tutor-surface", text
    ), "the tutor controls must ship with the hidden attribute in the static markup"


def test_tutor_js_reveals_the_surface_only_for_approved_learners() -> None:
    text = _read(TUTOR_JS)
    assert "me.learner.approved" in text
    # The unapproved early-return must come before any wiring/fetching:
    # extract hydrateTutorPanel's body and check order textually.
    start = text.index("function hydrateTutorPanel")
    bail = text.index("if (!approved)", start)
    assert "return" in text[bail : bail + 300]
    first_wire = min(
        idx
        for idx in (text.find("wireGrade(", start), text.find("wireNextStep(", start))
        if idx >= 0
    )
    assert bail < first_wire, "the approved check must precede all wiring"


# --- tutor.js fetch surface: precise, not blanket ---------------------------


def test_tutor_js_imports_the_single_api_base_constant() -> None:
    text = _read(TUTOR_JS)
    assert re.search(r'import\s*\{\s*API_BASE\s*\}\s*from\s*["\']\.\./lib/api\.js["\']', text)


def test_tutor_js_only_calls_tutor_progress_and_record() -> None:
    text = _read(TUTOR_JS)
    fetch_targets = re.findall(r"fetch\(\s*`([^`]*)`", text)
    assert len(fetch_targets) >= 3
    allowed = re.compile(r"^\$\{API_BASE\}(/tutor$|/progress/|/record$)")
    offenders = [t for t in fetch_targets if not allowed.match(t)]
    assert offenders == [], f"tutor.js calls non-whitelisted endpoint(s): {offenders}"


def test_tutor_js_never_references_the_other_authed_routes() -> None:
    code_only = _strip_js_comments(_read(TUTOR_JS))
    for route in ("/me", "/admin", "/export", "/delete", "/consent", "/auth"):
        assert f"{{API_BASE}}{route}" not in code_only, f"tutor.js must not call {route}"


def test_tutor_js_credentials_include_on_every_call() -> None:
    text = _read(TUTOR_JS)
    for target in ("/tutor`", "/record`"):
        idx = text.index(f"fetch(`${{API_BASE}}{target}")
        assert 'credentials: "include"' in text[idx : idx + 300]


# --- tutor-core.js: pure, Converse-shaped, rubric-pinning -------------------


def test_tutor_core_is_pure_no_fetch_no_dom() -> None:
    code_only = _strip_js_comments(_read(TUTOR_CORE))
    assert "fetch(" not in code_only
    assert "document." not in code_only
    assert "window." not in code_only


def test_payloads_are_converse_shaped() -> None:
    # The live-verified Bedrock-direct shape (the OpenAI-compat surface does
    # NOT serve Nova Pro): system:[{text}], messages:[{role, content:[{text}]}],
    # inferenceConfig:{maxTokens, temperature}.
    text = _read(TUTOR_CORE)
    assert re.search(r"system:\s*\[\{\s*text:", text)
    assert re.search(r'role:\s*"user",\s*content:\s*\[\{\s*text:', text)
    assert re.search(r"inferenceConfig:\s*\{\s*maxTokens", text)


def test_grade_prompt_pins_rubric_and_strict_json() -> None:
    text = _read(TUTOR_CORE)
    match = re.search(r"GRADE_SYSTEM_PROMPT\s*=(.+?);\s*$", text, re.S | re.M)
    assert match, "expected an exported GRADE_SYSTEM_PROMPT"
    prompt = match.group(1).lower()
    for token in ('"pass"', '"partial"', '"fail"', "json", "strict"):
        assert token in prompt, f"grade prompt must pin {token}"
    assert "only when" in prompt, "the rubric must be strict about what counts as pass"


def test_next_step_prompt_is_adaptive_over_weak_items() -> None:
    text = _read(TUTOR_CORE)
    match = re.search(r"NEXT_STEP_SYSTEM_PROMPT\s*=(.+?);\s*$", text, re.S | re.M)
    assert match, "expected an exported NEXT_STEP_SYSTEM_PROMPT"
    prompt = match.group(1).lower()
    assert "weak" in prompt
    assert "json" in prompt


def test_cloze_prompt_pins_the_contract_shape_and_the_join_key() -> None:
    text = _read(TUTOR_CORE)
    match = re.search(r"CLOZE_SYSTEM_PROMPT\s*=(.+?);\s*$", text, re.S | re.M)
    assert match, "expected an exported CLOZE_SYSTEM_PROMPT"
    prompt = match.group(1)
    assert "{{" in prompt, "must pin the {{blank_id}} marker syntax"
    for token in ("blanks", "options", "answer", "item_id"):
        assert token in prompt
    assert "verbatim" in prompt.lower(), "item_id must be pinned as a verbatim join key"


def test_cloze_validator_enforces_the_contract_and_the_join_key() -> None:
    # §3.6.1 client-side validation, plus the t15 rule that the generated
    # story's item_id reuses an EXISTING weak item's id (stable join key).
    text = _read(TUTOR_CORE)
    assert "validateClozeStory" in text
    assert re.search(r"options\.length\s*<\s*2", text), "must require >= 2 options"
    assert re.search(r"options\.(includes|indexOf)", text), "answer must be one of options"
    assert re.search(r"\\\{\\\{|\{\\\{", text), "must parse {{blank_id}} placeholders"
    assert "weakItemIds" in text, "item_id must be checked against the weak-item join keys"
    # prompt/answer fallback fields (§3.6.1: kept present as the
    # driver-facing instruction on a well-authored pick-the-right-word item).
    assert re.search(r'"prompt"|story\.prompt', text)
    assert re.search(r'"answer"|story\.answer', text)


def test_cloze_record_is_contract_valid_with_existing_fields_only() -> None:
    # The played story records through the EXISTING POST /api/record shape:
    # correct/total tallies, activity "practice" — and never the derived
    # score/grade/points fields the worker rejects.
    text = _read(TUTOR_CORE)
    assert "buildClozeRecord" in text
    assert re.search(r'activity:\s*"practice"', text)
    assert "correct" in text and "total" in text
    code_only = _strip_js_comments(text)
    for forbidden in ("score:", "grade:", "points:"):
        assert forbidden not in code_only, f"recorded must not carry {forbidden}"


# --- check-static-auth: extended precisely, not loosened --------------------


def test_check_static_auth_has_an_anchored_tutor_whitelist() -> None:
    text = _read(CHECK_STATIC_AUTH)
    assert "TUTOR_ALLOWED_SUFFIX_RE" in text
    assert re.search(r"\\/tutor\$", text), "the /tutor suffix must be anchored ($), not a prefix"


def test_check_static_auth_built_bundle_union_includes_the_tutor_whitelist() -> None:
    text = _read(CHECK_STATIC_AUTH)
    union = re.search(
        r"ALLOWED_SUFFIX_RE\.test\(suffix\)\s*\|\|\s*CONSENT_ALLOWED_SUFFIX_RE\.test\(suffix\)"
        r"\s*\|\|\s*VOICE_ALLOWED_SUFFIX_RE\.test\(suffix\)"
        r"\s*\|\|\s*TUTOR_ALLOWED_SUFFIX_RE\.test\(suffix\)",
        text,
    )
    assert union, "the built-bundle whitelist must be the union of all four per-script REs"


def test_check_static_auth_still_polices_stray_tutor_references() -> None:
    # The pre-t15 blanket rule ("referenced nowhere") is gone by design, but
    # its replacement must still exist and still FAIL on a /tutor reference
    # outside tutor.js's whitelisted fetch calls.
    text = _read(CHECK_STATIC_AUTH)
    assert re.search(r"referenced ONLY", text), "expected the precise stray-/tutor check"
    assert "learner.js" in text and "consent.js" in text  # the older checks stay


# --- execution coverage: the node-side unit suite is wired into the gate ----


def test_tutor_logic_unit_suite_exists_and_runs_in_npm_check() -> None:
    assert CHECK_TUTOR_LOGIC.is_file()
    text = _read(CHECK_TUTOR_LOGIC)
    # It executes the pure module — not a source-grep like this file.
    assert "tutor-core.js" in text
    for fn in ("parseGradeResponse", "validateClozeStory", "buildClozeRecord"):
        assert fn in text
    pkg = _read(SITE_PACKAGE_JSON)
    assert "check:tutor-logic" in pkg
    run_check = re.search(r'"check":\s*"([^"]+)"', pkg)
    assert run_check and "check:tutor-logic" in run_check.group(1)


# --- the wiring is config-only (h11): recorded, not enabled -----------------


def test_wrangler_records_the_converse_url_commented_out() -> None:
    text = _read(WRANGLER_TOML)
    assert CONVERSE_URL in text
    for line in text.splitlines():
        if CONVERSE_URL in line:
            assert line.lstrip().startswith("#"), "INFERENCE_URL must NOT be set live by t15"
    # No uncommented INFERENCE_URL assignment anywhere.
    assert not re.search(r"^\s*INFERENCE_URL\s*=", text, re.M)


def test_wrangler_comment_block_records_model_region_secret_and_cost() -> None:
    text = _read(WRANGLER_TOML)
    assert "us.amazon.nova-pro-v1:0" in text
    assert "us-east-1" in text
    assert "AWS_BEDROCK_API_KEY_SECRET" in text
    assert "wrangler secret put INFERENCE_TOKEN" in text
    lowered = text.lower()
    assert "per-token" in lowered and "idle" in lowered  # cost-when-busy note


def test_worker_readme_records_the_probe_results_and_shipped_wiring() -> None:
    text = _read(WORKER_README)
    assert CONVERSE_URL in text
    lowered = text.lower()
    assert "model_not_found" in lowered, "the OpenAI-compat NO-GO must be recorded"
    assert "converse" in lowered
    assert "latencyms" in lowered, "the sanitized live re-verification result must be quoted"
    assert "us.amazon.nova-pro-v1:0" in text
    # The stale pre-t15 instruction (cloudai/ec2bedrock served endpoint as THE
    # target) must no longer be the documented wiring for INFERENCE_URL.
    assert "cloudai-or-ec2bedrock-served-endpoint" not in text
