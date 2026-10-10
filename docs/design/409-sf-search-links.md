# #409 — Strength Forge search links: clean queries + a YouTube link

User ask (2026-10-10): "check that when we do a search to google the right
ones come up". Decided: fix the Google Images search AND add a YouTube link.

## 1. Surface

- `static/strength_forge_data.js` `googleLink(query)` →
  `https://www.google.com/search?q=<search + " exercise how to form">&tbm=isch`.
  Used once: `static/strength_forge.js` `openModal()` ("See Real Photos —
  Google Images" button). Not on the print sheet.
- Queries: `exercises[id].search` (43 catalog entries) and
  `flarePhases[*].exercises[*].search` (13 flare entries).
- `templates/docs.html:491-495` describes the modal ("See Real Photos" link;
  "inline diagram where one is available").

## 2. Findings

| Problem | Example |
|---|---|
| Suffix doubles words | "glute bridge exercise form **exercise how to form**", "pike push up shoulder **exercise exercise** how to form", "forearm plank proper form exercise how to form", "box breathing technique exercise how to form" |
| Back-unsafe variant dominates | "band rear delt fly" / "tricep kickback" image results are mostly BENT-OVER versions; the catalog descriptions say stand upright / only a slight hinge (L4/L5 · L5/S1) |
| Legacy parameter | `tbm=isch` — Google now redirects it to `udm=2` |
| Live results not inspected | Google served a reCAPTCHA to the automated browser; this ship fixes what the code controls (the query text) |

## 3. This ship

1. **Link building moves to the unit-tested helper**
   (`strength_forge_helpers.js` `exerciseSearchLinks(query)` → `{images,
   video}`): whitespace-collapsed query; Google Images via `udm=2`; YouTube
   `results?search_query=` with a "how to " prefix (not doubled). Empty query
   → `null` (no links rendered). `SFData.googleLink` is removed.
2. **Every query curated** (catalog + flare): the query is now the complete
   search — nothing appended — so no doubled words. Back-safe qualifiers where
   the common variant contradicts the description: rear delt fly and tricep
   kickback get "standing" (+ "upright" for the fly); lat pulldown keeps
   "kneeling"; others name the setup the plan uses (door anchor, seated).
3. **Modal:** two buttons — "🔍 Photos — Google" and "▶ Videos — YouTube",
   both new-tab, `rel="noopener noreferrer"`.
4. **Help copy** (`docs.html`) updated for the two links, and — now that #408
   gave every exercise a diagram — "an inline diagram (faded = start, solid =
   finish)" instead of "where one is available". Fact-check table in the ship
   notes.
5. **Tests:** Jest for the helper (URL shape, encoding, prefix rule, empty);
   Jest data hygiene (every catalog + flare entry has a query; no adjacent
   duplicate words; no "exercise how to form" leftovers; the two back-safe
   qualifiers present); Playwright: open a modal → both hrefs correct, new tab.
6. `CACHE_VERSION` bump (static JS/CSS changed).

## 4. Out of scope

- Per-side logging → #410.
- Any change to exercise instructions or the clinical text.
