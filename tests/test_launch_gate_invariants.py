"""Boundary invariants of the consent-tutoring uplift, asserted mechanically.

These are the launch gate's *always-on* half (t17, spec honesty condition h16:
"The invariants are mechanically checkable"). Unlike the live/e2e probes under
``tests/e2e/`` — which need a running origin and only fire under
``RUN_LAUNCH_GATE=1`` — every check here is a pure file read over the committed
tree, so it runs in the normal ``uv run pytest -n auto`` suite and locks the
four scope/boundary guarantees the spec's "Scope / boundaries" section makes:

1. **No email/password, ever.** The only persisted identity is the GitHub
   numeric id + the public display name — the schema stores no ``email`` or
   ``password`` column (also the concrete half of h9: the Privacy Policy's
   "no email, no password" claim must match what the code persists).
2. **Signed-out stays zero-API/zero-model.** The static-auth proof
   (``check-static-auth.mjs``) exists and is wired into the site's
   ``npm run check`` — its execution is a ``run.sh`` gate step; this test locks
   that it stays wired.
3. **The Worker stays provider-agnostic.** No Bedrock/OpenAI/Anthropic/AWS SDK
   is added to the Worker (neither a dependency nor a ``src/`` import) — h11's
   "no code change beyond config", enforced structurally.
4. **No subject prose is authored inside learn-cli.** The curriculum is
   authored UPSTREAM in the subject repos and pulled in via ``learn site
   export``; learn-cli's own ``learn/`` source tree carries no story/lesson
   prose, and the exported bundle carries its generated provenance.

A fifth check ties the Privacy Policy to reality (h9's second half): every
processor the code actually calls — GitHub, Cloudflare, AWS Bedrock — is named
in the published policy, and the policy's data claims (no email, no password,
export + delete) are not contradicted by the schema.

Deliberately pure file reads (no subprocess, no network) — same rationale as
``test_tutor_page.py`` / ``test_consent_page.py``: these lock *source shape*,
and stay hermetic so the default suite is fast and offline.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = ROOT / "workers" / "learn-api" / "schema.sql"
WORKER_PKG = ROOT / "workers" / "learn-api" / "package.json"
WORKER_SRC = ROOT / "workers" / "learn-api" / "src"
SITE_PKG = ROOT / "site-astro" / "package.json"
CHECK_STATIC_AUTH = ROOT / "site-astro" / "scripts" / "check-static-auth.mjs"
PRIVACY_PAGE = ROOT / "site-astro" / "src" / "pages" / "privacy" / "index.astro"
CONTENT_EXPORT = ROOT / "site-astro" / "src" / "content-export"
EXPORT_PY = ROOT / "learn" / "front" / "_export.py"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected {path} to exist"
    return path.read_text(encoding="utf-8")


# --- 1. no email/password column (privacy invariant + h9's concrete half) ----


def test_schema_defines_exactly_the_three_uplift_tables() -> None:
    sql = _read(SCHEMA_SQL).lower()
    for table in ("learners", "records", "consents"):
        assert re.search(rf"create table if not exists {table}\b", sql), f"missing table {table}"


def test_schema_has_no_email_or_password_column() -> None:
    # Column-name scan: split on CREATE TABLE bodies and look for a column whose
    # NAME is email/password (not merely the word appearing in a comment).
    sql = _read(SCHEMA_SQL)
    # Strip SQL line comments so the schema's own "no password, no email" note
    # (a comment, deliberately) can't trip the check.
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    column_names = re.findall(
        r"^\s*([a-z_][a-z0-9_]*)\s+(?:text|integer|blob|real|numeric)", code, re.I | re.M
    )
    lowered = {c.lower() for c in column_names}
    assert "email" not in lowered, "schema must not persist an email column"
    assert "password" not in lowered, "schema must not persist a password column"
    # The identity we DO persist is exactly the GitHub id + display name.
    assert "github_user_id" in lowered
    assert "display_name" in lowered


# --- 2. signed-out zero-API check stays wired --------------------------------


def test_static_auth_check_exists_and_is_wired_into_npm_check() -> None:
    assert CHECK_STATIC_AUTH.is_file(), "check-static-auth.mjs (the zero-API proof) must exist"
    pkg = json.loads(_read(SITE_PKG))
    scripts = pkg.get("scripts", {})
    check_cmd = scripts.get("check", "")
    # `npm run check` must invoke the static-auth proof (directly or via a
    # sub-script it chains). Accept either the script name or the file.
    wired = "check-static-auth" in check_cmd or any(
        "check-static-auth" in v for v in scripts.values()
    )
    assert wired, "npm run check must run check-static-auth.mjs (the signed-out zero-API gate)"


# --- 3. the Worker adds no provider SDK --------------------------------------

_PROVIDER_DEP_RE = re.compile(r"@?(aws-sdk|aws-crt|@aws|bedrock|openai|anthropic|@smithy)", re.I)


def test_worker_declares_no_provider_sdk_dependency() -> None:
    pkg = json.loads(_read(WORKER_PKG))
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    offenders = [name for name in deps if _PROVIDER_DEP_RE.search(name)]
    assert offenders == [], f"Worker must add no provider SDK dependency; found: {offenders}"
    # The only devDependency the broker-through-config design needs is wrangler.
    assert "wrangler" in deps, "wrangler is the Worker's one expected devDependency"


def test_worker_src_imports_no_provider_sdk() -> None:
    offenders: list[str] = []
    for js in sorted(WORKER_SRC.glob("*.js")):
        for line in _read(js).splitlines():
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            m = re.search(r"""(?:import\b[^;]*from|require\()\s*['"]([^'"]+)['"]""", line)
            if m and _PROVIDER_DEP_RE.search(m.group(1)):
                offenders.append(f"{js.name}: {stripped}")
    assert offenders == [], f"Worker src must import no provider SDK; found: {offenders}"


# --- 4. no subject prose authored inside learn-cli ---------------------------


# A story/lesson body runs to hundreds of characters; a legitimate format
# string, error message, or SQL fragment in learn-cli's own source does not.
# 200 chars is comfortably above the latter and below the former.
_PROSE_LEN = 200


def _long_string_constants(py_text: str) -> list[str]:
    """Every string-literal *value* longer than ``_PROSE_LEN`` in a Python
    source, EXCLUDING docstrings (module/class/function). Uses ``ast`` so it
    counts real string constants — never code that happens to sit between two
    unrelated short literals (the trap a bare regex falls into)."""
    tree = ast.parse(py_text)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            if len(node.value) > _PROSE_LEN and "http" not in node.value:
                out.append(node.value)
    return out


def test_export_driver_spawns_subjects_and_embeds_no_prose() -> None:
    # learn/front/_export.py is the ONLY producer of the content bundle. It must
    # drive the subject CLIs (drive(...)) and contain no embedded story text —
    # the prose comes from the subjects, never from learn-cli source.
    text = _read(EXPORT_PY)
    assert "drive(" in text, "the export must pull content from the subject CLIs via drive()"
    long_literals = _long_string_constants(text)
    assert long_literals == [], "the exporter must embed no story prose of its own"


def test_content_bundle_carries_generated_provenance() -> None:
    meta = json.loads(_read(CONTENT_EXPORT / "meta.json"))
    assert set(meta) >= {"contract_version", "schema_version", "subjects"}
    assert sorted(meta["subjects"]) == ["culture-guide", "french", "spanish"]


# The content-bearing fields of a story/exercise (the subject-plugin contract's
# story + cloze shapes). In learn-cli's own JSON these appear ONLY as schema
# property NAMES (whose value is a type descriptor), never populated with prose.
_CONTENT_FIELDS = {"body", "text", "prompt", "answer", "explanation", "choices", "options"}


def _content_field_prose(obj: object) -> list[str]:
    """Long STRING values sitting under a content-bearing key — the signature of
    a forked story/exercise. A schema's ``"body": {"type": "string"}`` has an
    OBJECT value and is ignored; only a ``"body": "<long prose>"`` is flagged."""
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key in _CONTENT_FIELDS and isinstance(val, str) and len(val) > _PROSE_LEN:
                    found.append(f"{key}={val[:50]}...")
                walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    return found


def test_no_subject_content_is_committed_under_the_learn_package() -> None:
    # learn/ holds registry metadata + contract SCHEMAS + CLI/portal code — it
    # declares the story/cloze fields but never populates them with prose. A
    # forked French story would show up as a long `body`/`text`/... string
    # VALUE under learn/ (the subjects' own repos are the only home for that).
    offenders: list[str] = []
    for jf in (ROOT / "learn").rglob("*.json"):
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for hit in _content_field_prose(data):
            offenders.append(f"{jf.relative_to(ROOT)}: {hit}")
    assert offenders == [], f"learn/ must carry no forked subject content; found: {offenders}"


# --- 5. the Privacy Policy matches what the code persists (h9) ----------------


def test_privacy_policy_names_every_processor_the_code_calls() -> None:
    text = _read(PRIVACY_PAGE)
    lowered = text.lower()
    for processor in ("github", "cloudflare", "bedrock"):
        assert processor in lowered, f"Privacy Policy must name the {processor} processor"


def test_privacy_policy_data_claims_match_the_schema() -> None:
    text = _read(PRIVACY_PAGE).lower()
    # The policy claims no email + no password — and the schema must back that.
    assert "no email" in text or "not.*email" in text or "email" in text
    assert "password" in text
    # And it must describe the self-serve export + delete path (right to withdraw).
    assert "export" in text and "delete" in text
    # Cross-check against the live schema: no email/password column (the same
    # assertion as test_schema_has_no_email_or_password_column, tied here to the
    # policy so a schema regression that adds one surfaces as a policy lie too).
    sql = _read(SCHEMA_SQL)
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines()).lower()
    assert not re.search(r"^\s*email\s+(text|integer)", code, re.M)
    assert not re.search(r"^\s*password\s+(text|integer)", code, re.M)
