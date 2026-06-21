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
const PLAN_KEYS = ["bandPlanA", "bandPlanB", "milS1", "milS2", "milS3"];

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
  // Breathing. (Exact name===title is too strict: legitimate variants
  // like "Band Glute Bridge" -> "Glute Bridge" must still pass.)
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
});
