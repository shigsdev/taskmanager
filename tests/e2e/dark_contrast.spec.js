/**
 * #451: dark-theme contrast. A selected card was near-white under cream
 * text (1.1:1); white on the sage / amber fills ~2.6:1 (Complete, Keep,
 * Snooze, the import "duplicate" badge); recurring preview cards grey on dark
 * (2.5:1) and white on hover; failed / applied row tints at 0.08 were
 * near-invisible. Each case is built with the app's own classes on a real
 * page, and the rendered colors are measured (WCAG contrast, translucent
 * backgrounds composited over what is behind them).
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
    let out = [19, 17, 16, 1]; // --slate-0 canvas
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
  window.__contrast = {
    text: (el) => ratio(over(parse(getComputedStyle(el).color), bgOf(el)), bgOf(el)),
    tint: (el) => ratio(bgOf(el), bgOf(el.parentElement)),
    bgLum: (el) => lum(bgOf(el)),   // #471
  };
})();
`;

async function build(page, html) {
    await page.goto("/?nosw=1");
    await page.evaluate(([m, h]) => {
        // eslint-disable-next-line no-eval
        (0, eval)(m);
        const box = document.createElement("div");
        box.id = "contrast451";
        box.style.cssText = "position:fixed;top:120px;left:20px;z-index:9999;width:420px;padding:12px;background:var(--surface)";
        box.innerHTML = h;
        document.body.appendChild(box);
    }, [MEASURE, html]);
}

const text = (page, sel) => page.evaluate((s) => window.__contrast.text(document.querySelector(s)), sel);

test.describe("#451 dark-theme contrast", () => {
    test("a selected card's text is readable", async ({ page }) => {
        await build(page, `<div class="task-card bulk-selected"><span class="task-title" id="c1">Selected task</span></div>`);
        expect(await text(page, "#c1")).toBeGreaterThanOrEqual(4.5);
    });

    test("text on the sage / amber fills is readable", async ({ page }) => {
        await build(page, `
            <button class="btn btn-complete" id="b1">Complete</button>
            <button class="review-btn review-btn-keep" id="b2">Keep</button>
            <button class="review-btn review-btn-snooze" id="b3">Snooze</button>
            <span class="import-dup-badge" id="b4">duplicate</span>
            <div class="task-card"><button class="task-complete-btn" id="b5">✓</button></div>`);
        for (const id of ["#b1", "#b2", "#b3", "#b4"]) {
            expect(await text(page, id), id).toBeGreaterThanOrEqual(4.5);
        }
        await page.hover("#b5");
        // #462: the card's ✓ (the old .quick-complete-btn wasn't rendered any more).
        expect(await text(page, "#b5"), "card ✓ on hover").toBeGreaterThanOrEqual(4.5);
    });

    test("recurring preview cards are readable, and stay dark on hover", async ({ page }) => {
        await build(page, `<div class="task-card preview-card" id="p"><span class="task-title" id="pt">Weekly review</span><span class="task-meta" id="pm">repeats weekly</span></div>`);
        expect(await text(page, "#pt")).toBeGreaterThanOrEqual(4.5);
        expect(await text(page, "#pm")).toBeGreaterThanOrEqual(4.5);
        await page.hover("#p");
        expect(await text(page, "#pt"), "title on hover").toBeGreaterThanOrEqual(4.5);
        const hoverBg = await page.evaluate(() => getComputedStyle(document.getElementById("p")).backgroundColor);
        expect(hoverBg, "hover background stays dark").not.toBe("rgb(244, 244, 245)");
    });

    test("failed and applied row tints are visible against their panel", async ({ page }) => {
        await build(page, `
            <div class="plan-row plan-row-failed" id="t1">failed</div>
            <div class="plan-row plan-row-applied" id="t2">applied</div>
            <div class="weekly-focus-plan-row-failed" id="t3">failed</div>
            <div class="reflection-action-row reflection-action-failed" id="t4">failed</div>
            <table><tbody><tr class="auto-categorize-row-failed" id="t5"><td>failed</td></tr></tbody></table>`);
        for (const id of ["#t1", "#t2", "#t3", "#t4", "#t5"]) {
            const r = await page.evaluate((s) => window.__contrast.tint(document.querySelector(s)), id);
            expect(r, `${id} tint vs panel`).toBeGreaterThanOrEqual(1.25);
            expect(await text(page, id), `${id} text`).toBeGreaterThanOrEqual(4.5);
        }
    });
});

test.describe("#471 light backgrounds left from before the dark theme", () => {
    const bgLum = (page, sel) => page.evaluate((s) => window.__contrast.bgLum(document.querySelector(s)), sel);

    test("the /scan error box, parent-task pills and listening 🎤 are dark and readable", async ({ page }) => {
        await build(page, `
            <div class="scan-status scan-error" id="e1">Scan failed: something went wrong</div>
            <span class="badge parent-link-status parent-link-status-archived" id="s1">archived</span>
            <span class="badge parent-link-status parent-link-status-cancelled" id="s2">cancelled</span>
            <span class="badge parent-link-status parent-link-status-deleted" id="s3">deleted</span>
            <button type="button" class="icon-btn voice-btn voice-listening" id="v1">●</button>`);
        for (const id of ["#e1", "#s1", "#s2", "#s3", "#v1"]) {
            expect(await text(page, id), `${id} text`).toBeGreaterThanOrEqual(4.5);
        }
        for (const id of ["#e1", "#s1", "#s2", "#s3"]) {
            expect(await bgLum(page, id), `${id} background is dark`).toBeLessThan(0.1);
        }
        // The panel 🎤 says "listening" the way the capture bar's does.
        const bg = await page.evaluate(() => getComputedStyle(document.getElementById("v1")).backgroundColor);
        expect(bg).toBe("rgb(220, 38, 38)");
    });

    test("a goal's progress track is dark and its fill stands out", async ({ page }) => {
        await build(page, `
            <div class="goal-progress-row"><div class="progress-bar" id="pb"><div class="progress-fill" id="pf" style="width:40%"></div></div></div>
            <div class="goal-progress-row"><div class="progress-bar"><div class="progress-fill complete" id="pc" style="width:100%"></div></div></div>`);
        expect(await bgLum(page, "#pb"), "track is dark").toBeLessThan(0.1);
        for (const id of ["#pf", "#pc"]) {
            const r = await page.evaluate((s) => window.__contrast.tint(document.querySelector(s)), id);
            expect(r, `${id} fill vs track`).toBeGreaterThanOrEqual(3);
        }
    });
});
