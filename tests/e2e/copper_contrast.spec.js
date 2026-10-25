/**
 * #485: white text on the copper fill measured 3.79:1 (WCAG AA wants
 * 4.5:1) — the primary .btn and every control that copies it. They now
 * carry the dark page colour (--on-fill), 4.97:1 (6.85:1 on the hover
 * copper). Each control is built with the app's own classes and its
 * rendered colours measured; then every copper fill with text on 19 real
 * pages is measured, so a control nobody listed can't stay white.
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
  // #521: finish in-flight transitions on el and its ancestors first, so a
  // read after a hover reports the settled colour, not one mid-fade (same
  // fix as SETTLED_BG in pages.spec.js). finish() throws on an infinite
  // animation; those have no settled state to wait for.
  const settle = (el) => {
    for (let n = el; n; n = n.parentElement) {
      n.getAnimations().forEach((a) => { try { a.finish(); } catch (e) { /* infinite */ } });
    }
    return el;
  };
  const bgOf = (el) => {
    const stack = [];
    for (let n = settle(el); n; n = n.parentElement) {
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
  const text = (el) => ratio(over(parse(getComputedStyle(settle(el)).color), bgOf(el)), bgOf(el));
  // Copper (#b87333) and its hover (#d68b46), solid.
  const COPPER = ["184,115,51", "214,139,70"];
  const isCopper = (el) => {
    const c = parse(getComputedStyle(el).backgroundColor);
    return c[3] >= 1 && COPPER.includes(c.slice(0, 3).join(","));
  };
  const ownText = (el) => Array.from(el.childNodes).some(
    (n) => n.nodeType === 3 && n.textContent.trim());
  window.__contrast = {
    text,
    // Every visible copper fill on the page with its own text, below 4.5:1.
    lowCopper: () => Array.from(document.querySelectorAll("body *"))
      .filter((el) => el.getClientRects().length && isCopper(el))
      .flatMap((el) => [el, ...el.querySelectorAll("*")])
      .filter((el) => ownText(el) && el.getClientRects().length)
      .map((el) => ({ el, r: text(el) }))
      .filter((x) => x.r < 4.5)
      .map((x) => (x.el.id ? "#" + x.el.id : x.el.className || x.el.tagName)
        + " " + x.r.toFixed(2) + " '" + x.el.textContent.trim().slice(0, 30) + "'"),
  };
})();
`;

async function build(page, html) {
    await page.goto("/?nosw=1");
    await page.evaluate(([m, h]) => {
        // eslint-disable-next-line no-eval
        (0, eval)(m);
        const box = document.createElement("div");
        box.id = "contrast485";
        box.style.cssText = "position:fixed;top:120px;left:20px;z-index:9999;width:340px;padding:12px;background:var(--surface)";
        box.innerHTML = h;
        document.body.appendChild(box);
    }, [MEASURE, html]);
}

const text = (page, sel) => page.evaluate((s) => window.__contrast.text(document.querySelector(s)), sel);

test.describe("#485 text on copper", () => {
    test("every copper control's text is readable", async ({ page }) => {
        await build(page, `
            <button class="btn" id="k1">Save</button>
            <span class="inbox-badge" id="k2">3</span>
            <div class="day-cell day-cell-today" id="k3">Mon</div>
            <span class="parent-picker-chip" id="k4">Parent task</span>
            <button class="project-filter-btn active" id="k5">Kitchen</button>
            <button class="goal-filter-btn active" id="k6">Health</button>
            <button class="active" id="projectsBulkToggle">Select</button>
            <button class="bulk-select-toggle active" id="k8">Select</button>
            <button class="review-btn review-btn-freeze" id="k9">Freeze</button>
            <button class="btn-stop" id="k10">Stop</button>
            <button class="voice-candidate-route route-task" id="k11">TASK</button>
            <button class="bulk-pending-chip" id="k12">Tier: Today ✕</button>
            <div class="recurring-toolbar"><button class="btn" id="recurringNew">+ New template</button></div>
            <span class="reflection-op-badge op-update" id="k14">UPDATE</span>
            <div class="swipe-actions" style="position:static;transform:none"><button class="swipe-action-move" id="k15">Move</button></div>`);
        for (const id of ["#k1", "#k2", "#k3", "#k4", "#k5", "#k6", "#projectsBulkToggle", "#k8",
            "#k9", "#k10", "#k11", "#k12", "#recurringNew", "#k14", "#k15"]) {
            expect(await text(page, id), id).toBeGreaterThanOrEqual(4.5);
        }
    });

    test("the update banner and its Reload button are readable", async ({ page }) => {
        await build(page, `<div class="update-banner" id="u1" style="top:auto;bottom:0"><span id="u2">A new version is ready</span><button id="u3">Reload</button></div>`);
        expect(await text(page, "#u2"), "banner text").toBeGreaterThanOrEqual(4.5);
        expect(await text(page, "#u3"), "Reload button").toBeGreaterThanOrEqual(4.5);
    });

    test("hovered copper controls stay readable", async ({ page }) => {
        await build(page, `
            <button class="btn" id="h1">Save</button>
            <button class="reopen-btn" id="h2">Re-open</button>
            <button class="voice-candidate-recur-btn" id="h3">↻ Make recurring</button>
            <div class="recurring-toolbar"><button class="btn" id="recurringNew">+ New template</button></div>
            <button class="bulk-pending-chip" id="h5">Tier: Today ✕</button>`);
        for (const id of ["#h1", "#h2", "#h3", "#recurringNew", "#h5"]) {
            await page.hover(id);
            expect(await text(page, id), `${id} on hover`).toBeGreaterThanOrEqual(4.5);
        }
        // The chip's hover was a light-theme blue; it is copper now.
        await page.hover("#h5");
        const bg = await page.evaluate(() => getComputedStyle(document.getElementById("h5")).backgroundColor);
        expect(bg).toBe("rgb(214, 139, 70)");
    });

    test("red buttons keep white text (the quiet case)", async ({ page }) => {
        await build(page, `
            <button class="btn btn-danger" id="d1">Delete</button>
            <div class="swipe-actions" style="position:static;transform:none"><button class="swipe-action-delete" id="d2">Delete</button></div>`);
        for (const id of ["#d1", "#d2"]) {
            const c = await page.evaluate((s) => getComputedStyle(document.querySelector(s)).color, id);
            expect(c, id).toBe("rgb(255, 255, 255)");
        }
    });

    const PAGES = ["/", "/tier/today", "/completed", "/goals", "/projects",
        "/recurring", "/calendar", "/review", "/settings", "/import", "/scan",
        "/recycle-bin", "/print", "/reflection", "/voice-memo", "/strength-forge",
        "/utilities", "/docs", "/plan"];

    test("no copper fill on any page has text under 4.5:1", async ({ page }) => {
        test.setTimeout(120_000);
        const low = {};
        for (const path of PAGES) {
            await page.goto(path + (path.includes("?") ? "&" : "?") + "nosw=1");
            await page.waitForLoadState("networkidle");
            const found = await page.evaluate((m) => {
                // eslint-disable-next-line no-eval
                (0, eval)(m);
                return window.__contrast.lowCopper();
            }, MEASURE);
            if (found.length) low[path] = found;
        }
        expect(low).toEqual({});
    });
});
