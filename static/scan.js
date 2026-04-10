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

        try {
            var resp = await fetch(UPLOAD_API, {
                method: "POST",
                body: formData,
            });
            var data = await resp.json();

            if (!resp.ok) {
                setStatus("Error: " + (data.error || "Upload failed"), true);
                submitBtn.disabled = false;
                return;
            }

            if (data.candidates && data.candidates.length > 0) {
                currentCandidates = data.candidates;
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

    function renderCandidates() {
        candidatesEl.innerHTML = "";
        currentCandidates.forEach(function (c, i) {
            var row = document.createElement("div");
            row.className = "scan-candidate";

            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = c.included !== false;
            cb.dataset.index = i;
            cb.addEventListener("change", function () {
                currentCandidates[i].included = cb.checked;
            });
            row.appendChild(cb);

            var input = document.createElement("input");
            input.type = "text";
            input.value = c.title;
            input.className = "scan-candidate-title";
            input.addEventListener("input", function () {
                currentCandidates[i].title = input.value;
            });
            row.appendChild(input);

            var typeSelect = document.createElement("select");
            typeSelect.className = "scan-candidate-type";
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

            candidatesEl.appendChild(row);
        });
    }

    // --- Confirm --------------------------------------------------------------

    async function confirmCandidates(allIncluded) {
        var toSend = currentCandidates.map(function (c) {
            return {
                title: c.title,
                type: c.type || "work",
                included: allIncluded ? true : c.included,
            };
        });

        try {
            var resp = await fetch(CONFIRM_API, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ candidates: toSend }),
            });
            var data = await resp.json();

            if (resp.ok) {
                doneMessage.textContent =
                    data.created + " task(s) added to your inbox.";
                showSection(doneSection);
            } else {
                alert("Error: " + (data.error || "Confirm failed"));
            }
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
