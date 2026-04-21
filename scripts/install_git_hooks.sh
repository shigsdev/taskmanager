#!/usr/bin/env bash
# scripts/install_git_hooks.sh
#
# Points `git config core.hooksPath` at the repo's `.githooks/` directory
# so every contributor gets the same pre-commit checks without having to
# copy hook files into .git/hooks/ by hand.
#
# Currently installs:
#   - pre-commit : runs gitleaks against staged content
#
# Idempotent: re-running just re-sets the config and verifies hooks are
# executable. Safe to call multiple times.
#
# Uninstall:
#   git config --unset core.hooksPath
#
# Usage:
#   bash scripts/install_git_hooks.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

if [ ! -d .githooks ]; then
    echo "ERROR: .githooks/ directory missing — are you in the repo root?" >&2
    exit 1
fi

# chmod +x on every hook (git bash on Windows sometimes strips the bit
# on fresh clones; this normalizes it).
for hook in .githooks/*; do
    [ -f "$hook" ] || continue
    chmod +x "$hook"
done

# Wire it up. `core.hooksPath` is a first-class git setting (since 2.9)
# so no symlinks or copy tricks needed.
git config core.hooksPath .githooks

echo "✓ git hooks installed. core.hooksPath = $(git config core.hooksPath)"
echo
echo "Active hooks:"
ls -1 .githooks/ | sed 's/^/  - /'
echo
echo "To uninstall: git config --unset core.hooksPath"
