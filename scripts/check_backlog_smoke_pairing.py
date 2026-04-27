"""PR39 (audit E5): warn when a BACKLOG item is flipped to ✅ DONE
without a corresponding NEW prod-smoke assertion in the same diff.

The "mark ✅ only after prod smoke" rule (CLAUDE.md backlog completion
gate) is a human process. This script is the heuristic enforcement:

  - Diff BACKLOG.md vs. the merge base.
  - For every line that flipped to "✅ DONE" or "✅ FIXED", extract
    the BACKLOG item number and a few keywords from the row text.
  - Diff tests/e2e-prod/ vs. the merge base.
  - Scan the prod-smoke diff for keyword overlap with each flipped row.
  - Warn on any flipped row with NO keyword hit in the prod-smoke diff.

It WARNS, it doesn't fail. False positives are likely (e.g. an existing
prod-smoke test already covers the feature without needing a new one).
The exit code stays 0 so the gate doesn't block legitimate work; the
warning text is loud enough that a reviewer sees it.

Invoked from run_all_gates.sh (added in this PR). Manually:
    python scripts/check_backlog_smoke_pairing.py [--base origin/main]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys


def _git(*args: str) -> str:
    """Run a git command + return stripped stdout. Empty on failure."""
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False,
        )
        return out.stdout
    except FileNotFoundError:
        return ""


def _diff(base: str, path: str) -> str:
    """Return the unified diff of `path` between base and HEAD."""
    return _git("diff", f"{base}...HEAD", "--unified=0", "--", path)


_FLIP_RE = re.compile(
    r"^\+.*\|\s*\d+\s*\|\s*\*\*([^*]+)\*\*.*\b(?:✅\s*(?:DONE|FIXED))\b",
    re.MULTILINE,
)
_ITEM_NUM_RE = re.compile(r"^\+\s*\|\s*(\d+)\s*\|", re.MULTILINE)
# Words 4+ chars that aren't pure digits or markdown noise — used as
# the keyword set for matching against prod-smoke diff text.
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}")
# Common words that appear in nearly every BACKLOG row — exclude so
# they don't generate false-positive matches.
_STOPWORDS = frozenset({
    "user", "flagged", "want", "want.", "feature", "feature.", "bug",
    "should", "could", "would", "needs", "need", "have", "this",
    "that", "with", "from", "into", "when", "while", "after", "before",
    "page", "pages", "test", "tests", "tested", "pass", "passes",
    "phase", "deploy", "green", "smoke", "data", "task", "tasks",
    "project", "projects", "goal", "goals", "calendar", "import",
    "card", "cards", "click", "clicks", "load", "loads", "loaded",
    "view", "true", "false", "none", "null", "type", "types", "list",
    "lists", "item", "items", "show", "shows", "open", "opens",
    "close", "closes", "state", "code", "logic", "file", "files",
    "render", "renders", "rendered", "label", "label.", "panel",
    "field", "fields", "input", "inputs", "value", "values", "the",
    "and", "or", "for", "but", "via", "per", "are", "is", "an",
    "fix", "done", "fixed", "ship", "shipped", "ready",
    "adds", "added", "add", "make", "made", "use", "used",
})


def _flips(diff_text: str) -> list[tuple[str, set[str]]]:
    """Extract each (item_title, keyword_set) for rows flipped to ✅."""
    flips = []
    for line in diff_text.splitlines():
        if not line.startswith("+"):
            continue
        # Skip the +++ header line
        if line.startswith("+++"):
            continue
        if "✅ DONE" not in line and "✅ FIXED" not in line:
            continue
        # Extract the **bold title** from the row — usually first **...**
        title_match = re.search(r"\*\*([^*]+)\*\*", line)
        title = title_match.group(1).strip() if title_match else ""
        # Build keyword set from the title + first sentence
        keywords = {
            w.lower() for w in _WORD_RE.findall(line)
            if w.lower() not in _STOPWORDS
        }
        flips.append((title, keywords))
    return flips


def _prod_smoke_text(base: str) -> str:
    """All NEW lines in the tests/e2e-prod/ diff."""
    diff = _diff(base, "tests/e2e-prod/")
    return "\n".join(
        line[1:].lower() for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Git ref to diff against (default: origin/main).",
    )
    args = parser.parse_args()

    backlog_diff = _diff(args.base, "BACKLOG.md")
    if not backlog_diff:
        # Nothing changed in BACKLOG.md — vacuously fine.
        return 0

    flips = _flips(backlog_diff)
    if not flips:
        return 0

    smoke_text = _prod_smoke_text(args.base)
    misses: list[str] = []
    for title, keywords in flips:
        if not keywords:
            continue
        # A "hit" = any flipped-row keyword appears in the prod-smoke diff.
        if not any(kw in smoke_text for kw in keywords):
            misses.append(title)

    if not misses:
        print("[backlog-smoke-pairing] OK: every BACKLOG ✅ flip has at "
              "least one keyword overlap with new prod-smoke lines.")
        return 0

    # Warn loudly but don't fail the gate (heuristic, false-positive risk).
    print("=" * 70)
    print("[backlog-smoke-pairing] WARNING: BACKLOG items flipped to ✅ "
          "without a matching NEW prod-smoke assertion:")
    for t in misses:
        print(f"  - {t}")
    print()
    print("Per CLAUDE.md backlog completion gate, every shipped feature "
          "should have a prod-smoke test asserting its specific behavior.")
    print("This is a HEURISTIC check — if you DID add coverage that doesn't "
          "match the keyword sniff, this is a false positive. Otherwise, "
          "add a prod test before marking ✅.")
    print("=" * 70)
    # Exit 0 — heuristic, not a hard fail.
    return 0


if __name__ == "__main__":
    sys.exit(main())
