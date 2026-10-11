"""#347: fail when a Playwright test asserts request SHAPE instead of
request SUCCESS.

Two misses during #345 passed review and every gate:

  1. A test recorded the URLs the page fetched (``page.route`` handler
     → ``route.continue()``) and asserted the recurring-previews window
     widened with the grid. It PASSED while that fetch returned 400 —
     the previews were silently absent and the test could not see it.
  2. A test named "dragging between days still works" never dragged
     anything; it clicked a cell as a proxy for the drop handler.

Both are the CLAUDE.md anti-pattern #3 family (assert outputs, not
shape), in a form ``check_no_string_match_only_tests.py`` (gate 8d)
does not look for. Two cheap heuristics, run over every
``tests/e2e*/**/*.spec.js``:

  DRAG-NO-DRAG     the test NAME says drag/drop but its body performs
                   no drag: no ``dragTo(`` / ``DragEvent`` /
                   ``mouse.down(`` / ``touchscreen.`` / ``TouchEvent`` /
                   ``dataTransfer`` / ``pointerdown``, and no call to an
                   in-file helper that does one.
  ROUTE-NO-STATUS  the body passes requests through
                   (``route.continue(`` / ``route.fallback(``) and reads
                   ``.url()``, but never checks a response: no
                   ``.status()`` / ``.ok()`` / ``toBeOK(`` /
                   ``waitForResponse(``. A ``route.fulfill`` stub is not
                   flagged — the test owns that response.

A test that legitimately trips a rule (a layout test whose name says
"drop to their own row") opts out with a comment in its body:

    // lint-347: <why this test is not a drag / not a request check>

Exit 0 clean, 1 on any hit. Hard-fail gate 8e in run_all_gates.sh.

Manually:
    python scripts/check_e2e_assertion_shape.py
"""
from __future__ import annotations

import glob
import re
import sys
from collections.abc import Iterator

SPEC_GLOB = "tests/e2e*/**/*.spec.js"

_TEST_OPEN_RE = re.compile(
    r"\btest(?:\.(?:only|skip|fixme))?\(\s*([\"'`])(.+?)\1\s*,\s*"
    r"async\s*\([^)]*\)\s*=>\s*\{",
    re.S,
)
_DRAG_NAME_RE = re.compile(
    r"\b(drag|drags|dragged|dragging|drop|drops|dropped|dropping)\b", re.I,
)
_DRAG_DONE_RE = re.compile(
    r"dragTo\(|dragAndDrop\(|DragEvent|mouse\.down\(|touchscreen\.|"
    r"TouchEvent|dataTransfer|pointerdown",
    re.I,
)
_FUNCTION_HELPER_RE = re.compile(
    r"(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*\{",
)
_ARROW_HELPER_RE = re.compile(
    r"^([ \t]*)(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
    re.M,
)
_PASS_THROUGH_RE = re.compile(r"route\.continue\(|route\.fallback\(")
_RECORDS_URL_RE = re.compile(r"\.url\(\)")
_CHECKS_STATUS_RE = re.compile(
    r"\.status\(\)|\.ok\(\)|toBeOK\(|waitForResponse\(",
)
_OPT_OUT_RE = re.compile(r"//\s*lint-347:")
_LINE_COMMENT_RE = re.compile(r"^[ \t]*//.*$", re.M)


def find_block(src: str, start: int) -> str:
    """Return src[start:] up to and including the brace that closes the
    block whose opening ``{`` sits just before ``start``."""
    i, depth = start, 1
    while depth and i < len(src):
        c = src[i]
        depth += (c == "{") - (c == "}")
        i += 1
    return src[start:i]


def iter_tests(src: str) -> Iterator[tuple[str, str, int]]:
    """Yield (test name, body, 1-based line) for every ``test(...)``."""
    for m in _TEST_OPEN_RE.finditer(src):
        line = src.count("\n", 0, m.start()) + 1
        yield m.group(2), find_block(src, m.end()), line


def performs_drag(body: str) -> bool:
    """True if ``body`` does a real drag. Whole-line ``//`` comments are
    ignored, so a comment that merely mentions DataTransfer is not one."""
    return bool(_DRAG_DONE_RE.search(_LINE_COMMENT_RE.sub("", body)))


def _arrow_body(src: str, m: re.Match[str]) -> str:
    """The rest of an arrow helper's first line, plus every following
    line indented deeper than the declaration. Blank lines don't end
    it; the first line at the declaration's indent or shallower does
    (the next sibling, a comment, or a braced body's closing ``}``)."""
    indent = len(m.group(1).expandtabs())
    eol = src.find("\n", m.end())
    if eol == -1:
        return src[m.end():]
    body = [src[m.end():eol]]
    for line in src[eol + 1:].splitlines():
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return "\n".join(body)


def drag_helpers(src: str) -> set[str]:
    """Names of in-file helpers whose body performs a real drag.

    Covers ``function name(...) {...}`` and arrow helpers, braced or
    expression-bodied, e.g.
    ``const f = (a) =>\\n    page.dispatchEvent(..., new DragEvent(...))``.
    """
    names: set[str] = set()
    for m in _FUNCTION_HELPER_RE.finditer(src):
        if performs_drag(find_block(src, m.end())):
            names.add(m.group(1))
    for m in _ARROW_HELPER_RE.finditer(src):
        if performs_drag(_arrow_body(src, m)):
            names.add(m.group(2))
    return names


def check_source(src: str) -> list[tuple[str, str, int]]:
    """Return (rule, test name, line) for each test that trips a rule."""
    helpers = drag_helpers(src)
    helper_call = (
        re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(helpers)))
                   + r")\s*\(")
        if helpers else None
    )
    hits: list[tuple[str, str, int]] = []
    for name, body, line in iter_tests(src):
        if _OPT_OUT_RE.search(body):
            continue
        dragged = performs_drag(body) or (
            helper_call is not None and helper_call.search(body)
        )
        if _DRAG_NAME_RE.search(name) and not dragged:
            hits.append(("DRAG-NO-DRAG", name, line))
        if (_PASS_THROUGH_RE.search(body) and _RECORDS_URL_RE.search(body)
                and not _CHECKS_STATUS_RE.search(body)):
            hits.append(("ROUTE-NO-STATUS", name, line))
    return hits


def main(argv: list[str] | None = None) -> int:
    paths = argv if argv else sorted(glob.glob(SPEC_GLOB, recursive=True))
    misses: list[str] = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for rule, name, line in check_source(src):
            misses.append(f"  {rule:<16} {path}:{line}  {name[:90]}")

    if not misses:
        print(f"[e2e-assertion-shape] OK: {len(paths)} spec files, no "
              "drag-named test without a drag, no pass-through route "
              "without a response check.")
        return 0

    print("=" * 70)
    print("[e2e-assertion-shape] FAIL: tests that assert shape, not "
          "success (#347):")
    print("\n".join(misses))
    print()
    print("DRAG-NO-DRAG: the name promises a drag the body never does. "
          "Perform one (locator.dragTo, a DragEvent, mouse.down/up, "
          "touchscreen) or rename the test.")
    print("ROUTE-NO-STATUS: the test watches request URLs it lets through "
          "but never checks the response, so a 400 passes. Assert "
          "response.status() / .ok(), or use page.waitForResponse.")
    print("If the rule genuinely does not apply, add "
          "'// lint-347: <reason>' inside the test body.")
    print("=" * 70)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
