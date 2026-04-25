/**
 * Settings page — load service status, stats, import history, digest actions.
 */

(function () {
    "use strict";

    // --- Load stats ----------------------------------------------------------

    fetch("/api/settings/stats")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            document.getElementById("statActiveTasks").textContent = data.active_tasks;
            document.getElementById("statTotalTasks").textContent = data.total_tasks;
            document.getElementById("statGoals").textContent = data.total_goals;
            document.getElementById("statRecurring").textContent = data.recurring_templates;
        });

    // --- Load service status -------------------------------------------------

    var serviceLabels = {
        google_oauth: "Google OAuth",
        google_vision: "Google Vision (OCR)",
        anthropic: "Anthropic Claude (AI)",
        sendgrid: "SendGrid (Email)",
    };

    fetch("/api/settings/status")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var tbody = document.getElementById("settingsServiceBody");
            tbody.innerHTML = "";

            Object.keys(serviceLabels).forEach(function (key) {
                var tr = document.createElement("tr");
                var tdName = document.createElement("td");
                tdName.textContent = serviceLabels[key];
                var tdStatus = document.createElement("td");
                var present = data[key];
                // Bug #48 — was "Configured / Not configured" which
                // misleadingly implied "service works." Reality: this
                // only checks env-var presence. Honest label: "Env var
                // set / Env var not set." Use 'Test send' (SendGrid
                // row) or actually use the feature to verify the
                // service really works end-to-end.
                tdStatus.textContent = present ? "Env var set" : "Env var not set";
                tdStatus.className = present ? "settings-ok" : "settings-warn";
                tr.appendChild(tdName);
                tr.appendChild(tdStatus);

                // For SendGrid specifically — add an inline "Test send"
                // button. Other services (Whisper / Claude / Vision)
                // need real audio / image input to test, so they don't
                // get an inline test button; you exercise them by
                // actually using the feature.
                var tdAction = document.createElement("td");
                if (key === "sendgrid" && present) {
                    tdAction.appendChild(buildSendgridTestButton());
                }
                tr.appendChild(tdAction);

                tbody.appendChild(tr);
            });

            // Digest email info (booleans — never expose actual addresses)
            document.getElementById("settingsDigestTo").textContent =
                data.digest_email ? "Env var set" : "(not set)";
            document.getElementById("settingsDigestFrom").textContent =
                data.digest_from ? "Env var set" : "(not set)";
        });

    /**
     * Build the inline "Test send" button + result chip for the SendGrid
     * row. Hits POST /api/digest/send (same endpoint as "Send digest now"
     * below — it IS the test). Shows result inline next to the button:
     * green "✓ sent" or red "✗ <real error from #50 global handler>".
     * No alert popup; the row itself becomes the answer.
     */
    function buildSendgridTestButton() {
        var wrap = document.createElement("span");
        wrap.className = "sendgrid-test-wrap";

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-sm";
        btn.textContent = "Test send";
        btn.title = "Send the daily digest now to verify end-to-end delivery";

        var result = document.createElement("span");
        result.className = "sendgrid-test-result";

        btn.addEventListener("click", async function () {
            if (!confirm("Send the daily digest now as a live test?")) return;
            btn.disabled = true;
            btn.textContent = "Sending…";
            result.textContent = "";
            result.className = "sendgrid-test-result";
            try {
                var resp = await fetch("/api/digest/send", { method: "POST" });
                var data = await resp.json();
                if (resp.ok) {
                    result.textContent = "✓ Sent";
                    result.classList.add("settings-ok");
                } else {
                    // #50: error message is now meaningful
                    // (e.g. "SendGrid returned HTTP 403: ...")
                    result.textContent = "✗ " + (data.error || "Send failed");
                    result.title = data.request_id
                        ? "request_id: " + data.request_id
                        : "";
                    result.classList.add("settings-warn");
                }
            } catch (err) {
                result.textContent = "✗ " + (err.message || "Network error");
                result.classList.add("settings-warn");
            }
            btn.disabled = false;
            btn.textContent = "Test send";
        });

        wrap.appendChild(btn);
        wrap.appendChild(result);
        return wrap;
    }

    // --- Load import history + recycle bin count ----------------------------

    function loadImports() {
        fetch("/api/settings/imports")
            .then(function (r) { return r.json(); })
            .then(function (logs) { renderImports(logs); });
    }

    function loadBinCount() {
        fetch("/api/recycle-bin/summary")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var badge = document.getElementById("settingsBinCount");
                if (badge) {
                    var total = (data.task_count || 0) + (data.goal_count || 0);
                    badge.textContent = total;
                }
            });
    }

    function renderImports(logs) {
        var tbody = document.getElementById("settingsImportBody");
        var emptyMsg = document.getElementById("settingsImportEmpty");
        tbody.innerHTML = "";

        if (!logs || logs.length === 0) {
            emptyMsg.style.display = "";
            return;
        }
        emptyMsg.style.display = "none";

        logs.forEach(function (log) {
            var tr = document.createElement("tr");

            var tdSource = document.createElement("td");
            tdSource.textContent = log.source;

            var tdCount = document.createElement("td");
            tdCount.textContent = log.task_count;

            var tdDate = document.createElement("td");
            if (log.imported_at) {
                var d = new Date(log.imported_at);
                tdDate.textContent = d.toLocaleDateString() + " " + d.toLocaleTimeString();
            } else {
                tdDate.textContent = "--";
            }

            var tdActions = document.createElement("td");
            if (!log.batch_id) {
                // Legacy import (pre-recycle-bin) — cannot be undone.
                tdActions.innerHTML = '<span class="settings-muted">—</span>';
            } else if (log.undone_at) {
                // Already in the bin.
                tdActions.innerHTML = '<span class="settings-muted">In Recycle Bin</span>';
            } else {
                var btn = document.createElement("button");
                btn.className = "btn btn-sm";
                btn.textContent = "Undo";
                btn.dataset.batchId = log.batch_id;
                btn.dataset.source = log.source;
                btn.dataset.count = log.task_count;
                btn.addEventListener("click", onUndoClick);
                tdActions.appendChild(btn);
            }

            tr.appendChild(tdSource);
            tr.appendChild(tdCount);
            tr.appendChild(tdDate);
            tr.appendChild(tdActions);
            tbody.appendChild(tr);
        });
    }

    function onUndoClick(e) {
        var btn = e.currentTarget;
        var batchId = btn.dataset.batchId;
        var source = btn.dataset.source;
        var count = btn.dataset.count;
        var confirmMsg = "Move this import to the recycle bin?\n\n" +
            "Source: " + source + "\n" +
            "Items:  " + count + "\n\n" +
            "You can restore it later from the Recycle Bin page.";
        if (!confirm(confirmMsg)) return;

        btn.disabled = true;
        btn.textContent = "Undoing…";

        fetch("/api/recycle-bin/undo/" + batchId, { method: "POST" })
            .then(function (r) {
                return r.json().then(function (body) { return { ok: r.ok, body: body }; });
            })
            .then(function (res) {
                if (!res.ok) {
                    alert("Undo failed: " + (res.body.error || "unknown error"));
                    btn.disabled = false;
                    btn.textContent = "Undo";
                    return;
                }
                // Refresh the history table and the bin count.
                loadImports();
                loadBinCount();
            })
            .catch(function (err) {
                alert("Undo failed: " + err.message);
                btn.disabled = false;
                btn.textContent = "Undo";
            });
    }

    loadImports();
    loadBinCount();

    // --- Digest actions ------------------------------------------------------

    var previewBtn = document.getElementById("settingsDigestPreview");
    var sendBtn = document.getElementById("settingsDigestSend");
    var digestText = document.getElementById("settingsDigestText");

    previewBtn.addEventListener("click", async function () {
        previewBtn.disabled = true;
        previewBtn.textContent = "Loading...";

        try {
            var resp = await fetch("/api/digest/preview");
            var data = await resp.json();

            if (resp.ok) {
                digestText.textContent = data.body;
                digestText.style.display = "";
            } else {
                alert("Error: " + (data.error || "Preview failed"));
            }
        } catch (err) {
            alert("Preview failed: " + err.message);
        }

        previewBtn.disabled = false;
        previewBtn.textContent = "Preview Digest";
    });

    sendBtn.addEventListener("click", async function () {
        if (!confirm("Send the daily digest email now?")) return;

        sendBtn.disabled = true;
        sendBtn.textContent = "Sending...";

        try {
            var resp = await fetch("/api/digest/send", { method: "POST" });
            var data = await resp.json();

            if (resp.ok) {
                alert("Digest sent successfully!");
            } else {
                alert("Error: " + (data.error || "Send failed"));
            }
        } catch (err) {
            alert("Send failed: " + err.message);
        }

        sendBtn.disabled = false;
        sendBtn.textContent = "Send Now";
    });
})();
