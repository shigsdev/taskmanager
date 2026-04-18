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
if python -m pytest --cov -q; then
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

if npm run test:e2e; then
    pass "local Playwright"
else
    fail "local Playwright failed"
    exit 1
fi

# --- 5. Bandit (Python security linter) -------------------------------------

banner "5. Bandit (security lint)"
# -ll = HIGH severity threshold; -ii = HIGH confidence threshold.
# Anything below those prints to stderr but doesn't fail the gate
# (keeps false-positive noise out of the must-fix bucket).
if python -m bandit -r . -c .bandit.yml -ll -ii --quiet; then
    pass "bandit"
else
    fail "bandit found a HIGH severity / HIGH confidence security issue"
    exit 1
fi

# --- 6. pip-audit (Python CVE check) ----------------------------------------

banner "6. pip-audit (dependency CVEs)"
if python -m pip_audit -r requirements.txt; then
    pass "pip-audit"
else
    fail "pip-audit found a known vulnerability — bump the affected package in requirements.txt"
    exit 1
fi

# --- 7. npm audit (Node CVE check) ------------------------------------------

banner "7. npm audit (dependency CVEs)"
# --audit-level=high means low/medium are reported but don't fail the
# gate. High and critical do.
if npm audit --audit-level=high; then
    pass "npm audit"
else
    fail "npm audit found a HIGH/CRITICAL vulnerability — bump the affected package in package.json"
    exit 1
fi

# --- 8. Docs sync check (env vars in code <-> README) -----------------------

banner "8. Docs sync check"
if python scripts/docs_sync_check.py; then
    pass "docs sync"
else
    fail "docs sync check failed"
    exit 1
fi

# --- 9. Semgrep (security pattern scanner) — DEFERRED ----------------------
#
# Semgrep was intended here but was deferred because the pip-installed
# semgrep CLI binary doesn't reliably end up on PATH for Python 3.14 on
# Windows. Bandit (gate 5) already covers ~70% of the same ground for
# Python security antipatterns — semgrep adds extra Flask-specific
# rules and OWASP coverage but isn't a replacement.
#
# To re-enable on a machine where `semgrep` is on PATH (mac/linux,
# or Windows after fixing PATH):
#
#   banner "9. Semgrep (security patterns)"
#   if semgrep scan --config=p/python --config=p/security-audit \
#           --error --quiet --exclude=.venv --exclude=.venv-mac \
#           --exclude=node_modules --exclude=.claude --exclude=tests \
#           --exclude=migrations --metrics=off; then
#       pass "semgrep"
#   else
#       fail "semgrep found a security issue — review the report above"
#       exit 1
#   fi
#
# Tracked as backlog item: "Semgrep gate (cross-platform fix)".

# --- Summary ----------------------------------------------------------------

banner "ALL GATES GREEN"
printf "${GREEN}${BOLD}Ready to commit.${NC}\n"
printf "\nNext steps (not automated — human judgment required):\n"
printf "  • Phase 6 manual regression via Claude Preview if this change\n"
printf "    touches any template, CSS, or new HTML route\n"
printf "  • After push: python scripts/validate_deploy.py [--auth-check]\n"
printf "  • After deploy GREEN: npm run test:e2e:prod\n"
