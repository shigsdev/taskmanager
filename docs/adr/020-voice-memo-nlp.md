# ADR-020: Voice-memo NLP — structured field inference

Date: 2026-04-21
Status: ACCEPTED

## Context

Backlog #36 — before this change, a voice memo flowed: audio →
Whisper transcript → Claude returns `list[str]` of task titles →
client renders a review screen with checkbox + title + type
dropdown. Metadata (tier, due_date) was always blank; the user had
to edit each task manually after import. For a voice-first capture
flow this cost more UI time than typing the tasks manually.

The user's framing: "NLP for voice memos to have intelligence into
what I am saying." Not just extract titles — infer the metadata the
speaker implied.

## Decisions

### 1. New structured parser, not a modified one

`parse_voice_memo_to_tasks(transcript)` lives alongside the existing
`parse_tasks_from_text` (which image OCR still uses). Two reasons:

- Image OCR's text doesn't have spoken context like "tomorrow" /
  "by Friday"; forcing it through a structured prompt would add
  hallucination risk without adding signal.
- Separate functions let each evolve independently. When image OCR
  eventually wants structured output (maybe when we add handwritten-
  due-date detection), it gets its own prompt, not a shared
  monster.

### 2. Structured output schema

Each candidate:

```json
{
  "title": "string, ≤100 chars, required",
  "type": "work" | "personal",
  "tier": "inbox" | "today" | "tomorrow" | "this_week",
  "due_date": "YYYY-MM-DD" | null
}
```

Tier deliberately omits `next_week`, `backlog`, `freezer` — voice
speech rarely uses that language ("I'll put this in the backlog")
without also being a meta-management statement, not an actual
commitment. Keeping the allowed set tight reduces hallucination
surface.

### 3. Today's date is injected into the prompt

Required for tier and due_date inference. The prompt contains
`Today's date is {today}` so Claude can resolve "tomorrow",
"Friday", "next Tuesday", "the 15th" against a specific date. Passed
in from Python via `date.today().isoformat()`.

Server TZ note: this uses `date.today()` which follows the server's
local time (UTC on Railway). That's slightly inconsistent with the
DIGEST_TZ semantics we established in #28 for tier→due_date auto-fill.
Acceptable in practice — Claude's response is validated against the
user's edits on the review screen; a 5-hour TZ drift at the Claude
end gets caught by the user before it becomes a real Task. Revisit
if users report "it thought 'tomorrow' meant yesterday."

### 4. Defensive normalisation after Claude

`_normalise_voice_candidates` is a strict cleanup pass that runs
between Claude's response and the API payload:

- Drops items with missing / empty / non-string titles.
- Truncates over-long titles to 100 chars (matches the prompt's
  hint but enforces it even when Claude ignores it).
- Coerces unknown `type` values to `"personal"` (safer default
  than `work` for voice memos, which tend toward personal life).
- Coerces unknown `tier` values to `"inbox"`.
- Validates `due_date` as ISO YYYY-MM-DD; drops (→ null) if
  malformed or not a string.

Tests pin every branch of this normaliser (6 cases) so a future
prompt regression — Claude starting to emit "Tier.INBOX" instead
of `"inbox"`, for example — gets caught at unit-test time.

### 5. Fallback chain on Claude failure

Three layers:

1. Happy path: structured parser returns valid JSON → candidates
   flow through with inferred fields.
2. Structured parser raises `RuntimeError` (missing API key, 4xx
   from Anthropic) → 422 response with transcript preserved so the
   user can read it back and re-record or paste manually.
3. Structured parser raises any other `Exception` → fall back to
   the old `parse_tasks_from_text` (title-only) and wrap each title
   as `{title, type: "personal", tier: "inbox", due_date: null}`.
   Degraded but functional — at least the user gets SOME structure.

### 6. `create_tasks_from_candidates` now honours tier + due_date

The function is shared with image OCR. Previously it hardcoded
`tier=INBOX` and ignored any date hints. Extended to honour tier +
due_date from the candidate dict, with the old default (Inbox, no
date) preserved when those keys are missing — so image OCR's flatter
candidate shape keeps the old behaviour.

Unknown tier values silently fall back to Inbox; unknown due_date
formats silently become null. Both are per-candidate failures — one
bad candidate doesn't fail the whole batch.

### 7. Review UI gains two controls per row

`static/voice_memo.js renderCandidate` now produces:
`[checkbox] [title input] [type select] [tier select] [date input]`.

Tier options: Inbox / Today / Tomorrow / This Week (the valid
inference set). Due date uses `<input type="date">` — gives iOS the
wheel picker for free.

CSS on .voice-candidate flex-wraps at 600px so the 5-column row
stacks cleanly on mobile (checkbox + title on the first line, the
three dropdowns on the second).

Confirm-submit payload includes all four fields (title, type, tier,
due_date); the server's `create_tasks_from_candidates` consumes them
via decision #6.

## Consequences

**Easy:**
- No schema change.
- Existing image OCR path unchanged (same prompt, same
  title-list response shape).
- Defensive normalisation means a prompt regression is caught at
  the unit-test tier, not in prod.

**Hard / accepted trade-offs:**
- Cost: slightly larger prompt (~200 tokens → ~400 tokens) + more
  tokens in the response (dicts vs strings). Max-tokens bumped
  from 1024 → 2048 to accommodate. For a typical 30-60 second voice
  memo the extra cost is fractions of a cent; logged via AppLog
  for future budget review if needed.
- Hallucination risk on tier/due_date fields — Claude could emit
  "tomorrow" for a vague "we should do this soon" phrase. User
  corrects on the review screen; normalisation + strict enum
  coercion guards the server.
- The TZ note in decision #3 — acceptable for MVP but a real
  correctness gap if users travel timezones.

## Alternatives considered

- **Add tier/due_date to the existing `parse_tasks_from_text`
  prompt**: rejected — forces image OCR through the same
  hallucination surface for no gain.
- **Skip Claude entirely and use regex for "tomorrow" / "Friday"**:
  rejected as brittle. Claude handles paraphrasing, negation
  ("not tomorrow, the day after"), and mixed-signal utterances in
  ways regex cannot without becoming its own parser.
- **Include project_hint / goal_hint in the MVP**: deferred. Adds
  complexity around matching hints to existing DB records (exact
  title match? fuzzy match? confidence thresholds?) and wasn't the
  primary user pain. Future backlog item.
- **Detect "not a task" utterances and flag them**: deferred. Scope
  creep for MVP. Currently any line that parses as a candidate
  becomes a candidate; user drops it by unchecking.

## Verification

- **Unit (normaliser)**: 6 cases in `TestVoiceNormaliser` — no
  title, blank/whitespace title, unknown type, unknown tier,
  malformed/missing due_date, long-title truncation, and a full
  end-to-end preservation assertion.
- **Unit (create_tasks)**: 3 cases in
  `TestVoiceCreateTasksFromCandidates` — inferred tier + due_date
  land on the Task; missing tier defaults to Inbox (image-OCR
  regression guard); bad due_date is silently dropped.
- **Integration (voice_api happy path)**: updated
  `test_happy_path_returns_candidates` asserts tier/due_date flow
  through the API response unchanged from the Claude mock.
- **Fallback preservation**: `test_parsing_failure_keeps_transcript_for_user_recovery`
  updated to patch the new function name; RuntimeError → 422 + transcript.
- **Full suite**: 1012 passed, 3 skipped. Gates green.
- **Phase 6**: deferred to the user's next real voice memo — unit
  tests cover the structural contract, but the subjective inference
  quality ("does it infer tomorrow correctly when I ramble?") is
  only meaningful against real spoken input.
