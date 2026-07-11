#!/usr/bin/env bash
# run.sh — the learn-cli pre-launch E2E gate, one entrypoint.
#
#   bash tools/launch-gate/run.sh
#
# Orchestrates every launch-bar check and audience test against the REAL
# production topology, LOCALLY (the worker + its /learn zone-mount proxy in front
# of the built static site — no cloud, no wrangler), then prints a final
# PASS/FAIL table. This gate runs PRE-LAUNCH, by hand — it is deliberately NOT
# wired into per-PR CI (see README.md). Exits non-zero if any check fails.
#
# Live mode: `LIVE_ORIGIN=https://agentculture.org bash tools/launch-gate/run.sh`
# re-runs the signed-out walk against the deployed site (see README.md "Live
# mode"); the local-artifact checks (launch bar, static-auth, audiences) still
# validate the very build that was deployed.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUT_DIR="$SCRIPT_DIR/.out"
RESULTS="$OUT_DIR/results.ndjson"
mkdir -p "$OUT_DIR"
: > "$RESULTS"
export LAUNCH_GATE_RESULTS="$RESULTS"

# The sibling subject CLIs (their built venvs). Override with LAUNCH_GATE_SUBJECT_BIN.
SUBJECT_BINS="${LAUNCH_GATE_SUBJECT_BIN:-/home/spark/git/french-cli/.venv/bin:/home/spark/git/spanish-cli/.venv/bin:/home/spark/git/culture-guide/.venv/bin}"
export PATH="$SUBJECT_BINS:$PATH"
export LAUNCH_GATE_SUBJECT_BIN="$SUBJECT_BINS"

DIST_DEPLOY="$REPO_ROOT/site-astro/dist-deploy"
export LAUNCH_GATE_DIST_DEPLOY="$DIST_DEPLOY"

emit() { # audience check status detail  (detail must be quote/backslash-free)
  printf '{"audience":"%s","check":"%s","status":"%s","detail":"%s"}\n' \
    "$1" "$2" "$3" "$4" >> "$RESULTS"
}

step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

# --- 1. preflight: the subject CLIs must be present and respond ---------------
step "preflight: subject CLIs on PATH"
for cmd in french spanish culture-guide; do
  if ver="$($cmd --version 2>/dev/null)" && [ -n "$ver" ]; then
    echo "  [PASS ] $cmd responds ($ver)"
    emit preflight "$cmd CLI responds to --version" PASS "$ver"
  else
    echo "  [FAIL ] $cmd not on PATH or unresponsive"
    emit preflight "$cmd CLI responds to --version" FAIL "not found on PATH; check $SUBJECT_BINS"
  fi
done

# --- 2. build the site + prepare the deploy tree (mirror deploy-site.yml) -----
step "build site-astro + prepare deploy directory"
BUILD_OK=1
(
  cd "$REPO_ROOT/site-astro" || exit 1
  if [ ! -d node_modules ]; then npm ci >/dev/null 2>&1 || exit 1; fi
  npm run build >/dev/null 2>&1
) || BUILD_OK=0
if [ "$BUILD_OK" = 1 ]; then
  rm -rf "$DIST_DEPLOY"
  mkdir -p "$DIST_DEPLOY/learn"
  cp -r "$REPO_ROOT/site-astro/dist/." "$DIST_DEPLOY/learn/"
  printf '/    /learn/    302\n' > "$DIST_DEPLOY/_redirects"
  echo "  [PASS ] site built and wrapped under dist-deploy/learn/"
  emit static "site-astro builds + deploy tree prepared" PASS "dist wrapped under /learn/"
else
  echo "  [FAIL ] site build failed"
  emit static "site-astro builds + deploy tree prepared" FAIL "npm ci/build failed"
fi

# --- 3. zero-API static check (site-astro npm run check) ----------------------
step "zero-API static check (npm run check)"
if [ "$BUILD_OK" = 1 ] && (cd "$REPO_ROOT/site-astro" && npm run check >/dev/null 2>&1); then
  echo "  [PASS ] static-auth + export-pages checks green"
  emit static "zero-API static check (npm run check)" PASS "static-auth + export-pages green"
else
  echo "  [FAIL ] npm run check failed (or build missing)"
  emit static "zero-API static check (npm run check)" FAIL "see: cd site-astro && npm run check"
fi

# --- 4. the measurable launch bar (subject doctors, content counts, css) ------
step "launch bar (subject doctors, content counts, css tokens)"
uv --project "$REPO_ROOT" run python "$SCRIPT_DIR/launch_bar.py" || true

# --- 5. audience tests: CLI (golden --json) + agent (MCP harness) -------------
step "audience tests: CLI golden --json + MCP harness (pytest)"
RUN_LAUNCH_GATE=1 uv --project "$REPO_ROOT" run pytest "$REPO_ROOT/tests/e2e" \
  -p no:randomly -q >/dev/null 2>&1
echo "  (per-test results recorded to the gate table)"

# --- 6. web audience: the scripted success walk (Playwright) ------------------
step "web audience: scripted success walk (phone + desktop)"
(
  cd "$SCRIPT_DIR"
  if [ ! -d node_modules ]; then npm install >/dev/null 2>&1 || true; fi
  # Best-effort browser fetch; walk.mjs degrades to a fetch/DOM fallback (SKIPs
  # the browser-level checks) if chromium can't launch.
  npx --yes playwright install chromium >/dev/null 2>&1 || true
  node walk.mjs
) || true

# --- 7. render the final PASS/FAIL table + gate verdict -----------------------
uv --project "$REPO_ROOT" run python "$SCRIPT_DIR/report.py" "$RESULTS"
exit $?
