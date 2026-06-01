#!/usr/bin/env bash
# scripts/run_all_gates.sh
#
# Single-command runner for ALL pre-deploy quality gates. Exits 0 only
# if every gate passes. Use before every `git commit`.
#
# Gates run, in order:
#   1. ruff check
#   2. pytest with coverage floor
#   3. jest (JavaScript unit tests)
#   4. local Playwright (needs bypass server — auto-managed)
#
# Not run by this script (run separately after `git push`):
#   - deploy validation (scripts/validate_deploy.py)
#   - prod Playwright smoke (npm run test:e2e:prod)
#   - Phase 6 manual browser regression for UI changes
#
# Usage:
#   bash scripts/run_all_gates.sh
#
# On Windows (git bash), the script needs node/npm on PATH. If not,
# prepend Node before invoking:
#   export PATH="/c/Program Files/nodejs:$PATH"
#   bash scripts/run_all_gates.sh
#
# This script intentionally has no "skip X" flags. Every gate that can
# reasonably run, DOES run. Skipping a gate is a conscious decision
# the human makes — they edit this file or run a gate manually —
# not a CLI convenience.

set -euo pipefail

# Resolve repo root (script may be invoked from anywhere)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# --- Formatting helpers ------------------------------------------------------

RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
BOLD=$'\033[1m'
NC=$'\033[0m'

banner() {
    printf "\n${BOLD}==== %s ====${NC}\n" "$1"
}

pass() {
    printf "${GREEN}✓${NC} %s\n" "$1"
}

fail() {
    printf "${RED}✗${NC} %s\n" "$1" >&2
}

# Run a NETWORK-BOUND gate command under a hard wall-clock cap so a
# transient registry / advisory-fetch stall fails fast instead of hanging
# the whole suite with no detection. Real incident 2026-05-31: pip-audit
# hung ~80 min on the OSV advisory fetch — its own `--timeout` is only a
# per-socket READ timeout (default 15s), NOT a bound on the total operation
# (many requests, or a trickling connection, never trip a single-socket
# timeout). GNU `timeout` exits 124 when it has to terminate the command.
# A timeout is surfaced as a gate FAILURE (re-run needed), never a silent
# pass — a network stall must not let a CVE gate slip through unverified.
# Falls back to running uncapped (with a loud warning) if `timeout` isn't
# installed, so the script stays portable.
# Usage: capped_run <seconds> <label> <cmd> [args...]
capped_run() {
    local cap="$1" label="$2"; shift 2
    local rc=0
    if command -v timeout >/dev/null 2>&1; then
        timeout "$cap" "$@" || rc=$?
        if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
            fail "${label} exceeded its ${cap}s wall-clock cap — likely a transient network stall (PyPI / OSV / npm registry). Re-run; if it persists, check connectivity. This is NOT treated as a pass."
        fi
    else
        printf "${YELLOW}!${NC} 'timeout' not on PATH — running %s WITHOUT a wall-clock cap (a network stall can hang here).\n" "$label" >&2
        "$@" || rc=$?
    fi
    return "$rc"
}

# #274 (2026-05-31): the 5 security/CVE scanners (bandit, pip-audit, npm
# audit, semgrep, gitleaks) are read-only and independent of one another, so
# run them CONCURRENTLY and join at the end instead of serially (~saves the
# sum-minus-max wall clock). bg_scan launches one in the background, capturing
# its combined output + real exit code under $SCAN_TMP. The `set +e` in the
# subshell is load-bearing: without it the parent's `set -e` would abort the
# subshell the instant the scanner exits non-zero, BEFORE we record the rc —
# and a security gate whose failure is silently dropped is worse than a slow
# one. scan_join prints the captured output in a deterministic order and turns
# any non-zero rc into a suite failure.
SCAN_TMP=""
SCAN_FAILED=0
SCAN_PIDS=()
bg_scan() {
    local key="$1"; shift
    [ -n "$SCAN_TMP" ] || SCAN_TMP="$(mktemp -d)"
    ( set +e; "$@" > "$SCAN_TMP/$key.out" 2>&1; echo $? > "$SCAN_TMP/$key.rc" ) &
    # Track ONLY the scanner PIDs. A bare `wait` would also block on the
    # long-lived dev-bypass server (started with `&` for the Playwright gate)
    # which never exits → the join would hang forever. wait on these PIDs.
    SCAN_PIDS+=("$!")
}
scan_await() {
    # Join all launched scanners. Subshells always exit 0 (set +e + echo), so
    # this never trips the parent's set -e; `|| true` is belt-and-braces.
    [ "${#SCAN_PIDS[@]}" -gt 0 ] && { wait "${SCAN_PIDS[@]}" || true; }
}
scan_join() {
    # Usage: scan_join <key> <label> <fail-line> [more-fail-lines...]
    local key="$1" label="$2"; shift 2
    banner "scanner result: $label"
    cat "$SCAN_TMP/$key.out" 2>/dev/null || true
    local rc
    rc="$(cat "$SCAN_TMP/$key.rc" 2>/dev/null || echo 1)"
    if [ "$rc" -eq 0 ]; then
        pass "$label"
    else
        local line
        for line in "$@"; do fail "$line"; done
        SCAN_FAILED=1
    fi
}

# --- Preflight: tools available ---------------------------------------------

banner "Preflight"
command -v python >/dev/null 2>&1 || { fail "python not on PATH"; exit 2; }
command -v npm >/dev/null 2>&1 || { fail "npm not on PATH (Windows: export PATH=\"/c/Program Files/nodejs:\$PATH\")"; exit 2; }
command -v curl >/dev/null 2>&1 || { fail "curl not on PATH"; exit 2; }
pass "python, npm, curl available"

# --- 1. Ruff ----------------------------------------------------------------

banner "1. Ruff"
if python -m ruff check .; then
    pass "ruff"
else
    fail "ruff failed — FIX LINT before re-running"
    exit 1
fi

# --- 2. Pytest --------------------------------------------------------------

banner "2. Pytest"
# #274 (2026-05-31): parallelize with pytest-xdist. Every test gets its own
# in-memory SQLite DB (function-scoped `app` fixture, sqlite:///:memory:),
# so there is ZERO shared state between tests — xdist is safe, and pytest-cov
# correctly combines per-worker coverage (same --cov-fail-under=80 floor).
# Measured 214s → 43s (~5x) on a 32-core box. Falls back to serial if
# pytest-xdist isn't installed so the gate stays portable. Override the
# worker count with PYTEST_WORKERS (e.g. PYTEST_WORKERS=0 to debug serially).
PYTEST_WORKERS="${PYTEST_WORKERS:-auto}"
PYTEST_PARALLEL=""
if python -c "import xdist" >/dev/null 2>&1; then
    PYTEST_PARALLEL="-n ${PYTEST_WORKERS}"
else
    printf "${YELLOW}!${NC} pytest-xdist not installed — running pytest serially (slower). Install: pip install pytest-xdist\n" >&2
fi
if python -m pytest ${PYTEST_PARALLEL} --cov -q; then
    pass "pytest (coverage floor enforced)"
else
    fail "pytest failed or coverage below floor"
    exit 1
fi

# --- 3. Jest ----------------------------------------------------------------

banner "3. Jest"
if npm test --silent 2>&1 | tail -10; then
    pass "jest"
else
    fail "jest failed"
    exit 1
fi

# --- 4. Local Playwright (auto-manages bypass server) ----------------------

banner "4. Local Playwright"

# If a bypass server is already running, reuse it (don't mess with the
# user's dev environment). Otherwise start one for the duration of the
# Playwright run and tear it down.
BYPASS_STARTED_BY_US=0
BYPASS_PID=""

if curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://localhost:5111/healthz 2>/dev/null | grep -qE "^[23456][0-9][0-9]$"; then
    pass "bypass server already running on :5111, reusing"
else
    printf "${YELLOW}…${NC} no bypass server on :5111, starting one\n"
    if [ ! -f .env.dev-bypass.example ]; then
        fail ".env.dev-bypass.example missing — cannot auto-start bypass"
        exit 1
    fi
    cp .env.dev-bypass.example .env.dev-bypass
    python scripts/run_dev_bypass.py > /tmp/run_all_gates_bypass.log 2>&1 &
    BYPASS_PID=$!
    BYPASS_STARTED_BY_US=1

    # Clean up the bypass server + .env.dev-bypass on any exit path.
    # Using a function so both trap and normal exit paths share it.
    cleanup_bypass() {
        if [ "$BYPASS_STARTED_BY_US" -eq 1 ]; then
            if [ -n "$BYPASS_PID" ] && kill -0 "$BYPASS_PID" 2>/dev/null; then
                kill "$BYPASS_PID" 2>/dev/null || true
            fi
            # Also kill any process still holding port 5111 (Flask
            # reloader forks a child that doesn't die with the parent).
            if command -v lsof >/dev/null 2>&1; then
                PORT_PID=$(lsof -ti:5111 2>/dev/null || true)
                [ -n "$PORT_PID" ] && kill -9 $PORT_PID 2>/dev/null || true
            fi
            rm -f .env.dev-bypass
        fi
    }
    trap cleanup_bypass EXIT INT TERM

    # Wait up to 60s for bypass to accept requests. First-time imports
    # (SQLAlchemy + psycopg + flask-dance + apscheduler on Windows) can
    # take 15-25s cold, plus the import_migrations scan runs on boot.
    # 60s gives plenty of headroom on slow machines.
    for i in $(seq 1 60); do
        if curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://localhost:5111/healthz 2>/dev/null | grep -qE "^[23456][0-9][0-9]$"; then
            pass "bypass server ready after ${i}s"
            break
        fi
        sleep 1
        if [ "$i" -eq 60 ]; then
            fail "bypass server did not come up in 60s — check /tmp/run_all_gates_bypass.log"
            cat /tmp/run_all_gates_bypass.log >&2 || true
            exit 1
        fi
    done
fi

# #274 (2026-05-31): run all three local projects in ONE `playwright test`
# invocation (test:e2e:local) instead of three sequential `npm run` calls.
# Each separate invocation paid its own Node + Playwright + browser
# cold-start (~3-5s each); one process pays it once and Playwright schedules
# all three projects (workers:1 keeps them serial = same DB-safety as
# before). Covers:
#   - chromium        — desktop 1280×800, ?nosw=1 (tests/e2e)
#   - chromium-sw     — SW-active path (tests/e2e-sw) — PR39 audit E2: the
#                       entire service-worker code path was otherwise only
#                       smoked on prod
#   - chromium-mobile — 375×812 re-run (#141) MINUS @noviewport-tagged
#                       viewport-independent groups (#274)
if npm run test:e2e:local; then
    pass "local Playwright (chromium + sw + mobile, one run)"
else
    fail "local Playwright failed"
    exit 1
fi

# --- 5. Bandit (Python security linter) -------------------------------------

banner "5. Bandit (security lint)"
# Default severity = LOW, default confidence = LOW. We previously gated
# at HIGH/HIGH only, but the 2026-04-18 audit pass cleared every LOW/LOW
# finding (some fixed in code, the rest documented as skips in
# .bandit.yml with rationale). Locking the gate at LOW/LOW catches any
# regression early — see backlog #20 + ADR-024.
# #274: launch in background (joined after the fast sync checks below).
bg_scan bandit python -m bandit -r . -c .bandit.yml --quiet

# --- 6. pip-audit (Python CVE check) ----------------------------------------

banner "6. pip-audit (dependency CVEs)"
# Ignored vulnerabilities (database false-positives only — never silent
# real risk; document each here with the OSV ID + reason):
#
#   PYSEC-2026-89 (markdown CVE-2025-69534 / GHSA-5wmx-573v-2qwq): the
#   advisory's own description says "fixed in version 3.8.1" and we
#   run markdown 3.10.2 (well past the fix). OSV still flags 3.8.1+
#   for this ID — false positive. Re-evaluate whenever the OSV record's
#   `fix_versions` field gets populated or the upstream entry is
#   amended. Added 2026-05-21 alongside #205.
#
# #163 (2026-05-22): audit requirements-dev.txt, not requirements.txt —
# it `-r`-includes requirements.txt so this covers BOTH the runtime and
# the dev/test deps (pytest, ruff, …) in one pass. A bare `pip-audit`
# would instead sweep in unrelated co-installed tooling (MCP servers,
# etc.) that this repo doesn't ship.
# Wall-clock cap (override with PIP_AUDIT_TIMEOUT=<seconds>). pip-audit is
# network-bound — see capped_run for the 2026-05-31 hang incident.
PIP_AUDIT_CAP="${PIP_AUDIT_TIMEOUT:-300}"
# #274: launch in background; capped_run still enforces the wall-clock cap
# (its 124-timeout hint is captured in the scanner's output + joined below).
bg_scan pipaudit capped_run "$PIP_AUDIT_CAP" "pip-audit" \
        python -m pip_audit -r requirements-dev.txt --ignore-vuln PYSEC-2026-89

# --- 7. npm audit (Node CVE check) ------------------------------------------

banner "7. npm audit (dependency CVEs)"
# --audit-level=high means low/medium are reported but don't fail the
# gate. High and critical do.
# Wall-clock cap (override with NPM_AUDIT_TIMEOUT=<seconds>). npm audit is
# network-bound (hits the npm registry advisory endpoint).
NPM_AUDIT_CAP="${NPM_AUDIT_TIMEOUT:-180}"
# #274: launch in background (joined below).
bg_scan npmaudit capped_run "$NPM_AUDIT_CAP" "npm audit" npm audit --audit-level=high

# --- 8. Docs sync check (env vars in code <-> README) -----------------------

banner "8. Docs sync check"
if python scripts/docs_sync_check.py; then
    pass "docs sync"
else
    fail "docs sync check failed"
    exit 1
fi

# --- 8b. ARCHITECTURE sync check (scheduler jobs + routes + API endpoints) --
# Added 2026-04-21 after the third ARCHITECTURE.md drift of the session.
# Mechanical greppable check; if you add a new route / endpoint / cron
# job, add its literal name to ARCHITECTURE.md in the same commit.

banner "8b. ARCHITECTURE sync check"
if python scripts/arch_sync_check.py; then
    pass "arch sync"
else
    fail "ARCHITECTURE.md drift — see output above"
    exit 1
fi

# --- 8c. BACKLOG ✅ vs prod-smoke pairing (PR39 audit E5) -------------------
banner "8c. BACKLOG ✅ vs prod-smoke pairing"
# Heuristic: warn if a BACKLOG row was flipped to ✅ DONE/FIXED in this
# diff but no NEW prod-smoke assertion was added that mentions any of the
# flipped row's keywords. Exits 0 even on warnings — false-positive risk
# on heuristic, so it's a soft gate. The warning text is loud enough
# that a reviewer sees it.
python scripts/check_backlog_smoke_pairing.py || true
pass "backlog ✅ ↔ prod-smoke pairing (heuristic)"

# --- 8d. No-string-match-only prod tests (PR50 anti-pattern #3) -------------
banner "8d. No-string-match-only prod tests"
# Heuristic: warn if a NEW prod-smoke test ONLY string-matches against
# /static/*.js source without any behavioral assertion. Per CLAUDE.md
# anti-pattern #3, those tests pass against a syntactically-valid but
# semantically-broken implementation. Real coverage = a Jest test on
# the extracted helper module. Exits 0 (heuristic, false-positive risk);
# the warning text is loud enough that a reviewer notices.
python scripts/check_no_string_match_only_tests.py || true
pass "no-string-match-only prod tests (heuristic)"

# --- 9. Semgrep (security pattern scanner) ----------------------------------

banner "9. Semgrep (security patterns)"
# Find the semgrep executable. `pip install semgrep` doesn't always
# put it on PATH — on Windows + Python 3.14 it lands in
# %LOCALAPPDATA%\Python\pythoncore-3.14-64\Scripts\semgrep.exe; on a
# Homebrew Mac it's at /opt/homebrew/bin/semgrep (Apple silicon) or
# /usr/local/bin/semgrep (Intel). Fall back to known locations before
# giving up. Order: PATH first (cheapest), then OS-specific paths.
SEMGREP_BIN=""
if command -v semgrep >/dev/null 2>&1; then
    SEMGREP_BIN="semgrep"
elif [ -x "/c/Users/${USERNAME}/AppData/Local/Python/pythoncore-3.14-64/Scripts/semgrep.exe" ]; then
    SEMGREP_BIN="/c/Users/${USERNAME}/AppData/Local/Python/pythoncore-3.14-64/Scripts/semgrep.exe"
elif [ -x "/c/Users/${USER}/AppData/Local/Python/pythoncore-3.14-64/Scripts/semgrep.exe" ]; then
    SEMGREP_BIN="/c/Users/${USER}/AppData/Local/Python/pythoncore-3.14-64/Scripts/semgrep.exe"
elif [ -x "/opt/homebrew/bin/semgrep" ]; then
    SEMGREP_BIN="/opt/homebrew/bin/semgrep"               # Apple silicon Homebrew
elif [ -x "/usr/local/bin/semgrep" ]; then
    SEMGREP_BIN="/usr/local/bin/semgrep"                  # Intel Homebrew / pipx default
elif [ -x "$HOME/.local/bin/semgrep" ]; then
    SEMGREP_BIN="$HOME/.local/bin/semgrep"                # Linux/Mac pip --user
fi

if [ -z "$SEMGREP_BIN" ]; then
    fail "semgrep not found. Install with one of:"
    fail "  Windows: pip install semgrep   (adds it to %LOCALAPPDATA%\\Python\\...\\Scripts)"
    fail "  Mac:     brew install semgrep  (or: pipx install semgrep)"
    fail "  Linux:   pipx install semgrep  (or: pip install --user semgrep)"
    exit 1
fi

# --error makes findings exit non-zero. p/python = standard Python rule
# pack; p/security-audit = OWASP-aligned cross-language audit pack.
# --metrics=off opts out of telemetry.
# #274: launch in background (joined below).
bg_scan semgrep "$SEMGREP_BIN" scan --config=p/python --config=p/security-audit \
        --error --quiet --metrics=off \
        --exclude=.venv --exclude=.venv-mac \
        --exclude=node_modules --exclude=.claude --exclude=tests \
        --exclude=migrations --exclude=docs

# --- 10. gitleaks (secrets scanner) -----------------------------------------

banner "10. gitleaks (secrets scanner)"
# gitleaks is a single-binary tool (not pip-installable). On first run,
# auto-download into ./tools/ if missing — single ~22 MB binary, signed
# by the official GitHub release.
GITLEAKS_BIN=""
if command -v gitleaks >/dev/null 2>&1; then
    GITLEAKS_BIN="gitleaks"
elif [ -x "./tools/gitleaks.exe" ]; then
    GITLEAKS_BIN="./tools/gitleaks.exe"
elif [ -x "./tools/gitleaks" ]; then
    GITLEAKS_BIN="./tools/gitleaks"
fi

if [ -z "$GITLEAKS_BIN" ]; then
    fail "gitleaks not installed. Auto-install with:"
    fail "  bash scripts/install_dev_tools.sh"
    fail "Or download manually from https://github.com/gitleaks/gitleaks/releases"
    fail "and place the binary at ./tools/gitleaks (or ./tools/gitleaks.exe on Windows)"
    exit 1
fi

# --no-git scans the working tree (vs. git history); --redact ensures
# any incidental match is shown without the actual secret.
# #274: launch in background (joined below).
bg_scan gitleaks "$GITLEAKS_BIN" detect --source . --no-banner --redact --no-git \
        --config .gitleaks.toml --exit-code 1

# --- 5–10. Join the parallel security scanners (#274) -----------------------
# All 5 read-only scanners were launched with bg_scan above and ran
# concurrently with each other AND with the fast docs/arch/heuristic checks
# (gates 8–8d). Join them now: wait ONLY on the scanner PIDs (never the
# bypass server), print each result in a fixed order, and fail the suite on
# ANY non-zero rc. A scanner whose failure is dropped silently would be worse
# than a slow gate — scan_join enforces every rc.
banner "5–10. Joining parallel security scanners"
scan_await
scan_join bandit "bandit" \
    "bandit found a security issue (LOW/LOW threshold). Review the report above." \
    "  If it's a true positive, fix it. If it's a documented exception, add a" \
    "  per-line '# nosec BXXX  # reason' or update .bandit.yml."
scan_join pipaudit "pip-audit" \
    "pip-audit gate failed — a known vulnerability (bump the affected package in requirements.txt / requirements-dev.txt) OR a timeout (see hint above)."
scan_join npmaudit "npm audit" \
    "npm audit gate failed — a HIGH/CRITICAL vulnerability (bump the affected package in package.json) OR a timeout (see hint above)."
scan_join semgrep "semgrep" \
    "semgrep found a security issue — review the report above."
scan_join gitleaks "gitleaks" \
    "gitleaks found a potential secret — review the report above." \
    "  If it's a false positive, add a path/regex allowlist entry to .gitleaks.toml"
rm -rf "$SCAN_TMP"
[ "$SCAN_FAILED" -eq 0 ] || exit 1

# --- 11. No embedded credentials in git remote URLs --------------------------

banner "11. No embedded credentials in git remote URLs"
# gitleaks scans tracked source files but does NOT scan `.git/config` (it's
# local-only state, not in the working tree). So a PAT embedded in a remote
# URL — e.g. `https://shigsdev:github_pat_…@github.com/...` — slips past
# every other gate while sitting in plaintext on disk + getting echoed by
# any `git remote -v` / `git config -l` invocation. Real incident
# 2026-05-24: a PAT was discovered in this repo's origin URL after living
# there an unknown duration; rotating the token + re-adding the remote
# without embedded creds fixed it. This gate prevents recurrence — any
# `remote.<name>.url = https://user[:token]@…` form fails the gate, which
# means a stray `git remote set-url origin https://token@…` (the typical
# AI-assistant "fix Authentication failed" anti-pattern) can't slip into
# day-to-day work silently.
#
# Pass shapes:
#   git@github.com:owner/repo.git          (SSH — preferred)
#   https://github.com/owner/repo.git      (HTTPS + credential helper)
# Fail shape:
#   https://user[:token]@github.com/...
#
# Implementation: `git config --get-regexp` lists every remote.*.url; grep
# matches the `https://[anything-but-@]@` prefix. The `:****@` mask before
# printing means we NEVER echo the actual secret even on failure.
# Detect on the UNMODIFIED config output so the regex match is precise.
# Redact AFTER detection, only for safe printing — the masking-then-
# matching approach broke `https://user@…` (sed ate the `//` between
# `https:` and `user`, defeating the awk regex).
GIT_CRED_LEAK="$(
    git config --get-regexp '^remote\..*\.url$' 2>/dev/null \
        | awk '/https:\/\/[^@ ]+@/ { print }'
)"
if [ -z "$GIT_CRED_LEAK" ]; then
    pass "no embedded credentials in git remote URLs"
else
    fail "git remote URL contains embedded credentials — ROTATE the token now:"
    # Redact ONLY the password portion (between : and @) before printing,
    # so the actual secret never appears on screen. Empty `://user@` —
    # username-only, no password — passes through unredacted (it's still
    # a leak shape but there's no secret to mask).
    while IFS= read -r line; do
        masked="$(printf '%s\n' "$line" \
            | sed -E 's|://([^:/]+):[^@]*@|://\1:****@|')"
        fail "  $masked"
    done <<< "$GIT_CRED_LEAK"
    fail ""
    fail "Full rotation procedure: docs/security/git-credentials.md"
    fail "Quick fix:"
    fail "  1. Revoke the leaked token at https://github.com/settings/tokens"
    fail "  2. Re-set the remote without embedded creds:"
    fail "       git remote set-url origin git@github.com:owner/repo.git   # SSH (preferred)"
    fail "       OR"
    fail "       git remote set-url origin https://github.com/owner/repo.git"
    fail "       git config --global credential.helper manager             # one-time"
    fail "  3. Audit shell history / OneDrive versions / screenshots for other copies"
    exit 1
fi

# --- Summary ----------------------------------------------------------------

banner "ALL GATES GREEN"
printf "${GREEN}${BOLD}Ready to commit.${NC}\n"
printf "\nNext steps (not automated — human judgment required):\n"
printf "  • Phase 6 manual regression via Claude Preview if this change\n"
printf "    touches any template, CSS, or new HTML route\n"
printf "  • After push: python scripts/validate_deploy.py [--auth-check]\n"
printf "  • After deploy GREEN: npm run test:e2e:prod\n"
