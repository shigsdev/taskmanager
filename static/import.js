/**
 * Import flow — paste OneNote tasks or upload Excel goals.
 *
 * Two flows share a common review/confirm pattern:
 * 1. OneNote: paste text → POST /api/import/tasks/parse → review → confirm
 * 2. Excel:   upload .xlsx → POST /api/import/goals/parse → review → confirm
 */

(function () {
    "use strict";

    // DOM refs — mode selection
    var modesSection = document.getElementById("importModes");
    var tasksBtn = document.getElementById("importTasksBtn");
    var docxBtn = document.getElementById("importDocxBtn");
    var goalsBtn = document.getElementById("importGoalsBtn");

    // DOM refs — tasks input
    var tasksInput = document.getElementById("importTasksInput");
    var textArea = document.getElementById("importText");
    var parseTasksBtn = document.getElementById("importParseTasksBtn");
    var backFromTasks = document.getElementById("importBackFromTasks");
    var tasksStatus = document.getElementById("importTasksStatus");

    // DOM refs — docx input
    var docxInput = document.getElementById("importDocxInput");
    var docxFileInput = document.getElementById("importDocxFile");
    var docxFileLabel = document.getElementById("importDocxFileLabel");
    var docxFileName = document.getElementById("importDocxFileName");
    var parseDocxBtn = document.getElementById("importParseDocxBtn");
    var backFromDocx = document.getElementById("importBackFromDocx");
    var docxStatus = document.getElementById("importDocxStatus");

    // DOM refs — goals input
    var goalsInput = document.getElementById("importGoalsInput");
    var fileInput = document.getElementById("importFile");
    var fileLabel = document.getElementById("importFileLabel");
    var fileName = document.getElementById("importFileName");
    var parseGoalsBtn = document.getElementById("importParseGoalsBtn");
    var backFromGoals = document.getElementById("importBackFromGoals");
    var goalsStatus = document.getElementById("importGoalsStatus");

    // DOM refs — review
    var reviewSection = document.getElementById("importReview");
    var reviewTitle = document.getElementById("importReviewTitle");
    var reviewDesc = document.getElementById("importReviewDesc");
    var candidatesEl = document.getElementById("importCandidates");
    var confirmAllBtn = document.getElementById("importConfirmAll");
    var confirmSelectedBtn = document.getElementById("importConfirmSelected");
    var startOverBtn = document.getElementById("importStartOver");
    // (#84 2026-04-25) Expand all / Collapse all controls removed — every
    // field is now always visible per row, no toggle needed.

    // DOM refs — confirm summary
    var confirmSection = document.getElementById("importConfirm");
    var confirmDesc = document.getElementById("importConfirmDesc");
    var confirmList = document.getElementById("importConfirmList");
    var finalConfirmBtn = document.getElementById("importFinalConfirm");
    var goBackBtn = document.getElementById("importGoBackBtn");
    var cancelBtn = document.getElementById("importCancelBtn");

    // DOM refs — done
    var doneSection = document.getElementById("importDone");
    var doneMessage = document.getElementById("importDoneMessage");
    var againBtn = document.getElementById("importAgainBtn");

    var currentMode = null; // "tasks" or "goals"
    var currentCandidates = [];

    // #76 (2026-04-25): preview rows now expose all writable fields, so
    // we need the goal + project lists. Loaded once on first review.
    var importGoals = [];
    var importProjects = [];
    var importLookupsLoaded = false;

    async function loadImportLookups() {
        if (importLookupsLoaded) return;
        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var [g, p] = await Promise.all([
                window.apiFetch("/api/goals"),
                window.apiFetch("/api/projects"),
            ]);
            importGoals = Array.isArray(g) ? g : [];
            importProjects = Array.isArray(p) ? p : [];
            importLookupsLoaded = true;
        } catch (err) {
            console.error("Failed to load goals/projects for import editor:", err);
            // Leave lookups empty — dropdowns will still render but only
            // (no goal) / (no project). User can pick later in detail panel.
        }
    }

    // --- Section management --------------------------------------------------

    function showSection(section) {
        modesSection.style.display = "none";
        tasksInput.style.display = "none";
        docxInput.style.display = "none";
        goalsInput.style.display = "none";
        reviewSection.style.display = "none";
        confirmSection.style.display = "none";
        doneSection.style.display = "none";
        // #80: project mode sections.
        var pti = document.getElementById("importProjectsTextInput");
        var pei = document.getElementById("importProjectsExcelInput");
        if (pti) pti.style.display = "none";
        if (pei) pei.style.display = "none";
        // #89: tasks Excel mode section.
        var tei = document.getElementById("importTasksExcelInput");
        if (tei) tei.style.display = "none";
        section.style.display = "";
    }

    function setStatus(el, msg, isError) {
        el.style.display = "";
        el.textContent = msg;
        el.className = "import-status" + (isError ? " import-error" : "");
    }

    function resetAll() {
        textArea.value = "";
        fileInput.value = "";
        fileName.textContent = "";
        docxFileInput.value = "";
        docxFileName.textContent = "";
        parseGoalsBtn.disabled = true;
        parseDocxBtn.disabled = true;
        tasksStatus.style.display = "none";
        docxStatus.style.display = "none";
        goalsStatus.style.display = "none";
        currentCandidates = [];
        currentMode = null;
        showSection(modesSection);
    }

    // --- Mode selection ------------------------------------------------------

    tasksBtn.addEventListener("click", function () {
        currentMode = "tasks";
        showSection(tasksInput);
    });

    docxBtn.addEventListener("click", function () {
        currentMode = "tasks";
        showSection(docxInput);
    });

    goalsBtn.addEventListener("click", function () {
        currentMode = "goals";
        showSection(goalsInput);
    });

    backFromTasks.addEventListener("click", resetAll);
    backFromDocx.addEventListener("click", resetAll);
    backFromGoals.addEventListener("click", resetAll);

    // #89 (2026-04-26): Excel tasks upload — mirrors docx handler.
    var tasksExcelBtn = document.getElementById("importTasksExcelBtn");
    var tasksExcelInput = document.getElementById("importTasksExcelInput");
    var tasksExcelFile = document.getElementById("importTasksExcelFile");
    var tasksExcelFileLabel = document.getElementById("importTasksExcelFileLabel");
    var tasksExcelFileName = document.getElementById("importTasksExcelFileName");
    var parseTasksExcelBtn = document.getElementById("importParseTasksExcelBtn");
    var backFromTasksExcel = document.getElementById("importBackFromTasksExcel");
    var tasksExcelStatus = document.getElementById("importTasksExcelStatus");

    if (tasksExcelBtn) tasksExcelBtn.addEventListener("click", function () {
        currentMode = "tasks";
        showSection(tasksExcelInput);
    });
    if (backFromTasksExcel) backFromTasksExcel.addEventListener("click", resetAll);
    if (tasksExcelFileLabel) tasksExcelFileLabel.addEventListener("click", function () {
        tasksExcelFile.click();
    });
    if (tasksExcelFile) tasksExcelFile.addEventListener("change", function () {
        var file = tasksExcelFile.files[0];
        if (!file) return;
        tasksExcelFileName.textContent = file.name;
        parseTasksExcelBtn.disabled = false;
    });
    if (parseTasksExcelBtn) parseTasksExcelBtn.addEventListener("click", async function () {
        var file = tasksExcelFile.files[0];
        if (!file) return;
        parseTasksExcelBtn.disabled = true;
        setStatus(tasksExcelStatus, "Parsing tasks from Excel…", false);
        var formData = new FormData();
        formData.append("file", file);
        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var data = await window.apiFetch("/api/import/tasks/upload-xlsx", {
                method: "POST", body: formData,
            });
            if (data.candidates && data.candidates.length > 0) {
                currentCandidates = data.candidates;
                reviewTitle.textContent = "Review Task Candidates";
                reviewDesc.textContent = data.total + " task(s) found. Edit any field before importing.";
                await loadImportLookups();
                renderTaskCandidates();
                showSection(reviewSection);
            } else {
                setStatus(tasksExcelStatus, "No tasks found in the Excel file.", true);
                parseTasksExcelBtn.disabled = false;
            }
        } catch (err) {
            setStatus(tasksExcelStatus, "Parse failed: " + err.message, true);
            parseTasksExcelBtn.disabled = false;
        }
    });

    // #80 (2026-04-26): Projects bulk-upload — paste-text + Excel modes.
    var projectsTextBtn = document.getElementById("importProjectsTextBtn");
    var projectsExcelBtn = document.getElementById("importProjectsExcelBtn");
    var projectsTextInput = document.getElementById("importProjectsTextInput");
    var projectsExcelInput = document.getElementById("importProjectsExcelInput");
    var projectsText = document.getElementById("importProjectsText");
    var parseProjectsTextBtn = document.getElementById("importParseProjectsTextBtn");
    var backFromProjectsText = document.getElementById("importBackFromProjectsText");
    var projectsTextStatus = document.getElementById("importProjectsTextStatus");
    var projectsExcelFile = document.getElementById("importProjectsExcelFile");
    var projectsExcelFileLabel = document.getElementById("importProjectsExcelFileLabel");
    var projectsExcelFileName = document.getElementById("importProjectsExcelFileName");
    var parseProjectsExcelBtn = document.getElementById("importParseProjectsExcelBtn");
    var backFromProjectsExcel = document.getElementById("importBackFromProjectsExcel");
    var projectsExcelStatus = document.getElementById("importProjectsExcelStatus");

    if (projectsTextBtn) projectsTextBtn.addEventListener("click", function () {
        currentMode = "projects";
        showSection(projectsTextInput);
    });
    if (projectsExcelBtn) projectsExcelBtn.addEventListener("click", function () {
        currentMode = "projects";
        showSection(projectsExcelInput);
    });
    if (backFromProjectsText) backFromProjectsText.addEventListener("click", resetAll);
    if (backFromProjectsExcel) backFromProjectsExcel.addEventListener("click", resetAll);
    if (projectsExcelFileLabel) projectsExcelFileLabel.addEventListener("click", function () {
        projectsExcelFile.click();
    });
    if (projectsExcelFile) projectsExcelFile.addEventListener("change", function () {
        var file = projectsExcelFile.files[0];
        if (!file) return;
        projectsExcelFileName.textContent = file.name;
        parseProjectsExcelBtn.disabled = false;
    });

    if (parseProjectsTextBtn) parseProjectsTextBtn.addEventListener("click", async function () {
        var text = projectsText.value;
        if (!text.trim()) {
            setStatus(projectsTextStatus, "Paste at least one project name.", true);
            return;
        }
        parseProjectsTextBtn.disabled = true;
        setStatus(projectsTextStatus, "Parsing projects…", false);
        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var data = await window.apiFetch("/api/import/projects/parse", {
                method: "POST",
                body: JSON.stringify({ text: text }),
            });
            if (data.candidates && data.candidates.length > 0) {
                currentCandidates = data.candidates;
                reviewTitle.textContent = "Review Project Candidates";
                reviewDesc.textContent = data.total + " project(s) found. Edit any field before importing.";
                renderProjectCandidates();
                showSection(reviewSection);
            } else {
                setStatus(projectsTextStatus, "No project names parsed.", true);
                parseProjectsTextBtn.disabled = false;
            }
        } catch (err) {
            setStatus(projectsTextStatus, "Parse failed: " + err.message, true);
            parseProjectsTextBtn.disabled = false;
        }
    });

    if (parseProjectsExcelBtn) parseProjectsExcelBtn.addEventListener("click", async function () {
        var file = projectsExcelFile.files[0];
        if (!file) return;
        parseProjectsExcelBtn.disabled = true;
        setStatus(projectsExcelStatus, "Parsing projects from Excel…", false);
        var formData = new FormData();
        formData.append("file", file);
        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var data = await window.apiFetch("/api/import/projects/upload", {
                method: "POST", body: formData,
            });
            if (data.candidates && data.candidates.length > 0) {
                currentCandidates = data.candidates;
                reviewTitle.textContent = "Review Project Candidates";
                reviewDesc.textContent = data.total + " project(s) found. Edit any field before importing.";
                renderProjectCandidates();
                showSection(reviewSection);
            } else {
                setStatus(projectsExcelStatus, "No projects found in the Excel file.", true);
                parseProjectsExcelBtn.disabled = false;
            }
        } catch (err) {
            setStatus(projectsExcelStatus, "Parse failed: " + err.message, true);
            parseProjectsExcelBtn.disabled = false;
        }
    });

    // --- File input ----------------------------------------------------------

    fileInput.addEventListener("change", function () {
        var file = fileInput.files[0];
        if (!file) return;
        fileName.textContent = file.name;
        parseGoalsBtn.disabled = false;
    });

    fileLabel.addEventListener("click", function () {
        fileInput.click();
    });

    // --- Docx file input -----------------------------------------------------

    docxFileInput.addEventListener("change", function () {
        var file = docxFileInput.files[0];
        if (!file) return;
        docxFileName.textContent = file.name;
        parseDocxBtn.disabled = false;
    });

    docxFileLabel.addEventListener("click", function () {
        docxFileInput.click();
    });

    // --- Parse docx ----------------------------------------------------------

    parseDocxBtn.addEventListener("click", async function () {
        var file = docxFileInput.files[0];
        if (!file) return;

        parseDocxBtn.disabled = true;
        setStatus(docxStatus, "Parsing tasks from .docx...", false);

        var formData = new FormData();
        formData.append("file", file);

        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var data = await window.apiFetch("/api/import/tasks/upload", {
                method: "POST",
                body: formData,
            });

            if (data.candidates && data.candidates.length > 0) {
                currentCandidates = data.candidates;
                reviewTitle.textContent = "Review Task Candidates";
                reviewDesc.textContent =
                    data.total + " task(s) found. Edit, include, or exclude before importing.";
                await loadImportLookups();
                renderTaskCandidates();
                showSection(reviewSection);
            } else {
                setStatus(docxStatus, "No tasks found in the .docx file.", true);
                parseDocxBtn.disabled = false;
            }
        } catch (err) {
            setStatus(docxStatus, "Parse failed: " + err.message, true);
            parseDocxBtn.disabled = false;
        }
    });

    // --- Parse tasks ---------------------------------------------------------

    parseTasksBtn.addEventListener("click", async function () {
        var text = textArea.value;
        if (!text.trim()) {
            setStatus(tasksStatus, "Please paste some text first.", true);
            return;
        }

        parseTasksBtn.disabled = true;
        setStatus(tasksStatus, "Parsing tasks...", false);

        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var data = await window.apiFetch("/api/import/tasks/parse", {
                method: "POST",
                body: JSON.stringify({ text: text }),
            });

            if (data.candidates && data.candidates.length > 0) {
                currentCandidates = data.candidates;
                reviewTitle.textContent = "Review Task Candidates";
                reviewDesc.textContent =
                    data.total + " task(s) found. Edit, include, or exclude before importing.";
                await loadImportLookups();
                renderTaskCandidates();
                showSection(reviewSection);
            } else {
                setStatus(tasksStatus, "No tasks found in the pasted text.", true);
                parseTasksBtn.disabled = false;
            }
        } catch (err) {
            setStatus(tasksStatus, "Parse failed: " + err.message, true);
            parseTasksBtn.disabled = false;
        }
    });

    // --- Parse goals ---------------------------------------------------------

    parseGoalsBtn.addEventListener("click", async function () {
        var file = fileInput.files[0];
        if (!file) return;

        parseGoalsBtn.disabled = true;
        setStatus(goalsStatus, "Parsing goals from Excel...", false);

        var formData = new FormData();
        formData.append("file", file);

        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var data = await window.apiFetch("/api/import/goals/parse", {
                method: "POST",
                body: formData,
            });

            if (data.candidates && data.candidates.length > 0) {
                currentCandidates = data.candidates;
                reviewTitle.textContent = "Review Goal Candidates";
                reviewDesc.textContent =
                    data.total + " goal(s) found. Edit, include, or exclude before importing.";
                renderGoalCandidates();
                showSection(reviewSection);
            } else {
                setStatus(goalsStatus, "No goals found in the Excel file.", true);
                parseGoalsBtn.disabled = false;
            }
            // (No need to load goals/projects for the goals-import path —
            // goals don't reference each other or projects.)
        } catch (err) {
            setStatus(goalsStatus, "Parse failed: " + err.message, true);
            parseGoalsBtn.disabled = false;
        }
    });

    // --- Render candidates ---------------------------------------------------

    // Helpers for the expanded editor (#76).
    function _selectFrom(options, valueKey, labelKey, current) {
        var sel = document.createElement("select");
        // Always include a "blank" option for foreign keys.
        var blank = document.createElement("option");
        blank.value = "";
        blank.textContent = "—";
        sel.appendChild(blank);
        options.forEach(function (o) {
            var opt = document.createElement("option");
            opt.value = o[valueKey];
            opt.textContent = o[labelKey];
            sel.appendChild(opt);
        });
        sel.value = current || "";
        return sel;
    }

    function _labeledField(labelText, control) {
        var wrap = document.createElement("label");
        wrap.className = "import-field";
        var span = document.createElement("span");
        span.textContent = labelText;
        wrap.appendChild(span);
        wrap.appendChild(control);
        return wrap;
    }

    function renderTaskCandidates() {
        candidatesEl.innerHTML = "";
        currentCandidates.forEach(function (c, i) {
            var row = document.createElement("div");
            row.className = "import-candidate" + (c.duplicate ? " import-duplicate" : "");

            var head = document.createElement("div");
            head.className = "import-candidate-head";

            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = c.included !== false && !c.duplicate;
            cb.dataset.index = i;
            cb.addEventListener("change", function () {
                currentCandidates[i].included = cb.checked;
            });
            if (c.duplicate) currentCandidates[i].included = false;
            head.appendChild(cb);

            var input = document.createElement("input");
            input.type = "text";
            input.value = c.title;
            input.className = "import-candidate-title";
            input.addEventListener("input", function () {
                currentCandidates[i].title = input.value;
            });
            head.appendChild(input);

            var typeSelect = document.createElement("select");
            typeSelect.className = "import-candidate-type";
            ["work", "personal"].forEach(function (val) {
                var opt = document.createElement("option");
                opt.value = val;
                opt.textContent = val.charAt(0).toUpperCase() + val.slice(1);
                typeSelect.appendChild(opt);
            });
            typeSelect.value = c.type || "work";
            typeSelect.addEventListener("change", function () {
                currentCandidates[i].type = typeSelect.value;
            });
            head.appendChild(typeSelect);

            if (c.duplicate) {
                var badge = document.createElement("span");
                badge.className = "import-dup-badge";
                badge.textContent = "duplicate";
                head.appendChild(badge);
            }

            row.appendChild(head);

            // #84 (2026-04-25): always-visible full editor — no expand toggle.
            var expanded = document.createElement("div");
            expanded.className = "import-candidate-expanded";

            var fieldsRow1 = document.createElement("div");
            fieldsRow1.className = "import-fields-row";

            var tierSel = document.createElement("select");
            ["inbox", "today", "tomorrow", "this_week", "next_week", "backlog", "freezer"].forEach(function (t) {
                var opt = document.createElement("option");
                opt.value = t;
                opt.textContent = t.replace("_", " ");
                tierSel.appendChild(opt);
            });
            tierSel.value = c.tier || "inbox";
            tierSel.addEventListener("change", function () {
                currentCandidates[i].tier = tierSel.value;
            });
            fieldsRow1.appendChild(_labeledField("Tier", tierSel));

            var dueInput = document.createElement("input");
            dueInput.type = "date";
            dueInput.value = c.due_date || "";
            dueInput.addEventListener("input", function () {
                currentCandidates[i].due_date = dueInput.value;
            });
            fieldsRow1.appendChild(_labeledField("Due date", dueInput));

            expanded.appendChild(fieldsRow1);

            var fieldsRow2 = document.createElement("div");
            fieldsRow2.className = "import-fields-row";

            var goalSel = _selectFrom(importGoals, "id", "title", c.goal_id);
            goalSel.addEventListener("change", function () {
                currentCandidates[i].goal_id = goalSel.value;
            });
            fieldsRow2.appendChild(_labeledField("Goal", goalSel));

            var projSel = _selectFrom(importProjects, "id", "name", c.project_id);
            projSel.addEventListener("change", function () {
                currentCandidates[i].project_id = projSel.value;
            });
            fieldsRow2.appendChild(_labeledField("Project", projSel));

            expanded.appendChild(fieldsRow2);

            var urlInput = document.createElement("input");
            urlInput.type = "text";
            urlInput.value = c.url || "";
            urlInput.placeholder = "https://...";
            urlInput.addEventListener("input", function () {
                currentCandidates[i].url = urlInput.value;
            });
            expanded.appendChild(_labeledField("URL", urlInput));

            var notesInput = document.createElement("textarea");
            notesInput.rows = 2;
            notesInput.value = c.notes || "";
            notesInput.placeholder = "Optional notes";
            notesInput.addEventListener("input", function () {
                currentCandidates[i].notes = notesInput.value;
            });
            expanded.appendChild(_labeledField("Notes", notesInput));

            row.appendChild(expanded);

            candidatesEl.appendChild(row);
        });
    }

    function renderGoalCandidates() {
        candidatesEl.innerHTML = "";
        currentCandidates.forEach(function (c, i) {
            var row = document.createElement("div");
            row.className = "import-candidate" + (c.duplicate ? " import-duplicate" : "");

            var head = document.createElement("div");
            head.className = "import-candidate-head";

            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = c.included !== false && !c.duplicate;
            cb.dataset.index = i;
            cb.addEventListener("change", function () {
                currentCandidates[i].included = cb.checked;
            });
            if (c.duplicate) currentCandidates[i].included = false;
            head.appendChild(cb);

            var input = document.createElement("input");
            input.type = "text";
            input.value = c.title;
            input.className = "import-candidate-title";
            input.addEventListener("input", function () {
                currentCandidates[i].title = input.value;
            });
            head.appendChild(input);

            var catSelect = document.createElement("select");
            catSelect.className = "import-candidate-type";
            ["health", "personal_growth", "relationships", "work"].forEach(function (val) {
                var opt = document.createElement("option");
                opt.value = val;
                opt.textContent = val.replace("_", " ").replace(/\b\w/g, function (l) {
                    return l.toUpperCase();
                });
                catSelect.appendChild(opt);
            });
            catSelect.value = c.category || "work";
            catSelect.addEventListener("change", function () {
                currentCandidates[i].category = catSelect.value;
            });
            head.appendChild(catSelect);

            if (c.duplicate) {
                var badge = document.createElement("span");
                badge.className = "import-dup-badge";
                badge.textContent = "duplicate";
                head.appendChild(badge);
            }

            row.appendChild(head);

            // #84 (2026-04-25): always-visible full editor — no expand toggle.
            var expanded = document.createElement("div");
            expanded.className = "import-candidate-expanded";

            var fieldsRow1 = document.createElement("div");
            fieldsRow1.className = "import-fields-row";

            var prioSel = document.createElement("select");
            ["must", "should", "could", "need_more_info"].forEach(function (p) {
                var opt = document.createElement("option");
                opt.value = p;
                opt.textContent = p.replace("_", " ").replace(/\b\w/g, function (l) { return l.toUpperCase(); });
                prioSel.appendChild(opt);
            });
            prioSel.value = c.priority || "should";
            prioSel.addEventListener("change", function () {
                currentCandidates[i].priority = prioSel.value;
            });
            fieldsRow1.appendChild(_labeledField("Priority", prioSel));

            var statusSel = document.createElement("select");
            ["not_started", "in_progress", "done", "on_hold"].forEach(function (s) {
                var opt = document.createElement("option");
                opt.value = s;
                opt.textContent = s.replace("_", " ").replace(/\b\w/g, function (l) { return l.toUpperCase(); });
                statusSel.appendChild(opt);
            });
            statusSel.value = c.status || "not_started";
            statusSel.addEventListener("change", function () {
                currentCandidates[i].status = statusSel.value;
            });
            fieldsRow1.appendChild(_labeledField("Status", statusSel));

            expanded.appendChild(fieldsRow1);

            var tqInput = document.createElement("input");
            tqInput.type = "text";
            tqInput.value = c.target_quarter || "";
            tqInput.placeholder = "e.g. 2026-Q4";
            tqInput.addEventListener("input", function () {
                currentCandidates[i].target_quarter = tqInput.value;
            });
            expanded.appendChild(_labeledField("Target quarter", tqInput));

            var actionsInput = document.createElement("textarea");
            actionsInput.rows = 2;
            actionsInput.value = c.actions || "";
            actionsInput.placeholder = "Concrete next-actions";
            actionsInput.addEventListener("input", function () {
                currentCandidates[i].actions = actionsInput.value;
            });
            expanded.appendChild(_labeledField("Actions", actionsInput));

            var notesInput = document.createElement("textarea");
            notesInput.rows = 2;
            notesInput.value = c.notes || "";
            notesInput.placeholder = "Optional notes";
            notesInput.addEventListener("input", function () {
                currentCandidates[i].notes = notesInput.value;
            });
            expanded.appendChild(_labeledField("Notes", notesInput));

            row.appendChild(expanded);

            candidatesEl.appendChild(row);
        });
    }

    // #80 (2026-04-26): renderer for project candidates. Mirrors the
    // tasks/goals always-expanded layout (#84). Per-row fields:
    // include checkbox, name input, type select, target_quarter,
    // status, color, actions, notes, linked_goal text input (free
    // string matched at create time).
    function renderProjectCandidates() {
        candidatesEl.innerHTML = "";
        currentCandidates.forEach(function (c, i) {
            var row = document.createElement("div");
            row.className = "import-candidate" + (c.duplicate ? " import-duplicate" : "");

            var head = document.createElement("div");
            head.className = "import-candidate-head";

            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = c.included !== false && !c.duplicate;
            cb.addEventListener("change", function () {
                currentCandidates[i].included = cb.checked;
            });
            if (c.duplicate) currentCandidates[i].included = false;
            head.appendChild(cb);

            var input = document.createElement("input");
            input.type = "text";
            input.value = c.name || "";
            input.className = "import-candidate-title";
            input.addEventListener("input", function () {
                currentCandidates[i].name = input.value;
            });
            head.appendChild(input);

            var typeSel = document.createElement("select");
            typeSel.className = "import-candidate-type";
            ["work", "personal"].forEach(function (val) {
                var opt = document.createElement("option");
                opt.value = val;
                opt.textContent = val.charAt(0).toUpperCase() + val.slice(1);
                typeSel.appendChild(opt);
            });
            typeSel.value = c.type || "work";
            typeSel.addEventListener("change", function () {
                currentCandidates[i].type = typeSel.value;
            });
            head.appendChild(typeSel);

            if (c.duplicate) {
                var badge = document.createElement("span");
                badge.className = "import-dup-badge";
                badge.textContent = "duplicate";
                head.appendChild(badge);
            }
            row.appendChild(head);

            var expanded = document.createElement("div");
            expanded.className = "import-candidate-expanded";

            var fieldsRow = document.createElement("div");
            fieldsRow.className = "import-fields-row";

            var tqInput = document.createElement("input");
            tqInput.type = "text";
            tqInput.value = c.target_quarter || "";
            tqInput.placeholder = "e.g. 2026-Q4";
            tqInput.addEventListener("input", function () {
                currentCandidates[i].target_quarter = tqInput.value;
            });
            fieldsRow.appendChild(_labeledField("Target quarter", tqInput));

            var statusSel = document.createElement("select");
            ["not_started", "in_progress", "done", "on_hold"].forEach(function (s) {
                var opt = document.createElement("option");
                opt.value = s;
                opt.textContent = s.replace("_", " ").replace(/\b\w/g, function (l) { return l.toUpperCase(); });
                statusSel.appendChild(opt);
            });
            statusSel.value = c.status || "not_started";
            statusSel.addEventListener("change", function () {
                currentCandidates[i].status = statusSel.value;
            });
            fieldsRow.appendChild(_labeledField("Status", statusSel));

            expanded.appendChild(fieldsRow);

            var linkedGoalInput = document.createElement("input");
            linkedGoalInput.type = "text";
            linkedGoalInput.value = c.linked_goal || "";
            linkedGoalInput.placeholder = "Goal title (case-insensitive match)";
            linkedGoalInput.addEventListener("input", function () {
                currentCandidates[i].linked_goal = linkedGoalInput.value;
            });
            expanded.appendChild(_labeledField("Linked goal (optional)", linkedGoalInput));

            var actionsInput = document.createElement("textarea");
            actionsInput.rows = 2;
            actionsInput.value = c.actions || "";
            actionsInput.placeholder = "Concrete next-actions";
            actionsInput.addEventListener("input", function () {
                currentCandidates[i].actions = actionsInput.value;
            });
            expanded.appendChild(_labeledField("Actions", actionsInput));

            var notesInput = document.createElement("textarea");
            notesInput.rows = 2;
            notesInput.value = c.notes || "";
            notesInput.placeholder = "Background, context, links…";
            notesInput.addEventListener("input", function () {
                currentCandidates[i].notes = notesInput.value;
            });
            expanded.appendChild(_labeledField("Notes", notesInput));

            row.appendChild(expanded);
            candidatesEl.appendChild(row);
        });
    }

    // --- Confirm summary (preview before DB commit) ---------------------------

    var pendingImport = []; // candidates staged for final confirm

    function showConfirmSummary(allIncluded) {
        // Build the list of what will actually be imported
        pendingImport = currentCandidates
            .filter(function (c) {
                return allIncluded ? true : c.included;
            })
            .filter(function (c) {
                // Projects use "name", tasks/goals use "title".
                if (currentMode === "projects") return (c.name || "").trim().length > 0;
                return (c.title || "").trim().length > 0;
            })
            .map(function (c) {
                if (currentMode === "projects") {
                    return {
                        name: c.name,
                        type: c.type || "work",
                        target_quarter: c.target_quarter || "",
                        status: c.status || "not_started",
                        actions: c.actions || "",
                        notes: c.notes || "",
                        linked_goal: c.linked_goal || "",
                        included: true,
                    };
                }
                var item = { title: c.title, included: true };
                if (currentMode === "tasks") {
                    item.type = c.type || "work";
                    // #76: forward all writable fields if the user touched them.
                    item.tier = c.tier || "inbox";
                    item.due_date = c.due_date || "";
                    item.goal_id = c.goal_id || "";
                    item.project_id = c.project_id || "";
                    item.url = c.url || "";
                    item.notes = c.notes || "";
                    // #89: Excel upload may carry free-text linked_goal /
                    // linked_project. Backend resolves them case-insensitively
                    // when goal_id / project_id is empty.
                    if (c.linked_goal) item.linked_goal = c.linked_goal;
                    if (c.linked_project) item.linked_project = c.linked_project;
                } else {
                    item.category = c.category || "work";
                    item.priority = c.priority || "should";
                    item.actions = c.actions || "";
                    item.target_quarter = c.target_quarter || "";
                    item.status = c.status || "not_started";
                    item.notes = c.notes || "";
                }
                return item;
            });

        if (pendingImport.length === 0) {
            alert("Nothing selected to import.");
            return;
        }

        var noun = currentMode === "tasks" ? "task(s)"
                 : (currentMode === "projects" ? "project(s)" : "goal(s)");
        confirmDesc.textContent =
            "You are about to import " +
            pendingImport.length +
            " " +
            noun +
            ". Review the list below, then confirm or go back to edit.";

        // Render the summary list
        confirmList.innerHTML = "";
        pendingImport.forEach(function (c) {
            var li = document.createElement("li");
            var label = currentMode === "projects" ? c.name : c.title;
            if (currentMode === "tasks") {
                label += " (" + (c.type || "work") + ")";
            } else if (currentMode === "projects") {
                label += " (" + (c.type || "work") + ")";
            } else {
                label += " (" + (c.category || "work") + ")";
            }
            li.textContent = label;
            confirmList.appendChild(li);
        });

        showSection(confirmSection);
    }

    async function executeImport() {
        finalConfirmBtn.disabled = true;
        finalConfirmBtn.textContent = "Importing...";

        var url;
        if (currentMode === "tasks") url = "/api/import/tasks/confirm";
        else if (currentMode === "projects") url = "/api/import/projects/confirm";
        else url = "/api/import/goals/confirm";

        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var data = await window.apiFetch(url, {
                method: "POST",
                body: JSON.stringify({
                    candidates: pendingImport,
                    source: currentMode + "_import",
                }),
            });
            var noun = currentMode === "tasks" ? "task(s)"
                     : (currentMode === "projects" ? "project(s)" : "goal(s)");
            doneMessage.textContent =
                data.created + " " + noun + " imported successfully.";
            showSection(doneSection);
        } catch (err) {
            alert("Confirm failed: " + err.message);
        }

        finalConfirmBtn.disabled = false;
        finalConfirmBtn.textContent = "Yes, Import Now";
    }

    confirmAllBtn.addEventListener("click", function () {
        showConfirmSummary(true);
    });

    confirmSelectedBtn.addEventListener("click", function () {
        showConfirmSummary(false);
    });

    finalConfirmBtn.addEventListener("click", executeImport);

    goBackBtn.addEventListener("click", function () {
        showSection(reviewSection);
    });

    cancelBtn.addEventListener("click", resetAll);
    startOverBtn.addEventListener("click", resetAll);
    againBtn.addEventListener("click", resetAll);

    // --- Init ----------------------------------------------------------------

    showSection(modesSection);
})();
