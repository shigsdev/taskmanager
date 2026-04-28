"""PR50: warn when a NEW prod-smoke test only string-matches fetched JS
source without any behavioral assertion.

The string-match pattern looks like:

    test("description", async ({ page }) => {
        const r = await page.request.get("/static/foo.js");
        const text = await r.text();
        expect(text).toContain('some literal');
        expect(text).not.toContain('other literal');
    });

This passes if the literal characters appear in the bundled source —
even when the actual logic is broken. Shipped bug PR47 → PR49 was
gated only by a test like this.

Rule (per CLAUDE.md anti-pattern #3): for non-trivial branches,
extract the logic into a `static/<name>_helpers.js` dual-export
module and Jest-test the actual function. The prod-smoke string
match is OK as belt-and-braces alongside a real Jest test, but it
must not be the ONLY assertion class in a test.

Heuristic detection (this script):
  - Diff `tests/e2e-prod/` vs. merge base
  - For each NEW `test(...)` block in the diff:
    * Does it call `page.request.get("/static/*.js")` AND
    * Does it ONLY do `expect(text).toContain(...)` /
      `expect(text).not.toContain(...)` assertions
      (no `.toBeVisible()`, `.click()`, `.evaluate()`, `.toBe()`,
      `.toEqual()`, `.toMatch()`, `.toHaveCount()`, etc.)
  - WARN if so. Exits 0 (heuristic, false-positive risk) but the
    output is loud enough that a reviewer notices.

Manually:
    python scripts/check_no_string_match_only_tests.py [--base origin/main]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False,
        )
        return out.stdout
    except FileNotFoundError:
        return ""


def _diff(base: str, path: str) -> str:
    return _git("diff", f"{base}...HEAD", "--unified=0", "--", path)


# Match a NEW test block opener, e.g.:
#   +    test("description", async ({ page }) => {
_TEST_OPEN_RE = re.compile(r'^\+\s*test\(\s*"([^"]+)"', re.MULTILINE)
# Lines that fetch a /static/*.js source file for inspection
_FETCH_STATIC_JS_RE = re.compile(
    r'^\+.*page\.request\.get\(["\']/static/[A-Za-z0-9_-]+\.js["\']',
    re.MULTILINE,
)
# Behavioral assertion patterns — at least one must be present alongside
# the string-match if the test is to be considered substantive.
_BEHAVIORAL_RE = re.compile(
    r'\.toBeVisible|\.click|\.evaluate|\.toBe\(|\.toEqual|\.toMatch|'
    r'\.toHaveCount|\.toHaveValue|\.toHaveAttribute|\.fill|\.selectOption|'
    r'\.dispatchEvent|page\.goto|\.toBeGreaterThan|\.toBeLessThan'
)


def _extract_test_blocks(diff: str) -> list[tuple[str, str]]:
    """Return list of (test_name, body_text_added). Body is the
    concatenated text of '+' lines belonging to that test block,
    detected by indentation tracking through the diff."""
    blocks: list[tuple[str, str]] = []
    current_name: str | None = None
    current_body: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("+"):
            # End of additions — flush current block if present
            if current_name and current_body:
                blocks.append((current_name, "\n".join(current_body)))
                current_name = None
                current_body = []
            continue
        if line.startswith("+++"):
            continue
        m = _TEST_OPEN_RE.match(line)
        if m:
            if current_name and current_body:
                blocks.append((current_name, "\n".join(current_body)))
            current_name = m.group(1)
            current_body = [line]
        elif current_name is not None:
            current_body.append(line)
    if current_name and current_body:
        blocks.append((current_name, "\n".join(current_body)))
    return blocks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Git ref to diff against (default: origin/main).",
    )
    args = parser.parse_args()

    diff = _diff(args.base, "tests/e2e-prod/")
    if not diff:
        return 0

    blocks = _extract_test_blocks(diff)
    if not blocks:
        return 0

    misses: list[str] = []
    for name, body in blocks:
        # Only flag tests that fetch /static/*.js source
        if not _FETCH_STATIC_JS_RE.search(body):
            continue
        # If there's any behavioral assertion in the same block, fine
        if _BEHAVIORAL_RE.search(body):
            continue
        # Pure string-match-only — flag
        misses.append(name)

    if not misses:
        print("[no-string-match-only-tests] OK: no new prod-smoke tests "
              "are pure string-matches against /static/*.js source.")
        return 0

    print("=" * 70)
    print("[no-string-match-only-tests] WARNING: new prod-smoke tests "
          "appear to ONLY string-match /static/*.js source without any "
          "behavioral assertion:")
    for n in misses:
        print(f"  - {n}")
    print()
    print("Per CLAUDE.md anti-pattern #3: a syntactically-valid but "
          "semantically-broken version of the same code passes a pure "
          "source-text match. Extract the logic into a dual-export "
          "helper module (e.g. static/<name>_helpers.js) and Jest-test "
          "the actual function. The prod-smoke string-match is OK as "
          "belt-and-braces ALONGSIDE a real Jest test, but it must not "
          "be the only assertion class.")
    print("=" * 70)
    # Exit 0 — heuristic warning; false positives possible. Loud text
    # makes reviewer catch real misses.
    return 0


if __name__ == "__main__":
    sys.exit(main())
