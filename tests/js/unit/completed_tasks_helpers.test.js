/**
 * @jest-environment jsdom
 *
 * Jest tests for #375 — real counts and an on-demand Completed section on
 * /projects and /goals.
 *
 * Why on demand: prod has 1,355 completed tasks (821 KB) against 73 active
 * (40 KB), one project with 356 and one goal with 422, so the pages never
 * download completed tasks with the page — a project/goal's own completed
 * tasks load when its Completed section is opened. These assert OUTPUTS:
 * the labels shown, the order and paging of the rows actually rendered,
 * the requests actually made, and what a failed or stale load leaves on
 * screen.
 */
"use strict";

const {
    projectCountLabel,
    completedSummaryLabel,
    sortCompletedNewestFirst,
    completedPage,
    moreButtonLabel,
    completedTasksUrl,
    createCompletedSection,
    COMPLETED_PAGE_SIZE,
} = require("../../../static/completed_tasks_helpers");

describe("projectCountLabel", () => {
    test("reads real active and done counts from the server", () => {
        expect(projectCountLabel({ active: 4, done: 356 })).toBe("4 active · 356 done");
        expect(projectCountLabel({ active: 0, done: 2 })).toBe("0 active · 2 done");
        expect(projectCountLabel({ active: 3, done: 0 })).toBe("3 active · 0 done");
    });

    test("nothing linked at all says so", () => {
        expect(projectCountLabel({ active: 0, done: 0 })).toBe("No tasks linked");
    });

    test("without server counts it falls back to the active count it has — never 'undefined'", () => {
        expect(projectCountLabel(undefined, 3)).toBe("3 active");
        expect(projectCountLabel(null, 0)).toBe("No tasks linked");
        expect(projectCountLabel({}, 2)).toBe("2 active");
    });
});

describe("completedSummaryLabel / moreButtonLabel", () => {
    test("summary carries the count", () => {
        expect(completedSummaryLabel(356)).toBe("Completed (356)");
        expect(completedSummaryLabel(1)).toBe("Completed (1)");
    });

    test("more button says how many it adds and how many are left", () => {
        expect(moreButtonLabel(306, 50)).toBe("Show 50 more (306 left)");
        expect(moreButtonLabel(50, 50)).toBe("Show 50 more");
        expect(moreButtonLabel(7, 50)).toBe("Show 7 more");
    });
});

describe("sortCompletedNewestFirst", () => {
    test("newest updated_at first, without mutating the input", () => {
        const input = [
            { title: "old", updated_at: "2026-01-01T10:00:00" },
            { title: "new", updated_at: "2026-10-09T10:00:00" },
            { title: "mid", updated_at: "2026-05-01T10:00:00+00:00" },
        ];
        const out = sortCompletedNewestFirst(input);
        expect(out.map((t) => t.title)).toEqual(["new", "mid", "old"]);
        expect(input[0].title).toBe("old");
    });

    test("ties break by title so the order is stable; missing dates go last", () => {
        const out = sortCompletedNewestFirst([
            { title: "b", updated_at: "2026-10-09T10:00:00" },
            { title: "none" },
            { title: "a", updated_at: "2026-10-09T10:00:00" },
            { title: "bad", updated_at: "not a date" },
        ]);
        expect(out.map((t) => t.title)).toEqual(["a", "b", "bad", "none"]);
    });
});

describe("completedPage", () => {
    const tasks = Array.from({ length: 120 }, (_, i) => ({ id: String(i) }));

    test("shows the first page and counts what is left", () => {
        const page = completedPage(tasks, 50);
        expect(page.visible).toHaveLength(50);
        expect(page.visible[0].id).toBe("0");
        expect(page.remaining).toBe(70);
    });

    test("past the end shows everything, nothing left", () => {
        expect(completedPage(tasks, 500)).toEqual({ visible: tasks, remaining: 0 });
        expect(completedPage([], 50)).toEqual({ visible: [], remaining: 0 });
    });
});

describe("completedTasksUrl", () => {
    test("asks for one project's or goal's completed tasks only", () => {
        expect(completedTasksUrl("project", "a1")).toBe("/api/tasks?status=archived&project_id=a1");
        expect(completedTasksUrl("goal", "g 2")).toBe("/api/tasks?status=archived&goal_id=g%202");
    });

    test("anything else is a programming error", () => {
        expect(() => completedTasksUrl("tier", "x")).toThrow();
    });
});

describe("createCompletedSection", () => {
    const flush = () => new Promise((r) => setTimeout(r, 0));
    // Like a user click: change `open` and let the DOM fire its own `toggle`
    // (one per change, as a browser does), then let the load settle.
    const setOpen = async (el, open) => { el.open = open; await flush(); };
    const row = (t) => {
        const li = document.createElement("li");
        li.className = "row";
        li.textContent = t.title;
        return li;
    };
    const many = (n) => Array.from({ length: n }, (_, i) => ({
        id: `t${i}`, title: `T${String(i).padStart(3, "0")}`,
        updated_at: `2026-10-${String(1 + (i % 9)).padStart(2, "0")}T00:00:${String(i % 60).padStart(2, "0")}`,
    }));

    test("the list matches the page's rows: <ul> for <li>, <div> for <div>", () => {
        const opts = { doc: document, count: 1, load: jest.fn(), renderRow: row };
        expect(createCompletedSection(opts).element.querySelector(".completed-tasks-list").tagName).toBe("UL");
        expect(createCompletedSection({ ...opts, listTag: "div" }).element
            .querySelector(".completed-tasks-list").tagName).toBe("DIV");
    });

    test("no completed tasks → no section at all", () => {
        expect(createCompletedSection({ doc: document, count: 0, load: jest.fn(), renderRow: row })).toBeNull();
    });

    test("collapsed until opened, and nothing is fetched until then", () => {
        const load = jest.fn(() => Promise.resolve([]));
        const s = createCompletedSection({ doc: document, count: 3, load, renderRow: row });
        expect(s.element.tagName).toBe("DETAILS");
        expect(s.element.open).toBe(false);
        expect(s.element.querySelector("summary").textContent).toBe("Completed (3)");
        expect(load).not.toHaveBeenCalled();
    });

    test("opening loads once, renders newest first, and paging shows more", async () => {
        const tasks = many(120);
        const load = jest.fn(() => Promise.resolve(tasks));
        const s = createCompletedSection({ doc: document, count: 120, load, renderRow: row });
        document.body.appendChild(s.element);
        s.element.open = true;
        await Promise.resolve();
        await flush();
        const rows = () => [...s.element.querySelectorAll("li.row")].map((li) => li.textContent);
        expect(rows()).toHaveLength(COMPLETED_PAGE_SIZE);
        expect(rows()).toEqual(sortCompletedNewestFirst(tasks).slice(0, 50).map((t) => t.title));
        const more = s.element.querySelector("button");
        expect(more.textContent).toBe("Show 50 more (70 left)");
        more.click();
        expect(rows()).toHaveLength(100);
        expect(more.textContent).toBe("Show 20 more");
        more.click();
        expect(rows()).toHaveLength(120);
        expect(more.hidden).toBe(true);

        await setOpen(s.element, false);
        await setOpen(s.element, true);
        expect(load).toHaveBeenCalledTimes(1); // reopening doesn't refetch
    });

    test("a failed load says so and opening again retries", async () => {
        const load = jest.fn()
            .mockImplementationOnce(() => Promise.reject(new Error("500")))
            .mockImplementationOnce(() => Promise.resolve([{ id: "a", title: "Done A" }]));
        const s = createCompletedSection({ doc: document, count: 1, load, renderRow: row });
        await setOpen(s.element, true);
        expect(s.element.textContent).toMatch(/couldn.t load completed tasks/i);
        expect(s.element.querySelectorAll("li.row")).toHaveLength(0);
        await setOpen(s.element, false);
        await setOpen(s.element, true);
        expect(load).toHaveBeenCalledTimes(2);
        expect(s.element.querySelector("li.row").textContent).toBe("Done A");
        expect(s.element.textContent).not.toMatch(/couldn.t load/i);
    });

    test("refresh re-fetches only if it was opened, and a stale reply loses", async () => {
        let resolveFirst;
        const load = jest.fn()
            .mockImplementationOnce(() => new Promise((r) => { resolveFirst = r; }))
            .mockImplementationOnce(() => Promise.resolve([{ id: "new", title: "Fresh" }]));
        const s = createCompletedSection({ doc: document, count: 1, load, renderRow: row });
        s.refresh();
        expect(load).not.toHaveBeenCalled(); // never opened → nothing to refresh

        await setOpen(s.element, true); // load #1, still pending
        expect(s.element.querySelector(".completed-tasks-status").textContent).toBe("Loading…");
        s.refresh(); // load #2 supersedes it
        await flush();
        resolveFirst([{ id: "old", title: "Stale" }]);
        await flush();
        expect([...s.element.querySelectorAll("li.row")].map((li) => li.textContent)).toEqual(["Fresh"]);
    });
});
