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
    var goalsBtn = document.getElementById("importGoalsBtn");

    // DOM refs — tasks input
    var tasksInput = document.getElementById("importTasksInput");
    var textArea = document.getElementById("importText");
    var parseTasksBtn = document.getElementById("importParseTasksBtn");
    var backFromTasks = document.getElementById("importBackFromTasks");
    var tasksStatus = document.getElementById("importTasksStatus");

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

    // --- Section management --------------------------------------------------

    function showSection(section) {
        modesSection.style.display = "none";
        tasksInput.style.display = "none";
        goalsInput.style.display = "none";
        reviewSection.style.display = "none";
        confirmSection.style.display = "none";
        doneSection.style.display = "none";
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
        parseGoalsBtn.disabled = true;
        tasksStatus.style.display = "none";
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

    goalsBtn.addEventListener("click", function () {
        currentMode = "goals";
        showSection(goalsInput);
    });

    backFromTasks.addEventListener("click", resetAll);
    backFromGoals.addEventListener("click", resetAll);

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
            var resp = await fetch("/api/import/tasks/parse", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: text }),
            });
            var data = await resp.json();

            if (!resp.ok) {
                setStatus(tasksStatus, "Error: " + (data.error || "Parse failed"), true);
                parseTasksBtn.disabled = false;
                return;
            }

            if (data.candidates && data.candidates.length > 0) {
                currentCandidates = data.candidates;
                reviewTitle.textContent = "Review Task Candidates";
                reviewDesc.textContent =
                    data.total + " task(s) found. Edit, include, or exclude before importing.";
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
            var resp = await fetch("/api/import/goals/parse", {
                method: "POST",
                body: formData,
            });
            var data = await resp.json();

            if (!resp.ok) {
                setStatus(goalsStatus, "Error: " + (data.error || "Parse failed"), true);
                parseGoalsBtn.disabled = false;
                return;
            }

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
        } catch (err) {
            setStatus(goalsStatus, "Parse failed: " + err.message, true);
            parseGoalsBtn.disabled = false;
        }
    });

    // --- Render candidates ---------------------------------------------------

    function renderTaskCandidates() {
        candidatesEl.innerHTML = "";
        currentCandidates.forEach(function (c, i) {
            var row = document.createElement("div");
            row.className = "import-candidate" + (c.duplicate ? " import-duplicate" : "");

            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = c.included !== false && !c.duplicate;
            cb.dataset.index = i;
            cb.addEventListener("change", function () {
                currentCandidates[i].included = cb.checked;
            });
            if (c.duplicate) currentCandidates[i].included = false;
            row.appendChild(cb);

            var input = document.createElement("input");
            input.type = "text";
            input.value = c.title;
            input.className = "import-candidate-title";
            input.addEventListener("input", function () {
                currentCandidates[i].title = input.value;
            });
            row.appendChild(input);

            var typeSelect = document.createElement("select");
            typeSelect.className = "import-candidate-type";
            var workOpt = document.createElement("option");
            workOpt.value = "work";
            workOpt.textContent = "Work";
            var persOpt = document.createElement("option");
            persOpt.value = "personal";
            persOpt.textContent = "Personal";
            typeSelect.appendChild(workOpt);
            typeSelect.appendChild(persOpt);
            typeSelect.value = c.type || "work";
            typeSelect.addEventListener("change", function () {
                currentCandidates[i].type = typeSelect.value;
            });
            row.appendChild(typeSelect);

            if (c.duplicate) {
                var badge = document.createElement("span");
                badge.className = "import-dup-badge";
                badge.textContent = "duplicate";
                row.appendChild(badge);
            }

            candidatesEl.appendChild(row);
        });
    }

    function renderGoalCandidates() {
        candidatesEl.innerHTML = "";
        currentCandidates.forEach(function (c, i) {
            var row = document.createElement("div");
            row.className = "import-candidate" + (c.duplicate ? " import-duplicate" : "");

            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = c.included !== false && !c.duplicate;
            cb.dataset.index = i;
            cb.addEventListener("change", function () {
                currentCandidates[i].included = cb.checked;
            });
            if (c.duplicate) currentCandidates[i].included = false;
            row.appendChild(cb);

            var input = document.createElement("input");
            input.type = "text";
            input.value = c.title;
            input.className = "import-candidate-title";
            input.addEventListener("input", function () {
                currentCandidates[i].title = input.value;
            });
            row.appendChild(input);

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
            row.appendChild(catSelect);

            if (c.duplicate) {
                var badge = document.createElement("span");
                badge.className = "import-dup-badge";
                badge.textContent = "duplicate";
                row.appendChild(badge);
            }

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
                return (c.title || "").trim().length > 0;
            })
            .map(function (c) {
                var item = { title: c.title, included: true };
                if (currentMode === "tasks") {
                    item.type = c.type || "work";
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

        var noun = currentMode === "tasks" ? "task(s)" : "goal(s)";
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
            var label = c.title;
            if (currentMode === "tasks") {
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

        var url =
            currentMode === "tasks"
                ? "/api/import/tasks/confirm"
                : "/api/import/goals/confirm";

        try {
            var resp = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    candidates: pendingImport,
                    source: currentMode + "_import",
                }),
            });
            var data = await resp.json();

            if (resp.ok) {
                var noun = currentMode === "tasks" ? "task(s)" : "goal(s)";
                doneMessage.textContent =
                    data.created + " " + noun + " imported successfully.";
                showSection(doneSection);
            } else {
                alert("Error: " + (data.error || "Confirm failed"));
            }
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
