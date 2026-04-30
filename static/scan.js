/**
 * Image scan to tasks — upload, review, confirm flow.
 *
 * How it works:
 * 1. User picks an image file (photo, screenshot, etc.)
 * 2. Image is uploaded to POST /api/scan/upload
 * 3. Server runs OCR (Google Vision) + AI parsing (Claude)
 * 4. Review screen shows parsed task candidates with checkboxes
 * 5. User edits/deselects candidates, then confirms
 * 6. POST /api/scan/confirm creates tasks in Inbox
 */

(function () {
    "use strict";

    const UPLOAD_API = "/api/scan/upload";
    const CONFIRM_API = "/api/scan/confirm";

    // DOM refs
    const uploadSection = document.getElementById("scanUpload");
    const reviewSection = document.getElementById("scanReview");
    const doneSection = document.getElementById("scanDone");

    const fileInput = document.getElementById("scanFile");
    const fileLabel = document.getElementById("scanFileLabel");
    const preview = document.getElementById("scanPreview");
    const previewImg = document.getElementById("scanPreviewImg");
    const submitBtn = document.getElementById("scanSubmitBtn");
    const statusEl = document.getElementById("scanStatus");

    const candidatesEl = document.getElementById("scanCandidates");
    const ocrTextEl = document.getElementById("scanOcrText");
    const confirmAllBtn = document.getElementById("scanConfirmAll");
    const confirmSelectedBtn = document.getElementById("scanConfirmSelected");
    const rescanBtn = document.getElementById("scanRescan");

    const doneMessage = document.getElementById("scanDoneMessage");
    const scanAgainBtn = document.getElementById("scanAgainBtn");

    let currentCandidates = [];
    // Tracks whether the current batch is tasks or goals. Set from the
    // upload response so review/confirm use the same mode the server saw.
    let currentKind = "tasks";

    const GOAL_CATEGORIES = [
        ["health", "Health"],
        ["personal_growth", "Personal Growth"],
        ["relationships", "Relationships"],
        ["work", "Work"],
    ];
    const GOAL_PRIORITIES = [
        ["must", "Must"],
        ["should", "Should"],
        ["could", "Could"],
        ["need_more_info", "Need More Info"],
    ];

    function getSelectedParseAs() {
        var radios = document.getElementsByName("parseAs");
        for (var i = 0; i < radios.length; i++) {
            if (radios[i].checked) return radios[i].value;
        }
        return "tasks";
    }

    // --- Helpers --------------------------------------------------------------

    function showSection(section) {
        uploadSection.style.display = "none";
        reviewSection.style.display = "none";
        doneSection.style.display = "none";
        section.style.display = "";
    }

    function setStatus(msg, isError) {
        statusEl.style.display = "";
        statusEl.textContent = msg;
        statusEl.className = "scan-status" + (isError ? " scan-error" : "");
    }

    function resetUpload() {
        fileInput.value = "";
        preview.style.display = "none";
        submitBtn.disabled = true;
        statusEl.style.display = "none";
        fileLabel.textContent = "Choose image or take photo";
        showSection(uploadSection);
    }

    // --- File selection -------------------------------------------------------

    fileInput.addEventListener("change", function () {
        var file = fileInput.files[0];
        if (!file) return;

        fileLabel.textContent = file.name;
        submitBtn.disabled = false;

        // Show preview
        var reader = new FileReader();
        reader.onload = function (e) {
            previewImg.src = e.target.result;
            preview.style.display = "";
        };
        reader.readAsDataURL(file);
    });

    // Note: no JS click handler on fileLabel — the <label for="scanFile">
    // attribute already opens the file picker natively. Adding a programmatic
    // .click() here caused a double-trigger on iOS Safari that cancelled the
    // camera intent and prevented the change event from firing on return.

    // --- Upload ---------------------------------------------------------------

    submitBtn.addEventListener("click", async function () {
        var file = fileInput.files[0];
        if (!file) return;

        submitBtn.disabled = true;
        setStatus("Scanning image... This may take a few seconds.", false);

        var formData = new FormData();
        formData.append("image", file);
        formData.append("parse_as", getSelectedParseAs());

        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var data = await window.apiFetch(UPLOAD_API, {
                method: "POST",
                body: formData,
            });

            if (data.candidates && data.candidates.length > 0) {
                currentCandidates = data.candidates;
                currentKind =
                    data.kind === "goals" ? "goals"
                    : (data.kind === "projects" ? "projects" : "tasks");
                ocrTextEl.textContent = data.ocr_text || "(no text)";
                renderCandidates();
                showSection(reviewSection);
            } else {
                setStatus(data.message || "No tasks found in image.", true);
                submitBtn.disabled = false;
            }
        } catch (err) {
            setStatus("Upload failed: " + err.message, true);
            submitBtn.disabled = false;
        }
    });

    // --- Review candidates ----------------------------------------------------

    function buildSelect(className, options, value, onChange) {
        var sel = document.createElement("select");
        sel.className = className;
        options.forEach(function (pair) {
            var opt = document.createElement("option");
            opt.value = pair[0];
            opt.textContent = pair[1];
            sel.appendChild(opt);
        });
        sel.value = value;
        sel.addEventListener("change", onChange);
        return sel;
    }

    function renderCandidates() {
        candidatesEl.innerHTML = "";
        currentCandidates.forEach(function (c, i) {
            var row = document.createElement("div");
            row.className =
                "scan-candidate scan-candidate-" + currentKind;

            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = c.included !== false;
            cb.dataset.index = i;
            cb.addEventListener("change", function () {
                currentCandidates[i].included = cb.checked;
            });
            row.appendChild(cb);

            var titleInput = document.createElement("input");
            titleInput.type = "text";
            titleInput.value = c.title;
            titleInput.className = "scan-candidate-title";
            titleInput.addEventListener("input", function () {
                currentCandidates[i].title = titleInput.value;
            });
            row.appendChild(titleInput);

            if (currentKind === "goals") {
                row.appendChild(
                    buildSelect(
                        "scan-candidate-category",
                        GOAL_CATEGORIES,
                        c.category || "personal_growth",
                        function (e) {
                            currentCandidates[i].category = e.target.value;
                        }
                    )
                );
                row.appendChild(
                    buildSelect(
                        "scan-candidate-priority",
                        GOAL_PRIORITIES,
                        c.priority || "need_more_info",
                        function (e) {
                            currentCandidates[i].priority = e.target.value;
                        }
                    )
                );
                var quarter = document.createElement("input");
                quarter.type = "text";
                quarter.className = "scan-candidate-quarter";
                quarter.placeholder = "Target quarter (e.g. Q2 2026)";
                quarter.value = c.target_quarter || "";
                quarter.addEventListener("input", function () {
                    currentCandidates[i].target_quarter = quarter.value;
                });
                row.appendChild(quarter);
            } else if (currentKind === "projects") {
                // #86 (2026-04-26): scan → projects. Type select +
                // optional target_quarter.
                row.appendChild(
                    buildSelect(
                        "scan-candidate-type",
                        [
                            ["work", "Work"],
                            ["personal", "Personal"],
                        ],
                        c.type || "work",
                        function (e) {
                            currentCandidates[i].type = e.target.value;
                        }
                    )
                );
                var pquarter = document.createElement("input");
                pquarter.type = "text";
                pquarter.className = "scan-candidate-quarter";
                pquarter.placeholder = "Target quarter (e.g. 2026-Q4)";
                pquarter.value = c.target_quarter || "";
                pquarter.addEventListener("input", function () {
                    currentCandidates[i].target_quarter = pquarter.value;
                });
                row.appendChild(pquarter);
            } else {
                row.appendChild(
                    buildSelect(
                        "scan-candidate-type",
                        [
                            ["work", "Work"],
                            ["personal", "Personal"],
                        ],
                        c.type || "work",
                        function (e) {
                            currentCandidates[i].type = e.target.value;
                        }
                    )
                );
            }

            candidatesEl.appendChild(row);
        });
    }

    // --- Confirm --------------------------------------------------------------

    async function confirmCandidates(allIncluded) {
        var toSend = currentCandidates.map(function (c) {
            // Projects use `name` instead of `title` per the import_service
            // shape — translate so create_projects_from_import is happy.
            var base = {
                included: allIncluded ? true : c.included,
            };
            if (currentKind === "projects") {
                base.name = c.title;
                base.type = c.type || "work";
                base.target_quarter = c.target_quarter || "";
            } else if (currentKind === "goals") {
                base.title = c.title;
                base.category = c.category || "personal_growth";
                base.priority = c.priority || "need_more_info";
                base.target_quarter = c.target_quarter || "";
                base.actions = c.actions || "";
            } else {
                base.title = c.title;
                base.type = c.type || "work";
            }
            return base;
        });

        try {
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var data = await window.apiFetch(CONFIRM_API, {
                method: "POST",
                body: JSON.stringify({
                    kind: currentKind,
                    candidates: toSend,
                }),
            });
            var label = currentKind === "goals" ? "goal(s)"
                      : (currentKind === "projects" ? "project(s)" : "task(s)");
            var suffix =
                currentKind === "goals" ? " added to your goals."
                : (currentKind === "projects" ? " added to your projects."
                   : " added to your inbox.");
            doneMessage.textContent = data.created + " " + label + suffix;
            showSection(doneSection);
        } catch (err) {
            alert("Confirm failed: " + err.message);
        }
    }

    confirmAllBtn.addEventListener("click", function () {
        confirmCandidates(true);
    });

    confirmSelectedBtn.addEventListener("click", function () {
        confirmCandidates(false);
    });

    rescanBtn.addEventListener("click", resetUpload);
    scanAgainBtn.addEventListener("click", resetUpload);

    // --- Init -----------------------------------------------------------------

    showSection(uploadSection);
})();
