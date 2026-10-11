"""Tests for scripts/check_e2e_assertion_shape.py — the #347 lint for
Playwright tests that assert request SHAPE instead of request SUCCESS.

Each fixture is a small spec-file source string; the lint is pure, so
we assert on what ``check_source`` returns.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mod():
    """Load the script without running its __main__ block."""
    spec = importlib.util.spec_from_file_location(
        "check_e2e_assertion_shape",
        ROOT / "scripts" / "check_e2e_assertion_shape.py",
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules["check_e2e_assertion_shape"] = m
    spec.loader.exec_module(m)
    return m


def _rules(mod, src):
    return [rule for rule, _name, _line in mod.check_source(src)]


class TestDragNoDrag:
    def test_drag_name_without_a_drag_is_flagged(self, mod):
        src = '''
test("dragging between days still works", async ({ page }) => {
    await page.locator(".cell").click();
    await expect(page.locator(".task")).toBeVisible();
});
'''
        hits = mod.check_source(src)
        assert hits == [("DRAG-NO-DRAG", "dragging between days still works", 2)]

    def test_inline_drag_event_is_ok(self, mod):
        src = '''
test("drop a task on a day", async ({ page }) => {
    await page.evaluate(() => {
        const dt = new DataTransfer();
        el.dispatchEvent(new DragEvent("drop", { dataTransfer: dt }));
    });
});
'''
        assert _rules(mod, src) == []

    def test_drag_to_is_ok(self, mod):
        src = '''
test("drags a chip onto a goal", async ({ page }) => {
    await chip.dragTo(card);
});
'''
        assert _rules(mod, src) == []

    def test_braced_function_helper_is_ok(self, mod):
        src = '''
async function dragChip(page, from, to) {
    await page.mouse.down();
    await page.mouse.up();
}
test("drag a chip", async ({ page }) => {
    await dragChip(page, a, b);
});
'''
        assert _rules(mod, src) == []

    def test_expression_bodied_arrow_helper_is_ok(self, mod):
        src = '''
    const fire = (page, sel) =>
        page.dispatchEvent(sel, "drop", { dataTransfer: null });
    const other = () => 1;
    test("a drop lands", async ({ page }) => {
        await fire(page, ".zone");
    });
'''
        assert _rules(mod, src) == []

    def test_helper_that_does_not_drag_does_not_count(self, mod):
        src = '''
const clickIt = (page) => page.click(".x");
test("drop a card", async ({ page }) => {
    await clickIt(page);
});
'''
        assert _rules(mod, src) == ["DRAG-NO-DRAG"]

    def test_arrow_body_stops_at_the_next_sibling_comment(self, mod):
        """Regression: the prototype ran ``card``'s body on into the next
        helper's comment ("...a real DataTransfer...") and counted
        ``card`` as a drag helper, so a test that only called it passed."""
        src = '''
    const card = (page, id) =>
        page.locator(`.card[data-id="${id}"]`);

    // Drag via a real DataTransfer.
    const dragIt = (page) =>
        page.evaluate(() => new DragEvent("drop"));

    test("drop onto a card", async ({ page }) => {
        await card(page, 1).click();
    });
'''
        assert mod.drag_helpers(src) == {"dragIt"}
        assert _rules(mod, src) == ["DRAG-NO-DRAG"]

    def test_a_comment_that_mentions_drag_event_is_not_a_drag(self, mod):
        src = '''
test("drag a chip", async ({ page }) => {
    // no DragEvent here, just a click
    await page.click(".chip");
});
'''
        assert _rules(mod, src) == ["DRAG-NO-DRAG"]

    def test_opt_out_comment_is_ok(self, mod):
        src = '''
test("quick-actions drop to their own row", async ({ page }) => {
    // lint-347: layout test, "drop" means wrap to a new row
    await expect(row).toBeVisible();
});
'''
        assert _rules(mod, src) == []

    def test_unrelated_name_is_ignored(self, mod):
        src = '''
test("dropdown opens", async ({ page }) => {
    await page.click("select");
});
'''
        assert _rules(mod, src) == []


class TestRouteNoStatus:
    def test_pass_through_recording_urls_without_status_is_flagged(self, mod):
        src = '''
test("fetch window widens with the grid", async ({ page }) => {
    const seen = [];
    await page.route("**/api/recurring/previews*", (route) => {
        seen.push(route.request().url());
        route.continue();
    });
    expect(seen[0]).toContain("end=");
});
'''
        assert _rules(mod, src) == ["ROUTE-NO-STATUS"]

    def test_wait_for_response_is_ok(self, mod):
        src = '''
test("fetch window widens with the grid", async ({ page }) => {
    await page.route("**/api/x*", (route) => route.continue());
    const resp = await page.waitForResponse((r) => r.url().includes("/api/x"));
    expect(resp.status()).toBe(200);
});
'''
        assert _rules(mod, src) == []

    def test_fulfill_stub_is_ok(self, mod):
        src = '''
test("renders the stubbed previews", async ({ page }) => {
    await page.route("**/api/x*", (route) => {
        expect(route.request().url()).toContain("end=");
        route.fulfill({ status: 200, body: "[]" });
    });
});
'''
        assert _rules(mod, src) == []


class TestRepo:
    def test_current_specs_are_clean(self, mod, monkeypatch, capsys):
        """The live spec files pass — the gate is green on main."""
        monkeypatch.chdir(ROOT)
        assert mod.main([]) == 0
        assert "OK" in capsys.readouterr().out

    def test_main_reports_a_hit_and_exits_1(self, mod, tmp_path, capsys):
        spec = tmp_path / "x.spec.js"
        spec.write_text(
            'test("drag it", async ({ page }) => {\n'
            '    await page.click(".a");\n'
            '});\n',
            encoding="utf-8",
        )
        assert mod.main([str(spec)]) == 1
        out = capsys.readouterr().out
        assert "DRAG-NO-DRAG" in out
        assert "lint-347" in out
