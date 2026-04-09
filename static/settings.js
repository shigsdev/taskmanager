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
                var configured = data[key];
                tdStatus.textContent = configured ? "Configured" : "Not configured";
                tdStatus.className = configured ? "settings-ok" : "settings-warn";
                tr.appendChild(tdName);
                tr.appendChild(tdStatus);
                tbody.appendChild(tr);
            });

            // Digest email info (booleans — never expose actual addresses)
            document.getElementById("settingsDigestTo").textContent =
                data.digest_email ? "Configured" : "(not set)";
            document.getElementById("settingsDigestFrom").textContent =
                data.digest_from ? "Configured" : "(not set)";
        });

    // --- Load import history -------------------------------------------------

    fetch("/api/settings/imports")
        .then(function (r) { return r.json(); })
        .then(function (logs) {
            var tbody = document.getElementById("settingsImportBody");
            var emptyMsg = document.getElementById("settingsImportEmpty");
            tbody.innerHTML = "";

            if (!logs || logs.length === 0) {
                emptyMsg.style.display = "";
                return;
            }

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

                tr.appendChild(tdSource);
                tr.appendChild(tdCount);
                tr.appendChild(tdDate);
                tbody.appendChild(tr);
            });
        });

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
