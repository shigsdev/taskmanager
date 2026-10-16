# #464 — A failed Finish & analyze that saved nothing

Filed 2026-10-11 while scoping #431. Checked 2026-10-16 against
`static/reflection.js` `submitReflection`, `static/api_client.js`
`apiFetch` and `reflection_api.submit`.

## What was wrong

`POST /api/reflection` saves the transcript (and retires the draft) BEFORE
it calls Claude, so an analysis failure answers 422 / 500 with
`{saved: true, reflection_id}`. The page couldn't read that — `apiFetch`
throws `new Error(body.error || statusText)` and drops the body — so every
failure was treated as "saved":

- `clearDraftUi()` — stops the autosave as if the draft were gone;
- the error screen with "Your transcript was saved before the failure —
  it's in your history below";
- its only button, Try Again, empties the box.

A failure BEFORE the save — the `PAID_API` rate limit (429, an HTML body,
so the message read "TOO MANY REQUESTS"), a dropped connection, a 400 /
422 on the input, a 413 — saved nothing and left the draft live. The claim
was false, and the text was off screen (safe in the draft until reload,
because `clearDraftUi` had stopped the autosave).

## This ship

- `apiFetch`: an error from a non-ok answer also carries `status` and the
  parsed `body` (additive; `message` unchanged).
- `reflectionHelpers.submitFailure(err)` → `{saved, message}`:
  - `saved` only when the body says `saved: true` — then the old
    behaviour and message, word for word;
  - otherwise `saved: false` and "Couldn't send it for analysis: <reason>.
    Nothing went to your history — your text is still here, and still
    saved as your draft." The reason for a 429 is "too many analyses in a
    minute — wait a minute and try again"; for anything else the server's
    message (or the network error).
- `submitReflection` on `saved: false`: no `clearDraftUi`, back to the
  writing view with the text, the message under the buttons (#431's
  `showInterimError`), the voice segments it was sending put back so the
  next submit still carries them. On `saved: true`: unchanged.

## Tests

- Jest: `apiFetch` error has `status` + `body`; `submitFailure` for a
  saved 422, a saved 500, an unsaved 429 (HTML body), an unsaved 422, a
  network error, and a saved flag that is anything but `true`.
- Playwright (pages.spec.js, #464 block, both projects): Finish & analyze
  with the POST stubbed 429 (no body) — writing view, text kept, the
  message, the draft still holds the text after a flush; stubbed 422
  `{saved: true}` — the error screen with the history line (the quiet
  case).

## Not in this ship

Nothing new found.
