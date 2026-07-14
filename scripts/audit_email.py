"""Shared alert-email body renderer for the recurring audit scripts (#302).

Every recurring audit — bug-pattern, tech-debt, coverage, security-posture —
sends the SAME shape of weekly/monthly alert: a self-explanatory "WHAT THIS
IS" preamble (findings are advisories, not build failures; a *missing* email
is the real signal), plain-English per-check descriptions, per-finding detail
blocks, a compact "clean this run" list, and numbered next steps.

Centralizing that format here keeps the four emails consistent AND avoids four
copies of a ~55-line block (which the tech-debt `code-duplication` check would
itself flag). Standalone: stdlib only, no app import — imported by the audit
scripts via the same ``sys.path.insert(0, PROJECT_ROOT); from scripts import
audit_email`` pattern they already use for ``backlog_autofile``.

The renderer is Finding-dataclass-agnostic: callers pass already-grouped plain
data (``findings_by_check`` = ``{label: [(loc, [detail_line, ...]), ...]}``),
so each script maps its own Finding shape (``message``/``line`` vs ``detail``)
without this module knowing about it.
"""
from __future__ import annotations

RULE = "─" * 56


def render(
    *,
    today: str,
    tag: str,
    title: str,
    unit_word: str,
    cadence_adj: str,
    scope_blurb: str,
    per_check_counts: list[tuple[str, int]],
    findings_by_check: dict[str, list[tuple[str, list[str]]]],
    descriptions: dict[str, str],
    todo_steps: list[str],
    subject_extra: str = "",
    header_extra: list[str] | None = None,
) -> tuple[str, str]:
    """Build ``(subject, body_text)`` for one audit email.

    Args:
        today: ISO date string (caller-supplied so it stays deterministic).
        tag: subject bracket tag, e.g. ``"tech-debt"``.
        title: body header line, e.g. ``"Weekly tech-debt audit"``.
        unit_word: what the run is called in prose — ``"scan"`` or ``"audit"``.
        cadence_adj: ``"weekly"`` or ``"monthly"``.
        scope_blurb: what the audit watches, spliced into the preamble.
        per_check_counts: ``[(label, count), ...]`` for every check, in order.
        findings_by_check: ``{label: [(loc, [detail_line, ...]), ...]}``. ``loc``
            is ``""`` when a finding has no file location.
        descriptions: ``{label: one-line plain-English description}``.
        todo_steps: numbered "what to do" steps (the renderer adds ``1.``/``2.``).
        subject_extra: appended inside the subject, e.g. ``" (87.3%)"``.
        header_extra: extra lines shown right after the RESULT line.
    """
    total = sum(len(v) for v in findings_by_check.values())
    n_checks = len(per_check_counts)
    cadence_word = "week" if cadence_adj == "weekly" else "month"

    whatis = (
        f"WHAT THIS IS — an automated {cadence_adj} {unit_word} of the repo "
        f"for {scope_blurb}. Findings are ADVISORIES to review, not build "
        f"failures: nothing here means production is broken. It emails EVERY "
        f"{cadence_word} even when clean, so a {cadence_word} with no email "
        f"means the {unit_word} itself stopped running — that silence is the "
        f"real thing to act on."
    )

    lines = [f"{title} — {today}", ""]
    lines += list(header_extra or [])

    if total == 0:
        subject = (
            f"[Taskmanager {tag}] ✓ all clear ({n_checks} checks)"
            f"{subject_extra} — {today}"
        )
        lines += [
            f"RESULT: ✓ all clear — 0 findings across {n_checks} checks. "
            "Nothing to do.",
            "",
            whatis,
            "",
            "Checks run (all clean):",
        ]
        for label, _count in per_check_counts:
            lines.append(f"  ✓ {label} — {descriptions.get(label, '')}")
        lines += ["", "Full log: the GitHub Actions run that sent this email."]
        return subject, "\n".join(lines)

    n_hit = sum(1 for v in findings_by_check.values() if v)
    noun = "issue" if total == 1 else "issues"
    subject = (
        f"[Taskmanager {tag}] {total} {noun} to review{subject_extra} — {today}"
    )
    lines += [
        f"RESULT: {total} {noun} to review, in {n_hit} of {n_checks} checks.",
        "",
        whatis,
        "",
    ]
    for label, _count in per_check_counts:
        hits = findings_by_check.get(label) or []
        if not hits:
            continue
        lines.append(RULE)
        n = len(hits)
        lines.append(f"{label} — {n} finding{'s' if n != 1 else ''}")
        if descriptions.get(label):
            lines.append(descriptions[label])
        lines.append("")
        for loc, detail_lines in hits:
            detail_lines = detail_lines or [""]
            if loc:
                lines.append(f"  {loc}")
                lines += [f"      {d}" for d in detail_lines]
            else:
                first, *rest = detail_lines
                lines.append(f"  • {first}")
                lines += [f"      {d}" for d in rest]
            lines.append("")
    lines.append(RULE)

    clean_labels = [lbl for lbl, c in per_check_counts if c == 0]
    if clean_labels:
        lines += ["", "Clean this run: " + ", ".join(clean_labels)]

    lines += ["", "WHAT TO DO:"]
    for i, step in enumerate(todo_steps, start=1):
        lines.append(f"  {i}. {step}")
    lines += [
        "",
        "Full log + raw output: the GitHub Actions run that sent this email.",
    ]
    return subject, "\n".join(lines)
