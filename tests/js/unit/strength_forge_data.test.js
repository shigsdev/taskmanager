/**
 * #290: Strength Forge plan-data referential integrity.
 *
 * Regression guard for the bug where a cool-down stretch item reused
 * another exercise's `id` as a placeholder (e.g. "90/90 Hip Stretch"
 * carried id "glute-bridge"), so the ℹ️ detail modal — which looks up
 * SF.exercises[item.id] — showed the WRONG exercise's title, how-to,
 * and diagram.
 *
 * strength_forge_data.js is a browser IIFE that assigns window.SFData
 * (no Node export by design — it's pure reference data, not logic). We
 * load it under a window shim via `vm` so these invariants run in Jest.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function loadSFData() {
  const code = fs.readFileSync(
    path.join(__dirname, "..", "..", "..", "static", "strength_forge_data.js"),
    "utf8"
  );
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox.window.SFData;
}

const SF = loadSFData();
// #317: the six #315 isolation plans were missing here, so the referential
// integrity invariants below never ran against them. Added.
const PLAN_KEYS = [
  "bandPlanA", "bandPlanB", "milS1", "milS2", "milS3",
  "isoChest", "isoBack", "isoShoulders", "isoBiceps", "isoTriceps", "isoLegs",
];

function allItems() {
  const items = [];
  PLAN_KEYS.forEach((key) => {
    (SF[key] || []).forEach((section) => {
      (section.items || []).forEach((item) => {
        items.push({ plan: key, item });
      });
    });
  });
  return items;
}

describe("SFData plan referential integrity", () => {
  test("loaded with exercises map and all plan arrays", () => {
    expect(SF).toBeTruthy();
    expect(typeof SF.exercises).toBe("object");
    PLAN_KEYS.forEach((key) => expect(Array.isArray(SF[key])).toBe(true));
  });

  test("every plan item id resolves to an entry in exercises", () => {
    const missing = allItems()
      .filter(({ item }) => !SF.exercises[item.id])
      .map(({ plan, item }) => `${plan}: "${item.name}" -> unknown id "${item.id}"`);
    expect(missing).toEqual([]);
  });

  // The bug class: a stretch item pointing at a non-stretch exercise.
  // A stretch-named item must resolve to a stretch-titled exercise, so
  // the detail modal describes a stretch — not a Glute Bridge / Box
  // Breathing. (Exact name===title is still too strict: qualifier-only
  // variants like "Diamond Push-Up (Knees if Needed)" -> "Diamond Push-Up"
  // legitimately share an entry. The band case is covered separately below
  // — see #317.)
  test("stretch items resolve to a stretch exercise", () => {
    const mismatches = allItems()
      .filter(({ item }) => /stretch/i.test(item.name))
      .filter(({ item }) => !/stretch/i.test((SF.exercises[item.id] || {}).title || ""))
      .map(({ plan, item }) => {
        const t = (SF.exercises[item.id] || {}).title;
        return `${plan}: "${item.name}" -> "${t}" (id "${item.id}")`;
      });
    expect(mismatches).toEqual([]);
  });

  test("the three fixed cool-down stretches resolve to their own details", () => {
    expect(SF.exercises["hip-90-90"].title).toBe("90/90 Hip Stretch");
    expect(SF.exercises["quad-stretch"].title).toBe("Standing Quad Stretch");
    expect(SF.exercises["chest-stretch"].title).toBe("Doorway Chest Stretch");
  });

  // #317 (user-reported 2026-09-07): "Band Glute Bridge" reused the plain
  // "glute-bridge" entry, so its ℹ️ how-to described the BODYWEIGHT bridge
  // and never mentioned the band. Same class as the #290 stretch bug: an
  // item whose NAME promises one thing while the modal describes another.
  // A band-named item must resolve to an entry that actually teaches the
  // banded version — unless the name explicitly says "No Band".
  test("band-named items resolve to a band exercise", () => {
    const mismatches = allItems()
      .filter(({ item }) => /band/i.test(item.name))
      .filter(({ item }) => !/no band/i.test(item.name))
      .filter(({ item }) => {
        const e = SF.exercises[item.id] || {};
        return !/band/i.test(e.title || "") && !/band/i.test(e.desc || "");
      })
      .map(({ plan, item }) => {
        const t = (SF.exercises[item.id] || {}).title;
        return `${plan}: "${item.name}" -> "${t}" (id "${item.id}")`;
      });
    expect(mismatches).toEqual([]);
  });

  test("Band Glute Bridge has its own entry that teaches the band", () => {
    const e = SF.exercises["band-glute-bridge"];
    expect(e).toBeTruthy();
    expect(e.title).toBe("Band Glute Bridge");
    expect(e.resist).toBe(true);
    expect(/band/i.test(e.desc)).toBe(true);
    // and it must be distinct from the bodyweight bridge's how-to
    expect(e.desc).not.toBe(SF.exercises["glute-bridge"].desc);
  });

  test("the plain glute-bridge entry stays bodyweight (No Band warm-ups use it)", () => {
    expect(SF.exercises["glute-bridge"].title).toBe("Glute Bridge");
    expect(SF.exercises["glute-bridge"].resist).toBeUndefined();
  });
});

// #318: the weekly schedule is shared by the on-screen strip AND the print
// sheet, so it has to stay structurally sound for every trainable program.
describe("SFData schedules (#318)", () => {
  const ROLES = ["band", "mil", "iso"];

  test("every trainable program has a schedule", () => {
    expect(typeof SF.schedules).toBe("object");
    ROLES.forEach((r) => expect(Array.isArray(SF.schedules[r].days)).toBe(true));
  });

  test("every schedule has days, and `on` indices point at real days", () => {
    ROLES.forEach((r) => {
      const sc = SF.schedules[r];
      expect(sc.days.length).toBeGreaterThan(0);
      expect(Array.isArray(sc.on)).toBe(true);
      sc.on.forEach((i) => {
        expect(Number.isInteger(i)).toBe(true);
        expect(i).toBeGreaterThanOrEqual(0);
        expect(i).toBeLessThan(sc.days.length);
      });
      expect(new Set(sc.on).size).toBe(sc.on.length); // no dupes
    });
  });

  test("band/military alternate train + rest days", () => {
    ["band", "mil"].forEach((r) => {
      expect(SF.schedules[r].on).toEqual([0, 2, 4]);
      // the non-training slots really are rest/recovery, not workouts
      SF.schedules[r].days.forEach((d, i) => {
        if (!SF.schedules[r].on.includes(i)) {
          expect(/rest|walk|mobility/i.test(d)).toBe(true);
        }
      });
    });
  });

  test("isolation has NO rest slots — all six are sessions", () => {
    const sc = SF.schedules.iso;
    expect(sc.on).toEqual([0, 1, 2, 3, 4, 5]);
    expect(sc.days.every((d) => !/^rest/i.test(d))).toBe(true);
  });

  test("isolation schedule labels line up with its six plans", () => {
    // Guard against the schedule strip drifting from the actual sessions.
    const planTitles = ["isoChest", "isoBack", "isoShoulders",
      "isoBiceps", "isoTriceps", "isoLegs"];
    expect(SF.schedules.iso.days.length).toBe(planTitles.length);
    planTitles.forEach((key, i) => {
      const label = SF.schedules.iso.days[i].toLowerCase();
      expect(key.toLowerCase()).toContain(label.replace(/\s+/g, ""));
    });
  });

  test("each schedule carries a usable note", () => {
    ROLES.forEach((r) => expect(SF.schedules[r].note.length).toBeGreaterThan(10));
  });
});
