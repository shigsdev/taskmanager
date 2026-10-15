/**
 * #450: iOS Safari zooms the page when you focus a field whose text is
 * under 16 px, and in the installed PWA the page stays zoomed. Only the task
 * panel had 16 px; the capture box, search, focus slots and most other
 * fields were 14.4 px. At phone width every typing field — inputs that take
 * text, selects, textareas — must compute to at least 16 px, on every page,
 * including the ones inside closed panels and pop-ups (computed style is
 * there whether or not the field is showing). Desktop keeps its sizes.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const PAGES = [
    "/", "/tier/today", "/completed", "/calendar", "/goals", "/projects",
    "/recurring", "/review", "/settings", "/import", "/scan", "/reflection",
    "/strength-forge", "/recycle-bin", "/voice-memo", "/plan", "/utilities",
    "/docs",
];

// Inputs that never open the keyboard don't trigger the zoom.
const NO_KEYBOARD = ["checkbox", "radio", "range", "file", "color", "button",
    "submit", "reset", "hidden", "image"];

test.describe("#450 no iOS focus zoom", () => {
    for (const path of PAGES) {
        test(`${path}: every typing field is at least 16px at phone width`, async ({ page, viewport }) => {
            test.skip(viewport.width >= 768, "phone-only rule: desktop keeps its sizes");
            await page.goto(`${path}?nosw=1`);
            await page.waitForLoadState("networkidle");
            const small = await page.evaluate((skip) => {
                return [...document.querySelectorAll("input, select, textarea")]
                    .filter((el) => el.tagName !== "INPUT" || !skip.includes((el.type || "").toLowerCase()))
                    .map((el) => ({
                        what: el.tagName.toLowerCase() + (el.id ? "#" + el.id : "")
                            + (el.className && typeof el.className === "string"
                                ? "." + el.className.trim().split(/\s+/).join(".") : ""),
                        px: parseFloat(getComputedStyle(el).fontSize),
                    }))
                    .filter((f) => f.px < 16);
            }, NO_KEYBOARD);
            expect(small, `fields under 16px on ${path}`).toEqual([]);
        });
    }
});
