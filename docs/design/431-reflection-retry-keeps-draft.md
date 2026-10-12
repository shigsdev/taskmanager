# #431 — A failed "Analyze so far" no longer costs the draft

Filed 2026-10-11 by the deep review (§A8).

## 1. Surface

| Step | Code | Problem |
|---|---|---|
| "Analyze so far" fails | `static/reflection.js` interim handler | Goes to the error screen with `showErr(…, true)`: "Your transcript was saved before the failure — it's in your history below" — false; it's still the open draft |
| Error screen → Try Again | `resetInput` | Empties the box, but leaves `lastSavedText` = the text and `draftRetired` = false |
| Next autosave (tab switch, any keystroke) | `saveDraftNow` → `shouldAutosaveDraft(lastSaved, "")` | "" ≠ last saved → `PUT {text: ""}`; the server overwrites the draft (`reflection_service.save_draft`) — the text is gone |

Start Over is hidden on a checkpoint review (#333), so the error screen's
Try Again is the only way to reach `resetInput` with a live draft today.

The final "Finish & analyze" path has a related but separate flaw — it
claims "saved in history" even when the failure came before anything was
saved (429, network) — filed as #464; it doesn't lose text (the draft
survives server-side; `clearDraftUi` blocks the autosave).

## 2. This ship

1. A failed "Analyze so far" returns to the writing view with the text
   where it was and shows the reason under the buttons
   (`#reflInterimError`, role=alert): "<reason> Your text is still here,
   and still saved as your draft." Cleared by the next attempt or keystroke.
2. `resetInput` sets `lastSavedText = null`, so an emptied box is never
   sent over a draft (an empty box with nothing of ours saved is skipped by
   `shouldAutosaveDraft`).
3. Help: one sentence under "Checkpointing a long reflection".
4. Playwright x 2 viewports (both red on the old page): the failed
   checkpoint keeps the box, the note and the server draft through a forced
   autosave; and Try Again on the error screen with a live draft never PUTs
   an empty box.
5. CACHE_VERSION; CLAUDE.md Phase 6 line + row.
