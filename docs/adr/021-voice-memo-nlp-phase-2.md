# ADR-021: Voice memo NLP phase 2 — project / goal hints + non-task detection

Date: 2026-04-21
Status: ACCEPTED

## Context

Backlog #37, the follow-up to #36's MVP. ADR-020 explicitly deferred
two items:

1. **Project / goal hinting** — so "finish the Q2 OKR deck" can
   pre-select the user's actual Q2 OKRs project, not leave project
   empty for manual linking.
2. **Non-task detection** — so reflective utterances ("I felt
   scattered today", "quick reminder that I'm doing fine") either
   get dropped or surfaced as notes, not cluttered into the task
   list as phantom to-dos.

The user caught the gap a session after #36 shipped: "wasn't there
an expansion for the feature we just did?" — the follow-up backlog
row existed in my head and in the ADR but had never been written
down as #37.

## Decisions

### 1. Prompt extension, not a new prompt

`_VOICE_PARSE_PROMPT` grows two new fields:

- `project_titles: str` — comma-separated list of the user's ACTIVE
  project names, inline in the prompt. Claude is told to cite them
  verbatim or emit null. Not passing IDs — title match is simpler and
  humans say titles, not UUIDs.
- `goal_titles: str` — same treatment.

And each candidate in the response now has three new keys:

- `project_hint: str | null` — exact title of a user project, or null
- `goal_hint: str | null` — same for goals
- `is_task: bool` — false iff Claude determined this is pure
  reflection, not an action

Default `is_task=true` — a miss (Claude forgot to emit it) keeps the
item as a task. Only literal `False` flips it off.

### 2. Server resolves hints to UUIDs; unresolved hints stay as free text

`_normalise_voice_candidates` now builds a case-insensitive lookup
`{title.lower(): id}` from the projects/goals lists it was given
and resolves each candidate's hint against it. Three outcomes:

- **Match**: `project_id` / `goal_id` set; `project_hint` /
  `goal_hint` string also preserved (useful for UI explanation).
- **No match** (hallucinated name): ID stays null, hint string
  preserved so the UI can render "Heard project: X (no match)" and
  the user can create that project manually OR pick one from the
  dropdown.
- **No hint** at all: both null, no UI affordance needed.

Exact match, not fuzzy — by design. Fuzzy matching (Levenshtein,
token set, etc.) invites silent wrong matches; "Q2 OCR" ≠ "Q2 OKRs"
is the right answer. If the user types with an inconsistent case,
that's still exact.

### 3. `create_tasks_from_candidates` validates + honours the IDs

The existing signature extends: the candidate dict can now carry
`project_id` and `goal_id` strings. Each is parsed via
`uuid.UUID(...)` with `contextlib.suppress(ValueError)`; a bad value
silently nulls that one field without failing the whole candidate
or the whole batch. Same "one bad field, don't explode the batch"
stance as #36's bad-due_date handling.

### 4. Reflections render in a collapsed section on the review screen

`is_task === false` candidates go into a `<details>` block labeled
"Reflections / non-tasks (N) — usually kept OUT of your task list"
below the main task list. Default-unchecked so they're dropped by
default; user can expand, check, and promote to task via "Add
Selected".

This is the key UX safety rail: if Claude mis-flags an actual task
as "reflection," the item is still reachable — it's just one click
behind a section — and the cost of a miss is "user opens the
section and checks the box", not "user never sees the item."

### 5. Projects + goals loaded once per page, not per candidate

`voice_memo.js` runs `loadProjectsAndGoalsForReview()` during init
(before the user even starts recording). The review screen uses
the cached lists. Two reasons:

- Pre-fetching keeps the post-record latency low — the user
  already paid for the Whisper + Claude call; don't make them
  wait on two more fetches before the screen paints.
- Projects and goals change rarely during a single voice-memo
  session; one fetch is enough.

Failure is non-fatal — the dropdowns fall back to "(no project)"
and "(no goal)" only, and the hint-as-free-text path still works.

### 6. Fetch path is defensive

`_fetch_projects_and_goals_for_hints` returns empty lists on any
exception (DB unavailable, session error, etc.). The rest of the
voice flow still works — just without hint resolution. This is
consistent with the MVP's philosophy: Whisper and Claude get the
essential path, fancier features degrade gracefully.

## Consequences

**Easy:**
- Backward compatible with #36. A voice candidate that lacks
  `project_hint` / `goal_hint` / `is_task` flows through as a
  task in Inbox with no project or goal — identical to pre-#37
  behaviour.
- No schema change. `Task.project_id` and `Task.goal_id` already
  exist; we're just wiring the voice flow to populate them.
- Image OCR path is unchanged. It still uses
  `parse_tasks_from_text` (flat titles) and
  `create_tasks_from_candidates` without the new keys.

**Hard / accepted trade-offs:**
- Prompt size grows with the number of projects + goals. At typical
  single-user scale (under 20 each) this is fine. If users
  accumulate hundreds, the prompt could bloat and cost more tokens;
  address when it bites — possibly by only passing ACTIVE + recent
  projects.
- `is_task=false` items still get a title and go through the same
  review flow, just hidden in a section. The cost of that design:
  one extra component on the review screen. The benefit:
  non-destructive — nothing is ever auto-dropped, so a Claude
  miss is always recoverable.
- Exact-match hint resolution means typos in project names ("Q2"
  vs "Q2 OKRs") fall back to no-match. If users report this as a
  real friction, add a "did you mean…" affordance — deferred.

## Alternatives considered

- **Fuzzy match for hint resolution** (Levenshtein, token set):
  rejected. Silent wrong-match risk outweighs the convenience.
  Users can pick from the dropdown explicitly.
- **Auto-drop `is_task=false` items**: rejected. Non-destructive
  default matters when the classifier is noisy. The collapsed
  section is a cheap middle ground.
- **Pass project/goal IDs to Claude instead of titles**: rejected.
  Human speech uses titles; asking Claude to cite UUIDs via a
  mapping table gives the model two error surfaces (title
  recognition + UUID bookkeeping) instead of one.
- **Add a "confidence" score**: deferred. Claude's confidence
  on a structured-output cell is hard to quantify and easy to
  mis-trust; the review-screen edit pattern is already the user's
  correction loop, so a confidence number adds visual weight
  without a clear action the user can take.

## Verification

- **Unit (normaliser)**: 7 new `TestVoiceNormaliser` tests —
  exact-match, case-insensitive match, no-match leaves hint as
  free text, goal hint resolves, `is_task=false` preserved,
  `is_task` default is True, only literal False flips it off.
- **Unit (create_tasks)**: 2 new `TestVoiceCreateTasksFromCandidates`
  tests — project_id + goal_id land on the Task; malformed UUID
  silently nulled (batch survives).
- **Full suite**: 37 voice tests pass. All gates (ruff, pytest,
  jest, playwright-local, semgrep, gitleaks, docs-sync,
  arch-sync, pip-audit) green.
- **Phase 6**: deferred to next real voice memo against prod —
  inference quality under actual speech is the only meaningful
  way to exercise the prompt. Review UI structure verified by
  the new unit tests.
