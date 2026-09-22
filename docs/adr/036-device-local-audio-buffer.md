# ADR-036: Reflection audio may buffer on the user's own device (IndexedDB)

Date: 2026-09-22

Status: ACCEPTED (operator-approved 2026-09-22; retention window default = 24h)

Supersedes: none — the "audio never touches disk" guarantee was never
written up as an ADR. It lived only in CLAUDE.md, four docstrings, the
README and two user-facing pages (enumerated below). This ADR is the
first time it is recorded as a decision, and it records it in its
narrowed form.

## Context

The app has claimed for its whole life that reflection/voice audio is
"processed in memory only — never written to disk or the DB". The claim
is restated in eight files:

| # | Site | Audience |
|---|---|---|
| 1 | `CLAUDE.md:639` (standing security rule, phrased about images) | dev |
| 2 | `models.py:479` (`Reflection` docstring) | dev |
| 3 | `reflection_api.py:27-28` (module docstring) | dev |
| 4 | `reflection_service.py:21` (Security block) | dev |
| 5 | `README.md:180-181` (voice-memo section) | dev |
| 6 | `templates/docs.html:655` + `~681` | **user-facing** |
| 7 | `templates/reflection.html:117-119` (shown in the recording UI) | **user-facing** |
| 8 | `migrations/versions/f3a4b5c6d7e8_add_reflections_table.py:11` | dev |

(Eight files, nine lines — site 6 states it twice. Two are user-facing,
which is what makes this a fact-check-rule change and not just a
docstring sweep.)

#326 (shipped 2026-09-22, `19a0e59`) raised the per-segment recording cap
in the weekly reflection from 10 to 30 minutes, after measuring that the
real constraint is Whisper's **25MB per-REQUEST** limit — a size limit,
not a duration one — and pinning `audioBitsPerSecond` to 32000 so 25MB is
~109 minutes. A 30-minute segment is ~6.9MB.

That tripled the blast radius of a flaw that was already there. A
segment's audio lives ONLY in an in-memory JS array (`chunks` in
`static/reflection.js:128`, appended at `ondataavailable`, line ~278)
until the user hits Pause, at which point `onstop` builds the Blob and
uploads it. If iOS evicts the backgrounded Safari tab mid-recording,
every byte is lost, silently. The #324 draft autosave protects
transcribed **text** (`POST /api/reflection/draft`); it does nothing for
audio that has not been uploaded yet.

Note the deliberate asymmetry with #324: drafts were put **server-side**
precisely so a reflection follows the user between phone and laptop
(`static/reflection.js:1037-1039` — "has to follow the user between
phone and laptop, which rules out localStorage"). Audio goes the other
way, device-local, for the privacy reason in the Decision. The two are
not inconsistent; they optimise different things (continuity vs.
minimising where audio exists at all).

## Decision

Buffer each MediaRecorder chunk into **browser-origin IndexedDB on the
user's own device** as it arrives, and delete it as soon as that segment
is transcribed — narrowing the guarantee from "audio never touches disk"
to **"audio never touches the SERVER's disk; on the user's own device it
may exist transiently, in sandboxed browser storage, for at most the
retention window."**

Scope, precisely:

- **The server half is UNCHANGED and still binding.** No audio is ever
  written to server disk or to Postgres. `voice_service` keeps streaming
  the upload straight to Whisper in memory; there is no audio column, no
  staging directory, no object store. Claim sites 2/3/4/8 narrow only in
  the sense that they must stop implying the *device* side.
- **Device-local only**, in browser-origin IndexedDB inside the browser's
  sandboxed profile storage (on iOS, the app's WebKit container). Not the
  filesystem, not a user-visible path, not synced anywhere.
- **Unencrypted at rest.** The chunks are stored as-is and rely on OS
  full-disk encryption. Stated here honestly as an accepted risk, not
  papered over — see Consequences.
- **Transient by construction.** Chunks for a segment are deleted (a) as
  soon as that segment is successfully transcribed, (b) on Done, (c) on
  Cancel, and (d) a bounded retention window — **24h, proposed default** —
  purges orphans on the next page load.
- **Recovery is offered, never automatic.** If orphaned audio is found on
  load, the user is asked whether to recover it. It is NOT silently
  transcribed (that spends the user's Whisper money without consent) and
  NOT silently discarded (that reintroduces the exact failure this ADR
  exists to fix).

The 5s `RECORDER_TIMESLICE_MS` that #326 added
(`static/reflection.js:54`, passed at `mediaRecorder.start()`, line ~322)
already produces the chunk stream this needs — it was added to make
segment size observable live, and the buffer rides on it for free. No new
recording machinery.

**The buffer FAILS OPEN.** Every call resolves rather than rejects. If
IndexedDB is unavailable (private mode, quota exhausted, old browser),
recording must still behave exactly as it did before — the in-memory
`chunks` array remains the primary path and the buffer is insurance,
never a dependency. This is a load-bearing property, not an
implementation detail: a safety net that can break the thing it protects
is a net loss.

**Implementation** (#327, in flight at the time of writing): the logic
lives in the dual-export helper `static/audio_buffer.js`
(`window.audioBuffer` in the browser, `module.exports` for Jest — same
pattern as `static/reflection_helpers.js`), keyed on
`DB_NAME = "taskmanager-audio"` with `RETENTION_MS = 24h`. It exposes
`dropSegment()` / `purgeAll()` / `purgeExpired(nowMs, maxAgeMs)`. Wiring
in `static/reflection.js`: aliased at line 137, `dropSegment` on
successful transcription (line ~473), `purgeAll` on Done and Cancel
(lines ~541 and ~563), and `offerRecoveredAudio()` (line ~1359, called
at ~1403) which runs `purgeExpired()` first and then surfaces the
`reflRecoverBanner` Use/Discard choice.

**Regression tests — written, and they are the gate.** Per CLAUDE.md
anti-pattern #3, the buffer's decision logic is covered by 14 Jest cases
in `tests/js/unit/audio_buffer.test.js` (retention predicate including
the exact 24h boundary, an undatable orphan failing *toward* deletion,
and byte-derived orphan descriptions). The IndexedDB plumbing itself is
exercised against a REAL browser in `tests/e2e/pages.spec.js`
("transient audio buffer (#327)", 10 cases) rather than a shim, because
the promise being enforced is about actual storage: chunks persist
across a reload, `dropSegment` leaves neither the index row NOR the
chunks, dropping one segment doesn't touch another, `purgeExpired`
deletes only the over-retention one, an expired orphan is purged unread
and never offered, and offering an orphan does not consume it.

Both halves of the narrowed scope are asserted mechanically: a
transcribed segment's chunks are **gone**, and an over-retention orphan
is **purged unread**.

## Consequences

**Easy:**
- A backgrounded-tab eviction mid-recording stops being a silent total
  loss. Up to 30 minutes of the user's spoken reflection now survives to
  the next page load.
- It rides the #326 timeslice — no change to the recorder's control flow,
  bitrate, byte budget, or cap logic.
- Nothing about the server's threat model moves. No new endpoint, no new
  credential, no new egress caller, no new rate-limit surface, no
  server-side orphan reaper.
- The privacy claim gets *more* accurate, not vaguer: "never on our
  server" is a stronger, checkable statement than a blanket "never on
  disk" that was already quietly wrong the moment a Blob hit the browser.

**Hard:**
- **Every claim site must be narrowed**, and two of them
  (`templates/docs.html`, `templates/reflection.html:117-119`) are
  user-facing — so per CLAUDE.md's user-facing documentation fact-check
  rule they need a fact-check table cited to `file:line`, plus Phase 6 at
  desktop and mobile. The in-recording-UI hint is the load-bearing one:
  it currently tells the user, *during recording*, something that will no
  longer be true.
- **A regression test asserting the NEW scope is now load-bearing**
  (CLAUDE.md cascade rule for security-sensitive refactors). It must
  assert both halves: that a transcribed segment's chunks are *gone* from
  IndexedDB, and that the server still never persists audio. A green test
  where it should be red means the "transient" property has silently
  become "permanent" — and the failure is invisible, because a buffer
  that never deletes looks identical to a working one from the UI.
- **Threat-model delta (explicit).** Someone with access to the unlocked
  device — or to an unencrypted disk image of it — could recover recent
  un-transcribed audio. That is a real, new exposure. It is **accepted**
  because it is bounded by, in combination: (a) the retention window, so
  the exposed set is at most one recording session plus up to 24h of
  orphans, never a history; (b) device-local only, so nothing is added to
  the server's blast radius or to any credential's; (c) browser-sandboxed
  storage plus OS full-disk encryption at rest; and (d) this is a
  single-user personal app and the audio is the user's own voice talking
  about their own work — there is no second tenant to leak to. Weighed
  against the status quo risk it removes — silently losing up to 30
  minutes of the user's spoken reflection — the trade is worth taking.
- **Unencrypted at rest is a deliberate gap.** Encrypting the chunks
  client-side would need a key, and any key the page can reach on reload
  without the user typing something is stored right next to the data it
  protects — security theatre. Honest dependence on OS FDE beats a fake
  envelope. Revisit only if the device threat model changes.
- **First IndexedDB usage in the codebase** — before #327, `grep -rn
  indexedDB static/ templates/` returned nothing. New failure modes with
  no local precedent: quota exhaustion mid-recording, private-browsing
  restrictions, and the browser evicting the store itself. The fails-open
  contract above is the mitigation, but it is a contract every future
  edit to `audio_buffer.js` has to keep.
- **Two new cascade obligations** from CLAUDE.md's table, because
  `static/audio_buffer.js` is a new static asset: it must be added to
  `APP_SHELL` in `static/sw.js` and to `EXPECTED_STATIC_FILES` in
  `health.py`, and `CACHE_VERSION` must be bumped. Miss the `health.py`
  row and `/healthz` reports `static_assets: fail` on deploy.
- **The recovery prompt is new UX that can itself go wrong.** A
  false-positive "recover?" on every load would be worse than the bug it
  fixes, so orphan detection has to be precise about what counts as an
  orphan.

## Alternatives considered

- **A. Flush on background — pause + upload from the existing
  `visibilitychange` handler** (`static/reflection.js:326`, which today
  only re-checks the clock cap because iOS freezes `setTimeout` when
  backgrounded). Rejected: it preserves the in-memory guarantee but races
  a shutdown it cannot win. The payload is megabytes (~6.9MB at 30 min)
  and `sendBeacon` caps around 64KB, so no transport reliably completes
  during teardown. Worse, it is completely blind to an outright tab kill,
  which fires no event at all — the exact case that motivates this ADR.
- **B. Rolling upload to a server staging area.** Rejected: strongest
  coverage, but it breaks the guarantee in the hardest possible direction
  — audio on the *server's* disk, which is the half this ADR deliberately
  keeps intact. It also needs a new endpoint, chunk storage, an
  ordering/resume protocol, and an orphan reaper: a substantial new
  server surface to fix a client-side durability bug.
- **C. Do nothing / revert to the 10-minute cap.** Rejected implicitly by
  #326: the cap was a conservative proxy for a size limit that has now
  been measured and pinned. Reverting it would give up a capability the
  user explicitly asked for in exchange for a bug that has a
  device-local fix.
- **`localStorage` instead of IndexedDB.** Rejected: string-only (Blobs
  would need base64, inflating ~33%), synchronous on the main thread, and
  typically capped around 5-10MB — under a single 30-minute segment.

## Related

- **#327** — the implementation this ADR authorises (`static/audio_buffer.js`
  plus the seven claim-site edits). This ADR is the decision record; #327
  is the ship.
- **#326** (`19a0e59`) — raised the segment cap 10 → 30 min, pinned the
  bitrate to 32kbps, and added the 5s timeslice this buffer rides on. The
  change that made this flaw worth fixing now.
- **#324** — resumable reflection drafts. Protects transcribed *text*
  server-side; deliberately the opposite storage choice, for continuity
  rather than privacy. Does not cover un-uploaded audio.
- **ADR-025** — central upload helper; the segment upload path this
  buffer feeds is unchanged.
- **ADR-023 / ADR-007** — the Whisper call still goes through
  `egress.safe_call_api` with the key in a header. Untouched.
