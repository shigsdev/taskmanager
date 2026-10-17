/**
 * #496: what #451 left on the sage fill (white text, 2.64:1 — WCAG AA wants
 * 4.5:1): the voice memo GOAL route chip, the reflection CREATE badge and
 * the day strip's drag-hover cell; and the voice PROJECT chip was a pink
 * from the light theme (white on #ec4899, 3.53:1). Sage fills now carry the
 * dark page colour (7.12:1) and PROJECT is amber with dark text (7.46:1).
 * Then every sage fill with text on 19 pages is measured, as #485 does for
 * copper.
 */
const { test, expect } = require("./lane"); // #402: per-worker lane server

const MEASURE = `
(() => {
  const parse = (c) => {
    const m = c.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return [0, 0, 0, 0];
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const over = (top, under) => {
    const a = top[3];
    return [0, 1, 2].map((i) => top[i] * a + under[i] * (1 - a)).concat(1);
  };
  const bgOf = (el) => {
    const stack = [];
    for (let n = el; n; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c[3] > 0) stack.push(c);
      if (c[3] >= 1) break;
    }
    let out = [19, 17, 16, 1];
    for (let i = stack.length - 1; i >= 0; i--) out = over(stack[i], out);
    return out;
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  const text = (el) => ratio(over(parse(getComputedStyle(el).color), bgOf(el)), bgOf(el));
  const SAGE = "148,164,139";
  const isSage = (el) => {
    const c = parse(getComputedStyle(el).backgroundColor);
    return c[3] >= 1 && c.slice(0, 3).join(",") === SAGE;
  };
  const ownText = (el) => Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim());
  window.__contrast = {
    text,
    lowSage: () => Array.from(document.querySelectorAll("body *"))
      .filter((el) => el.getClientRects().length && isSage(el))
      .flatMap((el) => [el, ...el.querySelectorAll("*")])
      .filter((el) => ownText(el) && el.getClientRects().length)
      .map((el) => ({ el, r: text(el) }))
      .filter((x) => x.r < 4.5)
      .map((x) => (x.el.className || x.el.tagName) + " " + x.r.toFixed(2)),
  };
})();
`;

async function build(page, html) {
    await page.goto("/?nosw=1");
    await page.evaluate(([m, h]) => {
        // eslint-disable-next-line no-eval
        (0, eval)(m);
        const box = document.createElement("div");
        box.style.cssText = "position:fixed;top:120px;left:20px;z-index:9999;width:340px;padding:12px;background:var(--surface)";
        box.innerHTML = h;
        document.body.appendChild(box);
    }, [MEASURE, html]);
}

const text = (page, sel) => page.evaluate((s) => window.__contrast.text(document.querySelector(s)), sel);

test.describe("#496 text on sage and the voice route chips", () => {
    test("the sage fills and the PROJECT chip are readable", async ({ page }) => {
        await build(page, `
            <button class="voice-candidate-route route-goal" id="s1">GOAL</button>
            <button class="voice-candidate-route route-project" id="s2">PROJECT</button>
            <button class="voice-candidate-route route-task" id="s3">TASK</button>
            <span class="reflection-op-badge op-create" id="s4">CREATE</span>
            <div class="day-cell day-cell-hover" id="s5">Mon</div>`);
        for (const id of ["#s1", "#s2", "#s3", "#s4", "#s5"]) {
            expect(await text(page, id), id).toBeGreaterThanOrEqual(4.5);
        }
        // PROJECT is no longer the light theme's pink.
        const bg = await page.evaluate(() => getComputedStyle(document.getElementById("s2")).backgroundColor);
        expect(bg).not.toBe("rgb(236, 72, 153)");
    });

    test("red fills keep white text (the quiet case)", async ({ page }) => {
        await build(page, `<span class="reflection-op-badge op-delete" id="d1">DELETE</span>`);
        const c = await page.evaluate(() => getComputedStyle(document.getElementById("d1")).color);
        expect(c).toBe("rgb(255, 255, 255)");
        expect(await text(page, "#d1")).toBeGreaterThanOrEqual(4.5);
    });

    const PAGES = ["/", "/tier/today", "/completed", "/goals", "/projects",
        "/recurring", "/calendar", "/review", "/settings", "/import", "/scan",
        "/recycle-bin", "/print", "/reflection", "/voice-memo", "/strength-forge",
        "/utilities", "/docs", "/plan"];

    test("no sage fill on any page has text under 4.5:1", async ({ page }) => {
        test.setTimeout(120_000);
        const low = {};
        for (const path of PAGES) {
            await page.goto(path + "?nosw=1");
            await page.waitForLoadState("networkidle");
            const found = await page.evaluate((m) => {
                // eslint-disable-next-line no-eval
                (0, eval)(m);
                return window.__contrast.lowSage();
            }, MEASURE);
            if (found.length) low[path] = found;
        }
        expect(low).toEqual({});
    });
});
