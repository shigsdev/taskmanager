/**
 * Jest unit tests for static/filter_helpers.js — closes audit C3 + C7.
 *
 * The helpers are loaded by both the browser (via <script>) and Node
 * (via require). Same source file = same logic both places, so these
 * tests guard the actual code that runs in production.
 */
const {
    FILTER_UUID_RE,
    isValidUuid,
    parseUuidCsv,
    serializeUuidSet,
    sweepStaleIds,
    filterProjectsByType,
    applyFilters,
} = require("../../../static/filter_helpers");

describe("FILTER_UUID_RE", () => {
    test("matches a real UUID v4", () => {
        expect(FILTER_UUID_RE.test("c0468ac3-5995-45a2-b80e-0b52ca82f685")).toBe(true);
    });
    test("rejects garbage", () => {
        expect(FILTER_UUID_RE.test("../etc/passwd")).toBe(false);
        expect(FILTER_UUID_RE.test("")).toBe(false);
        expect(FILTER_UUID_RE.test("not-a-uuid")).toBe(false);
    });
    test("rejects almost-UUID with bad length", () => {
        expect(FILTER_UUID_RE.test("c0468ac3-5995-45a2-b80e-0b52ca82f68")).toBe(false);
    });
});

describe("isValidUuid", () => {
    test("non-string returns false", () => {
        expect(isValidUuid(null)).toBe(false);
        expect(isValidUuid(undefined)).toBe(false);
        expect(isValidUuid(42)).toBe(false);
        expect(isValidUuid({})).toBe(false);
    });
    test("valid UUID returns true", () => {
        expect(isValidUuid("c0468ac3-5995-45a2-b80e-0b52ca82f685")).toBe(true);
    });
});

describe("parseUuidCsv (audit C7 — multi-select state persistence)", () => {
    test("empty/null/undefined → empty Set", () => {
        expect(parseUuidCsv("").size).toBe(0);
        expect(parseUuidCsv(null).size).toBe(0);
        expect(parseUuidCsv(undefined).size).toBe(0);
    });
    test("single UUID → Set of 1", () => {
        const s = parseUuidCsv("c0468ac3-5995-45a2-b80e-0b52ca82f685");
        expect(s.size).toBe(1);
        expect(s.has("c0468ac3-5995-45a2-b80e-0b52ca82f685")).toBe(true);
    });
    test("two UUIDs comma-joined → Set of 2", () => {
        const a = "c0468ac3-5995-45a2-b80e-0b52ca82f685";
        const b = "49e16ca4-2453-48d4-8a8a-5bb27774aed7";
        const s = parseUuidCsv(`${a},${b}`);
        expect(s.size).toBe(2);
        expect(s.has(a)).toBe(true);
        expect(s.has(b)).toBe(true);
    });
    test("dedupes when the same id appears twice", () => {
        const a = "c0468ac3-5995-45a2-b80e-0b52ca82f685";
        const s = parseUuidCsv(`${a},${a}`);
        expect(s.size).toBe(1);
    });
    test("strips whitespace + drops invalid entries silently", () => {
        const a = "c0468ac3-5995-45a2-b80e-0b52ca82f685";
        // PR28 fix #5: tampered LS values must not flow through
        const s = parseUuidCsv(`  ${a}  ,not-a-uuid,,${a}`);
        expect(s.size).toBe(1);
        expect(s.has(a)).toBe(true);
    });
});

describe("serializeUuidSet (round-trips with parseUuidCsv)", () => {
    test("empty Set → empty string", () => {
        expect(serializeUuidSet(new Set())).toBe("");
        expect(serializeUuidSet(null)).toBe("");
    });
    test("Set of 2 → comma-joined string parseable back", () => {
        const a = "c0468ac3-5995-45a2-b80e-0b52ca82f685";
        const b = "49e16ca4-2453-48d4-8a8a-5bb27774aed7";
        const orig = new Set([a, b]);
        const csv = serializeUuidSet(orig);
        expect(csv).toContain(",");
        const round = parseUuidCsv(csv);
        expect(round.size).toBe(2);
        expect(round.has(a)).toBe(true);
        expect(round.has(b)).toBe(true);
    });
});

describe("sweepStaleIds (PR36 BUG-2 — strip dead UUIDs after fetch)", () => {
    test("returns false + leaves Set alone when nothing is stale", () => {
        const a = "c0468ac3-5995-45a2-b80e-0b52ca82f685";
        const set = new Set([a]);
        const dirty = sweepStaleIds(set, [{ id: a }, { id: "other" }]);
        expect(dirty).toBe(false);
        expect(set.size).toBe(1);
    });
    test("removes ids not in the live list and reports dirty", () => {
        const a = "c0468ac3-5995-45a2-b80e-0b52ca82f685";
        const stale = "49e16ca4-2453-48d4-8a8a-5bb27774aed7";
        const set = new Set([a, stale]);
        const dirty = sweepStaleIds(set, [{ id: a }]);
        expect(dirty).toBe(true);
        expect(set.has(a)).toBe(true);
        expect(set.has(stale)).toBe(false);
    });
    test("empty filter Set → no-op (no dirty flag)", () => {
        const set = new Set();
        const dirty = sweepStaleIds(set, [{ id: "x" }]);
        expect(dirty).toBe(false);
        expect(set.size).toBe(0);
    });
    test("empty live list → no-op (don't blow away state on a transient fetch failure)", () => {
        const a = "c0468ac3-5995-45a2-b80e-0b52ca82f685";
        const set = new Set([a]);
        const dirty = sweepStaleIds(set, []);
        expect(dirty).toBe(false);
        expect(set.has(a)).toBe(true);
    });
});

describe("filterProjectsByType (audit C3 — project dropdown scoping #98)", () => {
    const projects = [
        { id: "1", name: "Roadmap", type: "work" },
        { id: "2", name: "Garden", type: "personal" },
        { id: "3", name: "OKRs", type: "work" },
        { id: "4", name: "Reading", type: "personal" },
    ];
    test("currentView=all → all projects", () => {
        const out = filterProjectsByType(projects, "all");
        expect(out.length).toBe(4);
    });
    test("currentView=work → only work projects", () => {
        const out = filterProjectsByType(projects, "work");
        expect(out.length).toBe(2);
        expect(out.every((p) => p.type === "work")).toBe(true);
    });
    test("currentView=personal → only personal projects", () => {
        const out = filterProjectsByType(projects, "personal");
        expect(out.length).toBe(2);
        expect(out.every((p) => p.type === "personal")).toBe(true);
    });
    test("returns a copy, not the same reference", () => {
        const out = filterProjectsByType(projects, "all");
        expect(out).not.toBe(projects);
    });
    test("non-array input → empty array (defensive)", () => {
        expect(filterProjectsByType(null, "all")).toEqual([]);
        expect(filterProjectsByType(undefined, "work")).toEqual([]);
    });
});

describe("applyFilters (#92 + #97 composed semantics)", () => {
    const tasks = [
        { id: "t1", type: "work", project_id: "p1", goal_id: "g1" },
        { id: "t2", type: "work", project_id: "p2", goal_id: "g2" },
        { id: "t3", type: "personal", project_id: "p3", goal_id: "g1" },
        { id: "t4", type: "work", project_id: null, goal_id: null },
    ];
    test("no filters → all tasks", () => {
        const out = applyFilters(tasks, "all", new Set(), new Set());
        expect(out.length).toBe(4);
    });
    test("type=work → 3 work tasks", () => {
        const out = applyFilters(tasks, "work", new Set(), new Set());
        expect(out.length).toBe(3);
        expect(out.every((t) => t.type === "work")).toBe(true);
    });
    test("project filter (single) narrows to 1", () => {
        const out = applyFilters(tasks, "all", new Set(["p1"]), new Set());
        expect(out.length).toBe(1);
        expect(out[0].id).toBe("t1");
    });
    test("project filter (multi-select) ORs within dimension", () => {
        // C7: multi-select must include tasks matching ANY chosen project
        const out = applyFilters(tasks, "all", new Set(["p1", "p3"]), new Set());
        expect(out.length).toBe(2);
        const ids = out.map((t) => t.id).sort();
        expect(ids).toEqual(["t1", "t3"]);
    });
    test("goal filter (multi-select) ORs within dimension", () => {
        const out = applyFilters(tasks, "all", new Set(), new Set(["g1"]));
        expect(out.length).toBe(2);
        const ids = out.map((t) => t.id).sort();
        expect(ids).toEqual(["t1", "t3"]);
    });
    test("type + project + goal all compose with AND", () => {
        // type=work + project=p1 + goal=g1 → only t1
        const out = applyFilters(
            tasks,
            "work",
            new Set(["p1"]),
            new Set(["g1"]),
        );
        expect(out.length).toBe(1);
        expect(out[0].id).toBe("t1");
    });
    test("non-array input → empty array (defensive)", () => {
        expect(applyFilters(null, "all", new Set(), new Set())).toEqual([]);
    });
});
