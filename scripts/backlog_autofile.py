"""#242 (2026-05-27): auto-file recurring-audit findings into BACKLOG.md.

Without this module, the 4 recurring audits (#226 bug-pattern,
#227 security, #228 tech-debt, #229 coverage) email findings + exit 1
but BACKLOG.md updates are manual. Same findings get emailed week
after week with no durable artifact telling the operator "yes I've
seen this, here's the plan, I'm working on it." This closes that
loop: each audit calls `upsert_findings()` after computing its
findings list; new findings get a row in BACKLOG.md, repeat findings
just refresh `last-seen`, and findings that have stopped appearing
get auto-flagged ``🟢 auto-detected resolved`` for human follow-up.

## Schema

The `## Auto-filed by recurring audits` section in `BACKLOG.md`
holds one row per UNIQUE finding. Identity is captured in an HTML
comment marker immediately above each row:

    <!-- audit-row: <audit_name>/<check_id>/<dedup_key> -->
    | <key> | <finding text> | <first-seen> | <last-seen> | <notes> |

`<audit_name>` is the short name of the audit (``bug-pattern``,
``security``, ``tech-debt``, ``coverage``). `<check_id>` matches the
``Finding.check_id`` field from the audit's dataclass. `<dedup_key>`
is the natural-key dedup tail — for path-keyed findings it's the
relative path; for path-less findings (e.g. an overall-coverage-drift
finding) it's a slugified version of the finding text.

## Operator-edit safety

Operators can edit the `Notes / Status` cell freely (e.g. adding "in
flight on feature/foo" or "wontfix — incompatible with X"). The
script's upsert preserves that cell verbatim on re-runs — only the
`Last seen` cell rewrites mechanically. The row is only removed
when an operator deletes it by hand AND its dedup key stops being
flagged (the auto-detected-resolved flag is added in-place, not as
a row deletion).

## CLI usage

Used by the audit scripts via:

    from scripts import backlog_autofile
    backlog_autofile.upsert_findings("tech-debt", findings)

And as a standalone CLI for ad-hoc seeding / testing:

    python scripts/backlog_autofile.py \\
        --audit tech-debt \\
        --check-id dependency-drift \\
        --path cryptography \\
        --detail "pip dep stuck at 46.0.7 (2 majors behind latest 48.0.0)"

## CI permission model

The GitHub Actions workflows that call `--autofile` need `permissions:
contents: write` so they can commit the BACKLOG.md update back to
main. Each workflow's commit-back step uses `[skip ci]` in the
message to avoid re-triggering on push (the recurring audits use
cron triggers anyway, but belt-and-braces).
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKLOG_PATH = PROJECT_ROOT / "BACKLOG.md"

SECTION_START = "## Auto-filed by recurring audits"
SECTION_END_MARKER = "<!-- autofile-section-end -->"
ROW_MARKER_PREFIX = "<!-- audit-row: "
ROW_MARKER_SUFFIX = " -->"
RESOLVED_PREFIX = "🟢 auto-detected resolved"

# Slugify regex — replace anything that isn't alphanumeric/hyphen/underscore
# with a single hyphen. Used for path-less findings where the dedup tail
# is derived from the finding text.
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class AuditRow:
    """One row in the auto-filed section.

    Attributes:
        marker_key: dedup identity, e.g. ``tech-debt/dependency-drift/cryptography``
        finding_text: human-readable detail string (the audit's
            ``Finding.detail`` plus any path prefix)
        first_seen: ISO date string (YYYY-MM-DD) — set once at insertion
        last_seen: ISO date string — refreshed every run that re-flags
        notes: operator-curated status / context. Preserved across
            re-renders. Empty string for newly-inserted rows.
    """

    marker_key: str
    finding_text: str
    first_seen: str
    last_seen: str
    notes: str


def _slug(s: str) -> str:
    """Normalise a free-text string to a safe dedup key tail.

    - Collapses non-alphanumeric runs to single hyphen
    - Strips leading/trailing hyphens
    - Lowercases (so case typos don't fork the key)
    """
    return _SLUG_RE.sub("-", s).strip("-").lower()


def make_marker_key(audit_name: str, check_id: str, dedup_tail: str) -> str:
    """Build the canonical ``audit/check_id/tail`` marker key.

    The tail is slugified so paths like ``static/style.css`` become
    ``static-style-css`` and don't trip the markdown table separator.
    """
    return f"{audit_name}/{check_id}/{_slug(dedup_tail)}"


def _today_iso() -> str:
    """Return today's date in ISO8601 (YYYY-MM-DD) form."""
    return datetime.date.today().isoformat()


# --- File I/O --------------------------------------------------------------


def _read_backlog() -> str:
    """Read the current BACKLOG.md text. Raises if missing — we don't
    auto-create the file because that would mask a misconfigured
    workflow checking out the wrong path.
    """
    if not BACKLOG_PATH.exists():
        raise FileNotFoundError(f"BACKLOG.md not found at {BACKLOG_PATH}")
    return BACKLOG_PATH.read_text(encoding="utf-8")


def _write_backlog(content: str) -> None:
    """Write BACKLOG.md atomically (via a sibling tempfile + rename) so
    a crashed workflow can't leave the file in a half-written state.
    """
    tmp = BACKLOG_PATH.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(BACKLOG_PATH)


# --- Parsing ---------------------------------------------------------------


def _split_section(content: str) -> tuple[str, str, str]:
    """Split BACKLOG.md into (head, autofile_section, tail) so the
    section can be re-rendered without disturbing surrounding text.

    The autofile_section spans from the line starting with
    ``## Auto-filed by recurring audits`` up to and including the
    ``<!-- autofile-section-end -->`` marker. If either anchor is
    missing, raises a clear error (the section is created by hand
    once when this script is introduced; we never auto-create it
    because that would let a misconfigured workflow silently inject
    rows into the wrong file).
    """
    lines = content.splitlines(keepends=True)
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if line.rstrip() == SECTION_START and start_idx is None:
            start_idx = i
        elif (
            SECTION_END_MARKER in line and start_idx is not None
            and end_idx is None
        ):
            end_idx = i
            break
    if start_idx is None or end_idx is None:
        raise ValueError(
            "BACKLOG.md does not contain the autofile section anchors "
            f"({SECTION_START!r} … {SECTION_END_MARKER!r}). "
            "Add them by hand once; the script does NOT auto-create.",
        )
    head = "".join(lines[:start_idx])
    section = "".join(lines[start_idx : end_idx + 1])
    tail = "".join(lines[end_idx + 1 :])
    return head, section, tail


def _parse_rows(section_text: str) -> list[AuditRow]:
    """Parse the existing rows out of the autofile section.

    Each row is two lines:
        <!-- audit-row: KEY -->
        | KEY | finding text | first | last | notes |

    The section may also contain header rows / explainer comments
    which we skip. Returns rows in their on-disk order so the
    re-render preserves their visual layout.
    """
    rows: list[AuditRow] = []
    lines = section_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(ROW_MARKER_PREFIX) and line.rstrip().endswith(
            ROW_MARKER_SUFFIX,
        ):
            marker_key = (
                line.removeprefix(ROW_MARKER_PREFIX)
                .rstrip()
                .removesuffix(ROW_MARKER_SUFFIX)
                .strip()
            )
            # Next non-blank line should be the table row.
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].startswith("|"):
                cells = [c.strip() for c in lines[j].split("|")[1:-1]]
                # cells = [key, finding_text, first_seen, last_seen, notes]
                if len(cells) >= 5:
                    rows.append(AuditRow(
                        marker_key=marker_key,
                        finding_text=cells[1],
                        first_seen=cells[2],
                        last_seen=cells[3],
                        notes=cells[4],
                    ))
                    i = j + 1
                    continue
        i += 1
    return rows


def _render_section(rows: list[AuditRow]) -> str:
    """Re-render the autofile section from the parsed/updated rows.

    Preserves the explainer block at the top of the section and the
    end-marker. Rows are sorted by audit_name then marker_key for
    stable diffs.
    """
    rows_sorted = sorted(rows, key=lambda r: r.marker_key)
    body_rows = []
    for r in rows_sorted:
        body_rows.append(
            f"<!-- audit-row: {r.marker_key} -->\n"
            f"| `{r.marker_key}` | {r.finding_text} | "
            f"{r.first_seen} | {r.last_seen} | {r.notes} |\n",
        )

    return (
        f"{SECTION_START}\n"
        "\n"
        "<!-- This section is managed by `scripts/backlog_autofile.py`. "
        "Each row\n"
        "is keyed by an HTML-comment marker of the form\n"
        "`<!-- audit-row: <audit_name>/<check_id>/<dedup_key> -->`. The four\n"
        "recurring audits (#226 bug-pattern, #227 security, #228 tech-debt,\n"
        "#229 coverage) call `upsert_finding()` on every run; new findings "
        "get\n"
        "a row, repeat findings only refresh `last-seen`. When an audit run\n"
        "clean-passes a previously-flagged key, the next "
        "`upsert_findings()`\n"
        "call marks the row `🟢 auto-detected resolved YYYY-MM-DD` so an\n"
        "operator can verify + move it to Resolved. **Do not edit the "
        "markers\n"
        "or column structure by hand** — the script grep-matches them\n"
        "verbatim. Free-text edits to the `Notes / Status` cell are fine.\n"
        "The script preserves operator-added prose across re-renders. -->\n"
        "\n"
        "| Audit row | Finding | First seen | Last seen | Notes / Status |\n"
        "|---|---|---|---|---|\n"
        + "".join(body_rows)
        + f"{SECTION_END_MARKER}\n"
    )


# --- Upsert ----------------------------------------------------------------


def upsert_findings(
    audit_name: str,
    findings: list,
    today: str | None = None,
) -> dict[str, int]:
    """Reconcile a single audit run's findings with the autofile section.

    For each finding:
    - If marker not present: insert new row with first_seen=last_seen=today
    - If marker present + still active: update last_seen=today
    - If a previously-tracked key for this audit_name is NOT in findings
      AND its row notes don't already contain the resolved marker:
      append `🟢 auto-detected resolved YYYY-MM-DD` to its notes

    Returns a dict ``{"inserted": N, "updated": M, "auto_resolved": K}``.

    Args:
        audit_name: short audit identifier (``bug-pattern``,
            ``security``, ``tech-debt``, ``coverage``)
        findings: list of objects with `.check_id`, `.detail`, and
            optionally `.path` attributes (the audit Finding dataclasses
            all satisfy this shape — duck-typed for testability)
        today: ISO date string to record. Defaults to today's local
            date. Override-able for deterministic testing.
    """
    today = today or _today_iso()
    content = _read_backlog()
    head, section_text, tail = _split_section(content)
    existing_rows = _parse_rows(section_text)
    rows_by_key = {r.marker_key: r for r in existing_rows}

    inserted = 0
    updated = 0
    seen_keys: set[str] = set()

    for f in findings:
        check_id = getattr(f, "check_id", "") or "unknown"
        path = getattr(f, "path", "") or ""
        # Audit Finding dataclasses are NOT uniform:
        # - tech-debt, security, coverage: use `detail` (str)
        # - bug-pattern: uses `message` (str) + `line` + `line_num`
        # The helper falls back to `message` so callers don't have to
        # adapt their finding shape.
        detail = (
            getattr(f, "detail", None)
            or getattr(f, "message", None)
            or ""
        )
        line_num = getattr(f, "line_num", 0) or 0
        if line_num and path and ":" not in detail[:50]:
            # Prefix the detail with the line number so the row carries
            # the source location even without re-running the audit.
            detail = f"line {line_num}: {detail}"
        # Dedup tail: prefer path (most-specific natural key) but fall
        # back to slugified detail when the audit doesn't carry a path
        # (e.g. an overall-coverage-drift finding has path="(repo)").
        dedup_tail = path if path and path != "(repo)" else detail
        key = make_marker_key(audit_name, check_id, dedup_tail)
        seen_keys.add(key)

        # Finding text rendering: path-prefixed when present, else
        # just the detail. Pipe escaping protects the table.
        finding_text = (
            f"**{path}** — {detail}"
            if path and path != "(repo)"
            else detail
        )
        finding_text = finding_text.replace("|", "\\|")

        if key in rows_by_key:
            old = rows_by_key[key]
            # Strip any prior auto-resolved annotation since the
            # finding has re-appeared (it WAS resolved, but the
            # underlying issue is back).
            notes = re.sub(
                rf"{re.escape(RESOLVED_PREFIX)} \d{{4}}-\d{{2}}-\d{{2}};?\s*",
                "",
                old.notes,
            ).strip()
            rows_by_key[key] = AuditRow(
                marker_key=key,
                finding_text=finding_text,
                first_seen=old.first_seen,
                last_seen=today,
                notes=notes,
            )
            updated += 1
        else:
            rows_by_key[key] = AuditRow(
                marker_key=key,
                finding_text=finding_text,
                first_seen=today,
                last_seen=today,
                notes="",
            )
            inserted += 1

    # Auto-detected-resolved pass: any row for THIS audit_name whose key
    # was NOT in `seen_keys` should get the resolved annotation (idempotent).
    auto_resolved = 0
    audit_prefix = f"{audit_name}/"
    for key, row in list(rows_by_key.items()):
        if not key.startswith(audit_prefix):
            continue
        if key in seen_keys:
            continue
        if RESOLVED_PREFIX in row.notes:
            continue  # already flagged
        resolved_note = f"{RESOLVED_PREFIX} {today}"
        merged_notes = (
            f"{row.notes}; {resolved_note}".lstrip("; ").strip()
            if row.notes else resolved_note
        )
        rows_by_key[key] = AuditRow(
            marker_key=row.marker_key,
            finding_text=row.finding_text,
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            notes=merged_notes,
        )
        auto_resolved += 1

    new_section = _render_section(list(rows_by_key.values()))
    _write_backlog(head + new_section + tail)
    return {
        "inserted": inserted,
        "updated": updated,
        "auto_resolved": auto_resolved,
    }


# --- Shared audit-side wrapper --------------------------------------------


def run_for_audit(audit_name: str, findings: list) -> None:
    """Audit-side wrapper: upsert findings, log a one-line summary, and
    swallow errors so a broken backlog_autofile can't take down the
    audit itself (the email channel is the primary durable signal —
    autofile is a value-add on top).

    Each of the 4 recurring audits calls this from its main() when
    the ``--autofile`` flag is passed. See the cascade comment in
    CLAUDE.md for the workflow-side commit-back step.
    """
    try:
        result = upsert_findings(audit_name, findings)
        sys.stdout.write(
            f"[{audit_name}] backlog autofile: "
            f"inserted={result['inserted']} "
            f"updated={result['updated']} "
            f"auto_resolved={result['auto_resolved']}\n",
        )
    except (FileNotFoundError, ValueError, OSError) as e:
        sys.stderr.write(
            f"[{audit_name}] backlog autofile failed (continuing): "
            f"{type(e).__name__}: {e}\n",
        )


# --- CLI entry point -------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Ad-hoc CLI for testing / one-off manual upserts.

    Audits normally call ``upsert_findings(...)`` programmatically;
    this CLI exists so an operator can seed a row without writing a
    finding dataclass instance.
    """
    parser = argparse.ArgumentParser(
        description="Upsert a single audit finding into BACKLOG.md.",
    )
    parser.add_argument(
        "--audit", required=True,
        help="Audit identifier (bug-pattern|security|tech-debt|coverage).",
    )
    parser.add_argument("--check-id", required=True, help="Finding.check_id")
    parser.add_argument("--path", default="", help="Finding.path (optional)")
    parser.add_argument("--detail", required=True, help="Finding.detail")
    args = parser.parse_args(argv)

    @dataclass
    class _Adhoc:
        check_id: str
        path: str
        detail: str

    result = upsert_findings(
        args.audit,
        [_Adhoc(
            check_id=args.check_id,
            path=args.path,
            detail=args.detail,
        )],
    )
    sys.stdout.write(
        f"backlog-autofile: inserted={result['inserted']} "
        f"updated={result['updated']} "
        f"auto_resolved={result['auto_resolved']}\n",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
