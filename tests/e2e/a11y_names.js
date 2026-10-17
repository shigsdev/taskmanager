/**
 * The accessible-name check shared by a11y_gaps.spec.js (#458, every page at
 * load) and review_rows_named.spec.js (#489, the review screens a page only
 * builds after an upload or a parse). Not a spec — Playwright's default
 * testMatch only picks up *.spec.js / *.test.js.
 *
 * `unnamedControls` runs IN THE PAGE (page.evaluate(unnamedControls)): the
 * controls with no accessible name, as {"tag#id.class": count}. A
 * placeholder alone doesn't count: it vanishes once you type and isn't a
 * label.
 */
function unnamedControls() {
    const t = (s) => (s || "").replace(/\s+/g, " ").trim();
    const named = (el) => {
        if (t(el.getAttribute("aria-label"))) return true;
        const lb = el.getAttribute("aria-labelledby");
        if (lb && lb.split(/\s+/).some((id) => t((document.getElementById(id) || {}).textContent))) return true;
        if (el.labels && Array.from(el.labels).some((l) => t(l.textContent))) return true;
        const tag = el.tagName;
        const textual = tag === "BUTTON" || tag === "A" || tag === "SUMMARY"
            || el.getAttribute("role") === "button";
        if (textual && t(el.textContent)) return true;
        const img = el.querySelector("img[alt]");
        if (img && t(img.alt)) return true;
        if (t(el.getAttribute("title"))) return true;
        if (tag === "INPUT" && /^(submit|button)$/.test(el.type) && t(el.value)) return true;
        return false;
    };
    const sel = "input:not([type=hidden]), select, textarea, button, a[href], "
        + "[role=button], [tabindex]:not([tabindex='-1']), summary";
    const out = {};
    for (const el of document.querySelectorAll(sel)) {
        if (named(el)) continue;
        const d = el.tagName.toLowerCase() + (el.id ? "#" + el.id : "")
            + (typeof el.className === "string" && el.className ? "." + el.className.split(" ")[0] : "");
        out[d] = (out[d] || 0) + 1;
    }
    return out;
}

module.exports = { unnamedControls };
