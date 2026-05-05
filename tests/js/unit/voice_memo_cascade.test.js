/**
 * @jest-environment jsdom
 *
 * Jest test for #137 Sub-PR A — voice memo project→goal cascade.
 *
 * Bug: when the user picked a project in the voice memo review UI
 * dropdown, voice_memo.js wrote project_id onto the candidate but
 * never mirrored the project's goal_id onto the goal select. The
 * task confirmed with project_id set + goal_id null even when the
 * project belonged to a goal — user had to manually re-pick the
 * goal every time.
 *
 * Per CLAUDE.md anti-pattern #3: this exercises the actual cascade
 * path (DOM construction + change-event dispatch + assertion on
 * goalSel.value AND the candidate-state mutation), not just a
 * source-string match. The handler under test is duplicated here
 * verbatim from voice_memo.js:499-518 to keep the test pure-Node
 * (voice_memo.js itself is an IIFE that runs against window/document
 * at load and isn't trivially importable).
 */
"use strict";

// filter_helpers.js dual-exports projectCascadeGoalId for Node + browser.
const filterHelpers = require("../../../static/filter_helpers");

// Mirror voice_memo.js's expectation: window.filterHelpers.projectCascadeGoalId.
beforeAll(() => {
    global.window = global.window || {};
    global.window.filterHelpers = filterHelpers;
});

function buildHandler(idx, projSel, goalSel, currentCandidates, availableProjects) {
    // Verbatim mirror of voice_memo.js cascade handler body.
    // 2026-05-04 UX fix: ALWAYS reset goal context on project change
    // (either to project's goal, or clear when new project has none /
    // user picks "(no project)"). Original "preserve" behaviour left
    // a stale OLD-project goal under a NEW project — user reported.
    return function () {
        currentCandidates[idx].project_id = projSel.value || null;
        const allowedGoalIds = new Set(
            Array.from(goalSel.options).map((o) => o.value)
        );
        const newGoalId = window.filterHelpers.projectCascadeGoalId(
            projSel.value, availableProjects, allowedGoalIds,
        );
        goalSel.value = newGoalId || "";
        currentCandidates[idx].goal_id = newGoalId || null;
    };
}

function setupSelects(projects, goals) {
    document.body.innerHTML = "";
    const projSel = document.createElement("select");
    const noneP = document.createElement("option");
    noneP.value = ""; noneP.textContent = "(no project)";
    projSel.appendChild(noneP);
    projects.forEach((p) => {
        const o = document.createElement("option");
        o.value = p.id; o.textContent = p.name;
        projSel.appendChild(o);
    });

    const goalSel = document.createElement("select");
    const noneG = document.createElement("option");
    noneG.value = ""; noneG.textContent = "(no goal)";
    goalSel.appendChild(noneG);
    goals.forEach((g) => {
        const o = document.createElement("option");
        o.value = g.id; o.textContent = g.title;
        goalSel.appendChild(o);
    });

    document.body.appendChild(projSel);
    document.body.appendChild(goalSel);
    return { projSel, goalSel };
}

describe("#137 Sub-PR A — voice memo project→goal cascade", () => {
    const PROJ_A = "11111111-1111-1111-1111-111111111111";
    const PROJ_B = "22222222-2222-2222-2222-222222222222";
    const GOAL_X = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    const GOAL_Y = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";

    test("picking a project mirrors that project's goal_id onto the goal select AND candidate", () => {
        const projects = [
            { id: PROJ_A, name: "Launch site", goal_id: GOAL_X },
            { id: PROJ_B, name: "Move apt", goal_id: GOAL_Y },
        ];
        const goals = [
            { id: GOAL_X, title: "Q2 launch" },
            { id: GOAL_Y, title: "Relocation" },
        ];
        const candidates = [{ project_id: null, goal_id: null }];
        const { projSel, goalSel } = setupSelects(projects, goals);
        projSel.addEventListener("change",
            buildHandler(0, projSel, goalSel, candidates, projects));

        projSel.value = PROJ_A;
        projSel.dispatchEvent(new Event("change"));

        expect(candidates[0].project_id).toBe(PROJ_A);
        expect(candidates[0].goal_id).toBe(GOAL_X);
        expect(goalSel.value).toBe(GOAL_X);
    });

    test("picking a project with no goal CLEARS the goal selection", () => {
        // 2026-05-04: behaviour changed from "preserve" to "clear". User
        // reported that switching from a project-with-goal to a
        // project-without-goal left the OLD goal showing under the NEW
        // project, which felt like a stale association. New rule:
        // changing project always resets goal context.
        const projects = [{ id: PROJ_A, name: "Solo proj", goal_id: null }];
        const goals = [{ id: GOAL_X, title: "Q2 launch" }];
        const candidates = [{ project_id: null, goal_id: GOAL_X }];
        const { projSel, goalSel } = setupSelects(projects, goals);
        goalSel.value = GOAL_X;
        projSel.addEventListener("change",
            buildHandler(0, projSel, goalSel, candidates, projects));

        projSel.value = PROJ_A;
        projSel.dispatchEvent(new Event("change"));

        expect(candidates[0].project_id).toBe(PROJ_A);
        expect(candidates[0].goal_id).toBeNull();
        expect(goalSel.value).toBe("");
    });

    test("clearing the project to '(no project)' clears project_id AND goal_id", () => {
        // 2026-05-04: behaviour changed. Used to preserve goal when user
        // selected "(no project)"; now mirrors server's project=null →
        // goal=null rule. User can re-pick a goal manually after if
        // they want one without a project.
        const projects = [{ id: PROJ_A, name: "Launch site", goal_id: GOAL_X }];
        const goals = [{ id: GOAL_X, title: "Q2 launch" }];
        const candidates = [{ project_id: PROJ_A, goal_id: GOAL_X }];
        const { projSel, goalSel } = setupSelects(projects, goals);
        projSel.value = PROJ_A;
        goalSel.value = GOAL_X;
        projSel.addEventListener("change",
            buildHandler(0, projSel, goalSel, candidates, projects));

        projSel.value = "";
        projSel.dispatchEvent(new Event("change"));

        expect(candidates[0].project_id).toBeNull();
        expect(candidates[0].goal_id).toBeNull();
        expect(goalSel.value).toBe("");
    });

    test("switching from project-with-goal-X to project-with-goal-Y updates the goal", () => {
        // The user's reported scenario inverse: switching between two
        // projects that BOTH have goals should follow the new project's
        // goal. Already worked under the old rules; tested explicitly
        // here so the reset-on-change rule doesn't accidentally regress
        // this case.
        const projects = [
            { id: PROJ_A, name: "Launch site", goal_id: GOAL_X },
            { id: PROJ_B, name: "Move apt", goal_id: GOAL_Y },
        ];
        const goals = [
            { id: GOAL_X, title: "Q2 launch" },
            { id: GOAL_Y, title: "Relocation" },
        ];
        const candidates = [{ project_id: PROJ_A, goal_id: GOAL_X }];
        const { projSel, goalSel } = setupSelects(projects, goals);
        projSel.value = PROJ_A;
        goalSel.value = GOAL_X;
        projSel.addEventListener("change",
            buildHandler(0, projSel, goalSel, candidates, projects));

        projSel.value = PROJ_B;
        projSel.dispatchEvent(new Event("change"));

        expect(candidates[0].project_id).toBe(PROJ_B);
        expect(candidates[0].goal_id).toBe(GOAL_Y);
        expect(goalSel.value).toBe(GOAL_Y);
    });

    test("project's goal_id not in allowed set (filtered out) → no cascade", () => {
        // Defensive case: the project references a goal that, for whatever
        // reason, isn't an option on the goal select (e.g. archived goal).
        // projectCascadeGoalId returns null, so we don't try to set an
        // invalid goal value.
        const projects = [{ id: PROJ_A, name: "Launch site", goal_id: GOAL_Y }];
        const goals = [{ id: GOAL_X, title: "Q2 launch" }];  // GOAL_Y absent
        const candidates = [{ project_id: null, goal_id: null }];
        const { projSel, goalSel } = setupSelects(projects, goals);
        projSel.addEventListener("change",
            buildHandler(0, projSel, goalSel, candidates, projects));

        projSel.value = PROJ_A;
        projSel.dispatchEvent(new Event("change"));

        expect(candidates[0].project_id).toBe(PROJ_A);
        expect(candidates[0].goal_id).toBeNull();
        expect(goalSel.value).toBe("");
    });
});
