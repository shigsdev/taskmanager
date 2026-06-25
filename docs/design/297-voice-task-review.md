# Spec #297 — Voice Task Review ("walk my day while driving")

Status: **Draft / spec-first** (operator chose to spec before building, 2026-06-22)
Owner: single-user app
Related: voice memo (`voice_api.py` / `voice_service.py` / `static/voice_memo.js`),
voice capture (`static/voice_input.js`), weekly review (`/review`),
validator-cookie auth (`validator_cookie.py`), ADR-023 (egress), ADR-007 (keys).

---

## 1. Problem & goal

The operator wants to **triage today's tasks by voice during a commute** — hear
each open Today task read aloud, then say **complete / move / skip** to act on it,
ideally without touching or looking at the phone.

Success = a safe, eyes-free way to get through the Today list on the drive, with
the actions persisted to the same tasks the board/calendar show.

Non-goal: a general voice assistant. The vocabulary is a fixed, tiny command set.

---

## 2. The core constraint (this shapes everything)

The app is used as an **iOS PWA**. On iPhone:

- **Text-to-speech WORKS** — `window.speechSynthesis` is supported on iOS Safari.
  Nothing in the app uses it yet; this is the new "read aloud" half.
- **Continuous speech recognition does NOT work** — the Web Speech
  `SpeechRecognition` / `webkitSpeechRecognition` API (used today in
  `static/voice_input.js` + `static/capture.js`) is **unsupported on iOS Safari**.
  That's why the capture-bar mic is feature-detected and hidden on iPhone
  (`voice_input.js:24`). So the cheap "browser just listens for my command" loop
  that works on Android/desktop **does not give hands-free listening on the
  operator's phone.**

Therefore the *speak* half is easy and cross-platform; the *listen* half on
iPhone is the hard design problem, and the three options below differ almost
entirely on how they solve it.

---

## 3. Interaction loop (identical across input methods)

1. **Speak** (TTS): "Task 1 of 8 — Finalize the Q3 roadmap. Complete, move, or skip?"
2. **Capture** the spoken command (method varies — see §5).
3. **Parse** with a fixed command grammar (§4).
4. **Act** via the existing task API (§6), then **confirm** ("Done.") and
   **auto-advance** to the next task.
5. At the end: "That's all 8. 5 completed, 2 moved to tomorrow, 1 skipped."

Barge-in (interrupting the TTS to answer early) and "repeat" are Phase 3.

---

## 4. Command grammar

Small fixed vocabulary → a **dual-export, Jest-tested** helper
`static/voice_review_helpers.js` (`parseReviewCommand(transcript)`), same pattern
as `parse_capture.js`. A keyword matcher is correct here (≈6 intents) — cheaper
and more robust against a noisy transcript than calling Claude.

| Intent | Sample utterances | Action |
|---|---|---|
| `complete` | "complete", "done", "finished", "check it off" | `POST /complete` |
| `move:tomorrow` | "move to tomorrow", "push to tomorrow", "tomorrow" | `PATCH {tier:"tomorrow"}` |
| `move:next_week` | "next week", "move to next week" | `PATCH {tier:"next_week"}` |
| `move:backlog` | "backlog", "later", "move to backlog" | `PATCH {tier:"backlog"}` |
| `skip` | "skip", "next", "pass" | advance, no change |
| `repeat` | "repeat", "say again", "what" | re-read current |
| `cancel-review` | "stop", "quit", "I'm done" | end the session |

Unrecognized → "Sorry, I didn't catch that. Complete, move, or skip?" (re-prompt,
never guess a mutation).

---

## 5. Input-capture options (the fork)

| # | Approach | Hands-free on iPhone? | New surface | Effort |
|---|---|---|---|---|
| A | **PWA push-to-talk + Whisper** | No — 1 tap/command | reuse `/api/voice-memo` pipeline | Low–Med |
| B | **iOS Shortcut + Siri** | **Yes** | **scoped mutation token + action API** | Med |
| C | **Web Speech loop** (Android/desktop only) | n/a (not iPhone) | reuse `voice_input.js` | Low |

**A — PWA push-to-talk.** Full-screen button; press-and-hold to speak, release →
`MediaRecorder` clip → `POST` → Whisper (reuse `voice_service.py`) → parse → act.
Pros: lives in the web app, reuses an existing pipeline. Cons: one tap per command
(not hands-free); **iOS PWA `MediaRecorder` is known-finicky** (`voice_memo.js:120`);
~2–4 s latency/command.

**B — iOS Shortcut + Siri (the only truly hands-free path on iPhone).** A Shortcut
fetches Today, loops, `Speak Text` each task, `Dictate Text` to capture the reply,
branches to call the action API. "Hey Siri, review my tasks"; works over CarPlay.
Cons: authored in the Shortcuts app (not code we own/test); the dictation loop is a
bit clunky; **needs a mutation-capable API token** (see §7) — new auth surface.

**C — Web Speech continuous loop.** On Android/desktop the existing
`SpeechRecognition` gives a near-free hands-free loop. Worth wiring as a bonus, but
it does **not** help the iPhone case.

---

## 6. Backend — mostly already there

Existing, reused as-is (all `@login_required`):

- List Today: `GET /api/tasks?tier=today` (or client-filter the full list).
- Complete: `POST /api/tasks/<uuid>/complete` (`tasks_api.py:148`).
- Move tier: `PATCH /api/tasks/<uuid>` `{tier: ...}` (`tasks_api.py:125`).
- Cancel: `POST /api/tasks/<uuid>/cancel` (`tasks_api.py:166`).

Phase-1 (briefing) and the Web-Speech/Whisper PWA paths run **in the browser**, so
they authenticate with the **existing OAuth session** — no new backend needed
beyond a new page/route to host the UI.

The **only** new backend work is for **Option B (the Shortcut)**, because a
Shortcut can't carry an OAuth session and the **validator cookie is GET-only**
(`validator_cookie.py` — read-only branch covers GET/HEAD/OPTIONS, so it cannot
complete/move). See §7.

---

## 7. New auth surface (Option B only) — requires an ADR

To let an iOS Shortcut **mutate** tasks, introduce a **scoped action token**:

- A long-lived, single-purpose bearer token (header `Authorization: Bearer …`,
  never in a URL per ADR-007), minted offline (like the validator cookie) and
  stored only in the Shortcut.
- **Scope it tightly:** only the review actions — `complete`, retier among a
  whitelist of tiers, `cancel` — on the operator's own tasks. NOT a general API key.
- Revocable: tie it to `SECRET_KEY` rotation and/or a stored token id so a leak is
  a one-line kill, matching the validator-cookie kill-switch model.
- Rate-limited (`@limiter.limit`) per the cascade rules for user-controlled routes.
- **Mandatory ADR** (new file `docs/adr/NNN-voice-review-action-token.md`):
  this widens the mutation auth boundary beyond OAuth, so per CLAUDE.md
  ("refactored a security-sensitive function / broadened a scope → write an ADR")
  the decision + threat-model delta must be recorded, with a regression test
  asserting the token CANNOT do anything outside its scope.

This is the single biggest reason Option B is "Medium not Low" effort, and why
it's deliberately **not** in the Phase-1 MVP.

---

## 8. Phasing (recommended build order)

- **Phase 1 — "Today briefing" (listen-first, safe, cheap).** New
  `/today-review` page/mode: `speechSynthesis` reads each Today task in order with
  a short pause; a single full-screen **✓ complete current** tap for use only when
  stopped. No command recognition yet. Ships in-stack today; validates whether
  audio review is actually useful on the commute before investing in §7.
- **Phase 2 — hands-free input.** (a) wire the Web Speech continuous loop for
  Android/desktop (cheap, reuses `voice_input.js`); (b) for iPhone hands-free,
  build Option B (Shortcut + the §7 token API + ADR). Pick (b) if true zero-touch
  is required.
- **Phase 3 — polish.** Barge-in (cancel TTS on speech start), "repeat",
  end-of-session summary, undo-last, optional Whisper push-to-talk fallback for
  iPhones where the user prefers staying in the PWA over Siri.

---

## 9. Safety (load-bearing — this is a driving feature)

- Engineer **out** screen interaction while moving. Default to fully-audio paths;
  any tap must be a **single large full-screen target** used only when stopped.
- TTS pace + a pause between tasks so the driver isn't rushed.
- Never require reading the screen to recover from an error — re-prompt by voice.
- Consider gating the "complete tap" behind a "are you stopped?" affordance or
  only exposing it in Phase 1's listen-mode, not the hands-free modes.
- Document in the SOP that this feature's Phase 6 includes an **eyes-free
  walkthrough** (can the whole loop be driven with the screen off / face down?).

---

## 10. Testing plan

- **Jest**: `voice_review_helpers.parseReviewCommand` — every intent + fuzzy
  utterances + the "unrecognized → re-prompt, never mutate" rule (anti-pattern #3).
- **pytest**: the §7 token — auth accepted on the whitelisted actions, **rejected**
  on every out-of-scope route/method; rate-limit; revocation via SECRET_KEY.
- **Phase 6**: the briefing page at desktop + mobile, plus the eyes-free
  walkthrough above. PWA caveat: Web Speech / `MediaRecorder` must be smoke-tested
  in the **installed standalone PWA**, not just a browser tab (per CLAUDE.md PWA
  rule) — TTS and mic permissions behave differently there.
- **Prod smoke**: the new page renders + (Phase 2) the token API rejects an
  unauthenticated mutation.

---

## 11. Cascade touch-points (when built)

- New `/today-review` route → `base.html` nav (or a capture-bar entry),
  `active_page`, `ARCHITECTURE.md` route catalog + Components, `templates/docs.html`
  (user-facing Help — fact-checked), Phase 6.
- New `static/voice_review*.js` → `sw.js` APP_SHELL + `health.py`
  EXPECTED_STATIC_FILES + CACHE bump.
- New token (Option B) → ADR (§7), README env-var/token docs, `scrub_sensitive`
  coverage for the token format + a `test_strips_*` log test, threat-model note in
  CLAUDE.md, rate-limit.
- New external caller? No — Whisper reuse routes through the existing
  `voice_service.py` (already ADR-023-compliant).

---

## 12. Open decisions (for the operator)

1. **Is fully zero-touch a hard requirement?** If yes → Option B (Shortcut + token
   + ADR). If a single tap at stoplights is acceptable → Option A (PWA push-to-talk)
   stays in-stack with no new auth surface.
2. **Today only, or Today + overdue?** (Overdue items are arguably the most useful
   to surface on a commute.)
3. **Should "move" default to a single most-common target** (e.g. "move" = tomorrow)
   to shrink the spoken grammar?
4. **CarPlay** matters? Only Option B reaches it.

---

## 13. Out of scope (v1)

Multi-user; arbitrary natural-language commands beyond the grammar; editing task
text by voice; creating tasks by voice (that's the existing voice-memo feature);
offline operation without network (Whisper + API both need connectivity).
