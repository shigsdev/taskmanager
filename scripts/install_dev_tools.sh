#!/usr/bin/env bash
# scripts/install_dev_tools.sh
#
# One-time installer for dev binaries that aren't pip-installable.
# Currently:
#   - gitleaks (secrets scanner)
#
# Idempotent: re-running just verifies binaries are present and prints
# their versions. Safe to call multiple times.
#
# Binaries land in ./tools/, which is gitignored. run_all_gates.sh
# checks PATH first then ./tools/ — either location works.
#
# Usage:
#   bash scripts/install_dev_tools.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

mkdir -p tools

# --- gitleaks ---------------------------------------------------------------

GITLEAKS_VERSION="8.30.1"
GITLEAKS_BASE="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}"

case "$(uname -s)" in
    Darwin)  GL_ASSET="gitleaks_${GITLEAKS_VERSION}_darwin_x64.tar.gz"; GL_BIN="gitleaks" ;;
    Linux)   GL_ASSET="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"; GL_BIN="gitleaks" ;;
    MINGW*|MSYS*|CYGWIN*)
             GL_ASSET="gitleaks_${GITLEAKS_VERSION}_windows_x64.zip"; GL_BIN="gitleaks.exe" ;;
    *)       echo "ERROR: unknown OS $(uname -s); install gitleaks manually." >&2; exit 1 ;;
esac

if [ -x "tools/${GL_BIN}" ]; then
    INSTALLED_VERSION=$("./tools/${GL_BIN}" version 2>&1 | head -1 || echo unknown)
    echo "✓ gitleaks already installed: ${INSTALLED_VERSION}"
else
    echo "⏳ Downloading gitleaks ${GITLEAKS_VERSION}..."
    cd tools
    if [[ "$GL_ASSET" == *.zip ]]; then
        curl -sL -o gitleaks.zip "${GITLEAKS_BASE}/${GL_ASSET}"
        unzip -o gitleaks.zip "${GL_BIN}" -d ./ >/dev/null
        rm -f gitleaks.zip
    else
        curl -sL "${GITLEAKS_BASE}/${GL_ASSET}" | tar -xz "${GL_BIN}"
    fi
    chmod +x "${GL_BIN}"
    cd ..
    echo "✓ gitleaks installed: $(./tools/${GL_BIN} version | head -1)"
fi

echo
echo "Dev tools ready. Re-run \`bash scripts/run_all_gates.sh\` to use them."
