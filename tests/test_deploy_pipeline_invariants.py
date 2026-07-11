"""Mechanical boundary invariants of the deploy-worker CI pipeline.

Task t3 of the 2026-07-11 "learn-cli ships a one-command-free deployment
pipeline" plan (``docs/plans/2026-07-11-learn-cli-ships-a-one-command-free-
deployment-pipe.md``). ``.github/workflows/deploy-worker.yml`` (t2) is the
*only* thing that ever runs ``wrangler deploy`` — a mistake there silently
promotes an untested Worker to production, or leaks a secret into a process
list, or drifts the schema out of idempotency and breaks a re-run. None of
that shows up as a Python test failure on its own, so this file locks the
workflow's and ``schema.sql``'s *shape* directly:

1. The production ``wrangler deploy`` step and the production D1 apply step
   (``d1 execute learn-ledger --remote``) are both gated to
   ``github.ref == 'refs/heads/main'`` (or a job-level
   ``environment: production``) — the boundary that keeps a branch
   ``workflow_dispatch`` run from ever touching prod.
2. The workflow never shells out to the SAM CLI and never references
   ``infra/`` — the voice-bridge stack (task t16) is out of scope for this
   pipeline entirely.
3. The workflow deploys the top-level ``workers/learn-api/wrangler.toml``
   and never ``wrangler.signedout.toml``.
4. Every ``wrangler secret put`` line pipes its value over stdin
   (``printf '%s' "$VALUE" | wrangler secret put NAME``) — a secret value
   must never appear as a literal CLI argument, where it would land in a
   process listing. All five Worker secrets are synced on both the prod and
   the preview path.
5. ``schema.sql`` is idempotent: every ``CREATE TABLE``/``CREATE INDEX``
   statement uses ``IF NOT EXISTS``, so re-applying it against a live D1 is a
   safe no-op.
6. The preview path only ever runs the non-promoting
   ``wrangler versions upload --env preview``; the promoting
   ``wrangler deploy`` appears exactly once and only under the main-ref
   guard — the two paths can never both fire in one run (h3/h11).

Deliberately pure file reads (no subprocess, no network, no wrangler/gh
invocation) — same rationale as ``test_launch_gate_invariants.py``: these
lock *source shape* and stay hermetic so the default suite is fast and
offline. The workflow is parsed as text/regex rather than through a YAML
library (PyYAML is a project dependency and available, but a plain-text,
step-block split avoids YAML's own gotchas here — e.g. a bare ``on:`` key
being cast to the boolean ``True`` under the YAML 1.1 rules PyYAML's
``safe_load`` still applies — and keeps this file dependency-free, matching
``test_launch_gate_invariants.py``'s own style).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_YML = ROOT / ".github" / "workflows" / "deploy-worker.yml"
SCHEMA_SQL = ROOT / "workers" / "learn-api" / "schema.sql"

_SECRET_NAMES = (
    "SESSION_SECRET",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "INFERENCE_TOKEN",
    "VOICE_TOKEN_SECRET",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"expected {path} to exist"
    return path.read_text(encoding="utf-8")


# --- text-only step splitting -------------------------------------------------
# Each GitHub Actions step starts with a `- name:` or `- uses:` marker at the
# step-list indentation. Slicing the raw text at those markers keeps a step's
# `if:`/`working-directory:`/`run:` lines together for block-local regex
# checks, without needing a YAML parser.

_STEP_START_RE = re.compile(r"^( *)- (?:name|uses):", re.M)


def _step_blocks(text: str) -> list[str]:
    starts = [m.start() for m in _STEP_START_RE.finditer(text)]
    assert starts, "expected at least one `- name:`/`- uses:` step marker in the workflow"
    starts.append(len(text))
    return [text[starts[i] : starts[i + 1]] for i in range(len(starts) - 1)]


def _step_matching(blocks: list[str], run_re: re.Pattern[str]) -> str:
    hits = [b for b in blocks if run_re.search(b)]
    assert len(hits) == 1, (
        f"expected exactly one step whose `run:` matches {run_re.pattern!r}, found {len(hits)}: "
        f"{hits!r}"
    )
    return hits[0]


def _strip_comment_lines(text: str) -> str:
    """Drop every full-line ``#`` comment.

    deploy-worker.yml's own header/step comments narrate the same invariants
    this file checks mechanically — a comment literally says "never
    wrangler.signedout.toml" (documenting the boundary, not violating it), so
    a naive substring search over the raw text would trip on the prose
    *asserting* the invariant. Mirrors test_launch_gate_invariants.py's SQL
    comment-stripping (``line.split("--", 1)[0]``) for the same reason: check
    the code, not the commentary about the code.
    """
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


# --- ref-gating helpers (acceptance 1 & 6) ------------------------------------

_MAIN_REF_RE = re.compile(r"github\.ref\s*==\s*['\"]refs/heads/main['\"]")
_NOT_MAIN_REF_RE = re.compile(r"github\.ref\s*!=\s*['\"]refs/heads/main['\"]")
_PROD_ENVIRONMENT_RE = re.compile(r"^\s*environment:\s*['\"]?production['\"]?\s*$", re.M)


def _job_declares_production_environment(text: str) -> bool:
    # Job-level keys (env:, permissions:, environment:, ...) sit before the
    # first step marker, so restrict the search to that header region.
    first_step = _STEP_START_RE.search(text)
    header = text[: first_step.start()] if first_step else text
    return bool(_PROD_ENVIRONMENT_RE.search(header))


def _requires_main_ref(step_block: str) -> bool:
    return bool(_MAIN_REF_RE.search(step_block))


def _requires_non_main_ref(step_block: str) -> bool:
    return bool(_NOT_MAIN_REF_RE.search(step_block))


def _is_prod_gated(step_block: str, text: str) -> bool:
    return _requires_main_ref(step_block) or _job_declares_production_environment(text)


# --- command-matching regexes --------------------------------------------------
# All four require the `npx wrangler@<n>` prefix so a match only fires against
# an actual invocation line, never against the "Deployment summary" step's
# narrative `echo '... `wrangler deploy` ...'` text, which names the same
# commands in prose without the `npx` prefix.

_PROD_D1_RUN_RE = re.compile(r"npx\s+wrangler@?\d*\s+d1\s+execute\s+learn-ledger\s+--remote\b")
_PREVIEW_D1_RUN_RE = re.compile(
    r"npx\s+wrangler@?\d*\s+d1\s+execute\s+learn-ledger-preview\s+--remote\b"
)
_PROD_DEPLOY_RUN_RE = re.compile(r"npx\s+wrangler@?\d*\s+deploy\b")
_PREVIEW_UPLOAD_RUN_RE = re.compile(r"npx\s+wrangler@?\d*\s+versions\s+upload\s+--env\s+preview\b")

# A real `sam` CLI invocation, not a false positive on "same"/"same-origin".
_SAM_CLI_RE = re.compile(r"\bsam\s+(?:deploy|build|package|sync|validate)\b")

_SECRET_PUT_LINE_RE = re.compile(
    r"printf\s+'%s'\s+\"\$\{\{\s*secrets\.(\w+)\s*\}\}\"\s*\|\s*"
    r"npx\s+wrangler@?\d*\s+secret\s+put\s+(\w+)(?:\s+--env\s+\S+)?"
)


# --- 1. prod deploy + prod D1 apply are gated to the main ref -----------------


def test_prod_d1_apply_is_gated_to_main_ref() -> None:
    text = _read(WORKFLOW_YML)
    step = _step_matching(_step_blocks(text), _PROD_D1_RUN_RE)
    assert _is_prod_gated(step, text), (
        "the `d1 execute learn-ledger --remote` (production) step must require "
        "github.ref == 'refs/heads/main' (or a job-level environment: production); "
        f"step was:\n{step}"
    )


def test_prod_wrangler_deploy_is_gated_to_main_ref() -> None:
    text = _read(WORKFLOW_YML)
    step = _step_matching(_step_blocks(text), _PROD_DEPLOY_RUN_RE)
    assert _is_prod_gated(step, text), (
        "the `wrangler deploy` (production promote) step must require "
        "github.ref == 'refs/heads/main' (or a job-level environment: production); "
        f"step was:\n{step}"
    )


# --- 2. no sam / infra reference (voice bridge is out of scope) ---------------


def test_workflow_never_invokes_the_sam_cli() -> None:
    code = _strip_comment_lines(_read(WORKFLOW_YML))
    match = _SAM_CLI_RE.search(code)
    assert match is None, (
        "deploy-worker.yml must never shell out to the SAM CLI (voice bridge / "
        f"infra/ is out of scope for this workflow); found {match!r}"
    )


def test_workflow_never_references_the_infra_directory() -> None:
    code = _strip_comment_lines(_read(WORKFLOW_YML))
    assert "infra/" not in code, (
        "deploy-worker.yml must never reference infra/ (the SAM voice-bridge "
        "stack is out of scope for this workflow)"
    )


# --- 3. deploys the top-level wrangler.toml, never wrangler.signedout.toml ----


def test_workflow_never_deploys_the_signed_out_toml_variant() -> None:
    # The string "wrangler.signedout.toml" appears once in the raw file today,
    # but only inside a comment documenting the invariant ("never
    # wrangler.signedout.toml") — strip comments first so this targets actual
    # deploy commands, not prose that names the forbidden file while asserting
    # it's avoided.
    code = _strip_comment_lines(_read(WORKFLOW_YML))
    assert "wrangler.signedout.toml" not in code, (
        "the workflow must deploy the top-level workers/learn-api/wrangler.toml, "
        "never wrangler.signedout.toml"
    )


def test_workflow_never_redirects_wrangler_at_a_different_config_file() -> None:
    text = _read(WORKFLOW_YML)
    assert "--config" not in text, (
        "no step may pass wrangler a --config flag pointing away from the "
        "top-level workers/learn-api/wrangler.toml"
    )


# --- 4. secrets never appear as a CLI argument; all five are synced -----------


def test_every_secret_put_line_pipes_the_value_over_stdin() -> None:
    text = _read(WORKFLOW_YML)
    lines = [ln.strip() for ln in text.splitlines() if "secret put" in ln]
    assert lines, "expected at least one `wrangler secret put` invocation"
    for line in lines:
        match = _SECRET_PUT_LINE_RE.fullmatch(line)
        assert match, (
            "every `secret put` must receive its value over stdin "
            "(printf '%s' \"${{ secrets.X }}\" | wrangler secret put X [--env ...]), "
            f"never as a literal CLI argument; offending line: {line!r}"
        )
        piped_secret, put_name = match.group(1), match.group(2)
        assert piped_secret == put_name, (
            f"piped secret {piped_secret!r} must match the `secret put` target name "
            f"{put_name!r} on the same line: {line!r}"
        )


def _secret_put_lines(step_block: str) -> list[str]:
    # Line-scoped on purpose: a step's trailing comment (e.g. "never an --env
    # flag.", which sits between this step and the next marker and so is part
    # of this text block) must not be mistaken for step content like a real
    # `secret put ... --env preview` invocation.
    return [ln.strip() for ln in step_block.splitlines() if "secret put" in ln]


def test_all_five_worker_secrets_are_synced_on_the_prod_path() -> None:
    text = _read(WORKFLOW_YML)
    blocks = _step_blocks(text)
    prod_secret_blocks = [b for b in blocks if _secret_put_lines(b) and _requires_main_ref(b)]
    assert prod_secret_blocks, "expected a main-ref-gated step that syncs Worker secrets"
    lines = [ln for b in prod_secret_blocks for ln in _secret_put_lines(b) if "--env" not in ln]
    missing = [
        name for name in _SECRET_NAMES if not any(f"secret put {name}" in ln for ln in lines)
    ]
    assert not missing, f"prod secret sync (no --env, i.e. production) is missing: {missing}"


def test_all_five_worker_secrets_are_synced_on_the_preview_path() -> None:
    text = _read(WORKFLOW_YML)
    blocks = _step_blocks(text)
    preview_secret_blocks = [
        b for b in blocks if _secret_put_lines(b) and _requires_non_main_ref(b)
    ]
    assert preview_secret_blocks, "expected a non-main-ref-gated step that syncs Worker secrets"
    lines = [ln for b in preview_secret_blocks for ln in _secret_put_lines(b) if "--env" in ln]
    missing = [
        name for name in _SECRET_NAMES if not any(f"secret put {name}" in ln for ln in lines)
    ]
    assert not missing, f"preview secret sync (--env preview) is missing: {missing}"


# --- 5. schema.sql is idempotent -----------------------------------------------

_CREATE_ANY_RE = re.compile(r"\bcreate\s+(?:unique\s+)?(?:table|index)\b", re.I)
_CREATE_IDEMPOTENT_RE = re.compile(
    r"\bcreate\s+(?:unique\s+)?(?:table|index)\s+if\s+not\s+exists\b", re.I
)


def test_schema_statements_are_all_created_idempotently() -> None:
    sql = _read(SCHEMA_SQL)
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    all_creates = _CREATE_ANY_RE.findall(code)
    idempotent_creates = _CREATE_IDEMPOTENT_RE.findall(code)
    assert all_creates, "expected at least one CREATE TABLE/INDEX statement in schema.sql"
    assert len(idempotent_creates) == len(all_creates), (
        "every CREATE TABLE/INDEX in schema.sql must use IF NOT EXISTS so a "
        f"re-run is a safe no-op (found {len(all_creates)} CREATE statement(s), "
        f"{len(idempotent_creates)} idempotent)"
    )


# --- 6. preview safety: non-promoting upload, promote only under main --------


def test_preview_path_uses_non_promoting_versions_upload() -> None:
    text = _read(WORKFLOW_YML)
    step = _step_matching(_step_blocks(text), _PREVIEW_UPLOAD_RUN_RE)
    assert _requires_non_main_ref(step), (
        "`wrangler versions upload --env preview` must run only off a non-main "
        f"ref (branch dispatch), never on push-to-main; step was:\n{step}"
    )
    assert not _PROD_DEPLOY_RUN_RE.search(
        step
    ), "the preview upload step must never also run `wrangler deploy` (promote)"


def test_wrangler_deploy_promote_appears_only_once_and_only_under_main_guard() -> None:
    text = _read(WORKFLOW_YML)
    blocks = _step_blocks(text)
    deploy_blocks = [b for b in blocks if _PROD_DEPLOY_RUN_RE.search(b)]
    assert len(deploy_blocks) == 1, (
        "expected exactly one step that runs `wrangler deploy` (the sole "
        f"promote path), found {len(deploy_blocks)}"
    )
    step = deploy_blocks[0]
    assert _is_prod_gated(
        step, text
    ), "the `wrangler deploy` step must require github.ref == 'refs/heads/main'"
    assert not _requires_non_main_ref(step), (
        "the `wrangler deploy` step must never also be reachable on the "
        "non-main (preview) condition"
    )


def test_preview_and_prod_paths_are_mutually_exclusive_by_construction() -> None:
    # Belt-and-suspenders on h3/h11: the prod D1/deploy steps require
    # ref == main, the preview D1/upload steps require ref != main, so no
    # single workflow run can ever satisfy both — encoded here so a future
    # edit that relaxes either guard to an unconditional step trips a test.
    text = _read(WORKFLOW_YML)
    blocks = _step_blocks(text)
    prod_step = _step_matching(blocks, _PROD_DEPLOY_RUN_RE)
    preview_step = _step_matching(blocks, _PREVIEW_UPLOAD_RUN_RE)
    assert _requires_main_ref(prod_step) and not _requires_non_main_ref(prod_step)
    assert _requires_non_main_ref(preview_step) and not _requires_main_ref(preview_step)
