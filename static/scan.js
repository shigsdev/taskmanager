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

    // iPhone photos are typically 3-8 MB and 4032×3024. Uploading them
    // unmodified over cellular regularly causes Safari's fetch() to
    // abort with "Load failed" before the server can respond. Resize
    // on a canvas to a sane max dimension and re-encode as JPEG so the
    // payload is small (usually < 500 KB) and upload is reliable. The
    // 2048px cap is well above Google Vision's useful resolution for
    // OCR on the kind of content this feature handles.
    const MAX_IMAGE_DIMENSION = 2048;
    const COMPRESSED_JPEG_QUALITY = 0.85;

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

    // --- Client-side image compression ---------------------------------------

    /**
     * Downscale and re-encode an image file to JPEG.
     *
     * iPhone camera images are large (3-8 MB, 4032×3024). Uploading them
     * raw over cellular causes Safari to throw "Load failed" before the
     * server can respond. We resize on a canvas to at most
     * MAX_IMAGE_DIMENSION on the long edge and export as JPEG, which
     * typically drops the payload under 500 KB while staying legible
     * enough for Google Vision OCR.
     *
     * Returns a Promise that resolves to a Blob. Rejects if the file
     * can't be decoded as an image (e.g. HEIC on browsers that don't
     * support it natively — uncommon since iOS Safari converts HEIC
     * to JPEG when uploading via <input type="file"> already).
     */
    function compressImage(file) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onerror = function () {
                reject(new Error("Could not read the selected file."));
            };
            reader.onload = function (e) {
                var img = new Image();
                img.onerror = function () {
                    reject(new Error(
                        "Could not decode the image. Try a JPEG or PNG."
                    ));
                };
                img.onload = function () {
                    var w = img.naturalWidth;
                    var h = img.naturalHeight;
                    var longest = Math.max(w, h);
                    if (longest > MAX_IMAGE_DIMENSION) {
                        var scale = MAX_IMAGE_DIMENSION / longest;
                        w = Math.round(w * scale);
                        h = Math.round(h * scale);
                    }
                    var canvas = document.createElement("canvas");
                    canvas.width = w;
                    canvas.height = h;
                    var ctx = canvas.getContext("2d");
                    if (!ctx) {
                        reject(new Error("Canvas not available in this browser."));
                        return;
                    }
                    ctx.drawImage(img, 0, 0, w, h);
                    canvas.toBlob(
                        function (blob) {
                            if (!blob) {
                                reject(new Error("Image compression failed."));
                                return;
                            }
                            resolve(blob);
                        },
                        "image/jpeg",
                        COMPRESSED_JPEG_QUALITY
                    );
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        });
    }

    // --- Upload ---------------------------------------------------------------

    submitBtn.addEventListener("click", async function () {
        var file = fileInput.files[0];
        if (!file) return;

        submitBtn.disabled = true;
        setStatus("Preparing image...", false);

        // Downscale + re-encode before upload. If compression fails
        // (unsupported format, decoder error), fall back to sending the
        // original file so the server-side content-type check can
        // return a proper error.
        var uploadBlob;
        var uploadName;
        try {
            uploadBlob = await compressImage(file);
            uploadName = (file.name || "scan").replace(
                /\.[^.]+$/, ""
            ) + ".jpg";
        } catch (err) {
            uploadBlob = file;
            uploadName = file.name || "scan";
        }

        setStatus("Scanning image... This may take a few seconds.", false);

        var formData = new FormData();
        formData.append("image", uploadBlob, uploadName);
        formData.append("parse_as", getSelectedParseAs());

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
                currentKind = data.kind === "goals" ? "goals" : "tasks";
                ocrTextEl.textContent = data.ocr_text || "(no text)";
                renderCandidates();
                showSection(reviewSection);
            } else {
                setStatus(data.message || "No tasks found in image.", true);
                submitBtn.disabled = false;
            }
        } catch (err) {
            // Safari surfaces every network-layer failure (aborted
            // request, connection dropped, payload too big for the
            // edge proxy) as a TypeError with message "Load failed".
            // Translate that into something actionable — the user
            // can't do anything with "Load failed" but they can retry
            // on a different network or with a smaller image.
            var raw = (err && err.message) || "";
            var friendly;
            if (raw === "Load failed" || err instanceof TypeError) {
                friendly =
                    "Network error while uploading. Check your " +
                    "connection and try again. If it keeps failing, " +
                    "try a smaller image.";
            } else {
                friendly = raw || "Unknown error";
            }
            setStatus("Upload failed: " + friendly, true);
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
            var base = {
                title: c.title,
                included: allIncluded ? true : c.included,
            };
            if (currentKind === "goals") {
                base.category = c.category || "personal_growth";
                base.priority = c.priority || "need_more_info";
                base.target_quarter = c.target_quarter || "";
                base.actions = c.actions || "";
            } else {
                base.type = c.type || "work";
            }
            return base;
        });

        try {
            var resp = await fetch(CONFIRM_API, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    kind: currentKind,
                    candidates: toSend,
                }),
            });
            var data = await resp.json();

            if (resp.ok) {
                var label = currentKind === "goals" ? "goal(s)" : "task(s)";
                var suffix =
                    currentKind === "goals"
                        ? " added to your goals."
                        : " added to your inbox.";
                doneMessage.textContent = data.created + " " + label + suffix;
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
