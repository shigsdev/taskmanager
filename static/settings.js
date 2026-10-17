/**
 * Settings page — load service status, stats, import history, digest actions.
 */

(function () {
    "use strict";

    // #440: a section whose data didn't load says so, with a Retry, in a
    // box at the end of that section — instead of "--", an empty table, or
    // the template's "0".
    function sectionLoadError(sectionId, what, err, retry) {
        var section = document.getElementById(sectionId);
        if (!section || !window.loadErrorHelpers) return;
        var hostId = sectionId + "LoadError";
        var host = document.getElementById(hostId);
        if (!host) {
            host = document.createElement("div");
            host.id = hostId;
            section.appendChild(host);
        }
        window.loadErrorHelpers.showLoadError(host, what, err, retry);
    }

    function sectionClearLoadError(sectionId) {
        var host = document.getElementById(sectionId + "LoadError");
        if (host) host.remove();
    }

    // --- Load stats ----------------------------------------------------------

    function loadStats() {
        // PR67 #132: window.apiFetch (auto-retry + recovery)
        window.apiFetch("/api/settings/stats")
            .then(function (data) {
                sectionClearLoadError("settingsStats");
                document.getElementById("statActiveTasks").textContent = data.active_tasks;
                document.getElementById("statTotalTasks").textContent = data.total_tasks;
                document.getElementById("statGoals").textContent = data.total_goals;
                document.getElementById("statRecurring").textContent = data.recurring_templates;
            })
            .catch(function (err) {
                console.error("settings/stats failed:", err);
                sectionLoadError("settingsStats", "the overview", err, loadStats);
            });
    }
    loadStats();

    // --- Load service status -------------------------------------------------

    var serviceLabels = {
        google_oauth: "Google OAuth",
        google_vision: "Google Vision (OCR)",
        anthropic: "Anthropic Claude (AI)",
        email: "Email (digest)",
    };

    function loadStatus() {
        // PR67 #132: window.apiFetch (auto-retry + recovery)
        window.apiFetch("/api/settings/status")
            .then(function (data) {
                sectionClearLoadError("settingsServices");
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
                    // set / Env var not set." Use 'Test send' (Email
                    // row) or actually use the feature to verify the
                    // service really works end-to-end.
                    tdStatus.textContent = present ? "Env var set" : "Env var not set";
                    tdStatus.className = present ? "settings-ok" : "settings-warn";
                    tr.appendChild(tdName);
                    tr.appendChild(tdStatus);

                    // For the email (SMTP) row specifically — add an inline "Test send"
                    // button. Other services (Whisper / Claude / Vision)
                    // need real audio / image input to test, so they don't
                    // get an inline test button; you exercise them by
                    // actually using the feature.
                    var tdAction = document.createElement("td");
                    if (key === "email" && present) {
                        tdAction.appendChild(buildSmtpTestButton());
                    }
                    tr.appendChild(tdAction);

                    tbody.appendChild(tr);
                });

                // Digest email info (booleans — never expose actual addresses)
                document.getElementById("settingsDigestTo").textContent =
                    data.digest_email ? "Env var set" : "(not set)";
                document.getElementById("settingsDigestFrom").textContent =
                    data.digest_from ? "Env var set" : "(not set)";
            })
            .catch(function (err) {
                console.error("settings/status failed:", err);
                sectionLoadError("settingsServices", "service status", err, loadStatus);
            });
    }
    loadStatus();

    /**
     * Build the inline "Test send" button + result chip for the email
     * (SMTP) row. Hits POST /api/digest/send (same endpoint as "Send digest now"
     * below — it IS the test). Shows result inline next to the button:
     * green "✓ sent" or red "✗ <real error from #50 global handler>".
     * No alert popup; the row itself becomes the answer.
     */
    function buildSmtpTestButton() {
        var wrap = document.createElement("span");
        wrap.className = "smtp-test-wrap";

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-sm";
        btn.textContent = "Test send";
        btn.title = "Send the daily digest now to verify end-to-end delivery";

        var result = document.createElement("span");
        result.className = "smtp-test-result";

        btn.addEventListener("click", async function () {
            if (!confirm("Send the daily digest now as a live test?")) return;
            btn.disabled = true;
            btn.textContent = "Sending…";
            result.textContent = "";
            result.className = "smtp-test-result";
            try {
                // PR67 #132: window.apiFetch (auto-retry + recovery)
                await window.apiFetch("/api/digest/send", { method: "POST" });
                result.textContent = "✓ Sent";
                result.classList.add("settings-ok");
            } catch (err) {
                // #50 + apiFetch: error message is meaningful from
                // the global handler (e.g. "SMTP send failed: ...")
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
        // PR67 #132: window.apiFetch (auto-retry + recovery)
        window.apiFetch("/api/settings/imports")
            .then(function (logs) {
                sectionClearLoadError("settingsImports");
                renderImports(logs);
            })
            .catch(function (err) {
                console.error("loadImports failed:", err);
                sectionLoadError("settingsImports", "import history", err, loadImports);
            });
    }

    function loadBinCount() {
        // PR67 #132: window.apiFetch (auto-retry + recovery)
        window.apiFetch("/api/recycle-bin/summary")
            .then(function (data) {
                var badge = document.getElementById("settingsBinCount");
                if (badge) {
                    // #428: deleted tasks are listed in the bin too.
                    // #478: and undone project imports.
                    var total = (data.task_count || 0) + (data.goal_count || 0) +
                        (data.project_count || 0) + (data.deleted_task_count || 0);
                    badge.textContent = total;
                }
            })
            .catch(function (err) {
                console.error("loadBinCount failed:", err);
                // #440: not the template's placeholder — say it's unknown.
                var badge = document.getElementById("settingsBinCount");
                if (badge) badge.textContent = "?";
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
            // #444: zone-less UTC from the server — read as UTC, not local.
            var d = log.imported_at && window.dateHelpers
                ? window.dateHelpers.parseServerTimestamp(log.imported_at) : null;
            if (d) {
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

    // #369: closing line of the "this will pause…" paragraph, by count (#374).
    var UNDO_PAUSE_TAIL = {
        one: "It resumes if you restore this import from the Recycle Bin.",
        many: "They resume if you restore this import from the Recycle Bin.",
    };

    // #369: the repeating tasks this undo would pause, as confirm text, or
    // "" when there are none. Any failure → "": the server cascade is the
    // control, the dialog is information, so a lookup must never block
    // the undo (#353's ruling).
    function undoPauseMessage(batchId) {
        var helpers = window.projectArchiveHelpers;
        if (!helpers) return Promise.resolve("");
        return window.apiFetch("/api/recycle-bin/impact/" + batchId)
            .then(function (data) {
                var msg = helpers.archiveConfirmMessage(data && data.paused_templates, UNDO_PAUSE_TAIL);
                // #494: the open subtasks you added go with the import.
                var bin = window.recycleBinHelpers;
                var subs = bin ? bin.addedSubtasksPhrase(data && data.subtasks, "undo") : "";
                return [subs, msg].filter(Boolean).join("\n\n");
            })
            .catch(function () { return ""; });
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

        // Disabled during the lookup so a double click can't open two dialogs.
        btn.disabled = true;
        btn.textContent = "Checking…";

        undoPauseMessage(batchId).then(function (pauseMsg) {
            if (!confirm(pauseMsg ? confirmMsg + "\n\n" + pauseMsg : confirmMsg)) {
                btn.disabled = false;
                btn.textContent = "Undo";
                return;
            }
            runUndo(btn, batchId);
        });
    }

    function runUndo(btn, batchId) {
        btn.textContent = "Undoing…";

        // PR67 #132: window.apiFetch (auto-retry + recovery)
        window.apiFetch("/api/recycle-bin/undo/" + batchId, { method: "POST" })
            .then(function () {
                // Refresh the history table and the bin count — and (#444)
                // the overview counts and the nav Inbox badge, which the
                // undo just changed too.
                loadImports();
                loadBinCount();
                loadStats();
                if (window.refreshInboxBadge) window.refreshInboxBadge();
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
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            var data = await window.apiFetch("/api/digest/preview");
            digestText.textContent = data.body;
            digestText.style.display = "";
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
            // PR67 #132: window.apiFetch (auto-retry + recovery)
            await window.apiFetch("/api/digest/send", { method: "POST" });
            alert("Digest sent successfully!");
        } catch (err) {
            alert("Send failed: " + err.message);
        }

        sendBtn.disabled = false;
        sendBtn.textContent = "Send Now";
    });

    // Feature 1 (2026-05-09): Weekly Focus slot count input.
    var slotInput = document.getElementById("settingsWeeklyFocusSlotCount");
    var slotSave = document.getElementById("settingsWeeklyFocusSave");
    var slotStatus = document.getElementById("settingsWeeklyFocusStatus");
    if (slotInput && slotSave) {
        // Hydrate the current value on load.
        window.apiFetch("/api/weekly-focus").then(function (d) {
            slotInput.value = String(d.slot_count);
        }).catch(function () { /* leave default */ });

        slotSave.addEventListener("click", async function () {
            var n = parseInt(slotInput.value, 10);
            if (isNaN(n) || n < 1 || n > 7) {
                alert("Slots must be between 1 and 7.");
                return;
            }
            slotSave.disabled = true;
            try {
                var r = await window.apiFetch(
                    "/api/weekly-focus/settings/slot-count",
                    {
                        method: "PATCH",
                        body: JSON.stringify({ slot_count: n }),
                    }
                );
                slotInput.value = String(r.slot_count);
                slotStatus.textContent = "Saved.";
                setTimeout(function () { slotStatus.textContent = ""; }, 2000);
            } catch (err) {
                alert("Save failed: " + err.message);
            }
            slotSave.disabled = false;
        });
    }

    // --- #499: Siri voice review token -------------------------------------
    // Make a token here on the phone, copy it into the Shortcut, revoke an
    // old one. The token lives only in this page's field until Done (or a
    // reload) — the server never stores it.

    (function voiceTokenCard() {
        var section = document.getElementById("settingsVoiceToken");
        var h = window.voiceTokenHelpers;
        if (!section || !h) return;

        var daysSel = document.getElementById("voiceTokenDays");
        var makeBtn = document.getElementById("voiceTokenMake");
        var makeStatus = document.getElementById("voiceTokenMakeStatus");
        var newBox = document.getElementById("voiceTokenNew");
        var valueEl = document.getElementById("voiceTokenValue");
        var copyBtn = document.getElementById("voiceTokenCopy");
        var copyHeaderBtn = document.getElementById("voiceTokenCopyHeader");
        var doneBtn = document.getElementById("voiceTokenDone");
        var copyStatus = document.getElementById("voiceTokenCopyStatus");
        var listEl = document.getElementById("voiceTokenList");
        var emptyEl = document.getElementById("voiceTokenEmpty");
        var byIdInput = document.getElementById("voiceTokenRevokeId");
        var byIdBtn = document.getElementById("voiceTokenRevokeById");
        var revokeStatus = document.getElementById("voiceTokenRevokeStatus");

        // A deploy's auto-reload must not wipe a token not yet copied.
        if (window.reloadGuard) {
            window.reloadGuard.add(function () { return !newBox.hidden; });
        }

        function showStatus(el, text, ok) {
            el.textContent = text || "";
            el.classList.toggle("settings-ok", !!text && ok === true);
            el.classList.toggle("settings-warn", !!text && ok === false);
        }

        function renderList(tokens) {
            listEl.innerHTML = "";
            emptyEl.hidden = tokens.length > 0;
            tokens.forEach(function (row) {
                var label = h.tokenRowLabel(row, new Date());
                var li = document.createElement("li");
                li.className = "voice-token-row";
                li.dataset.jti = row.jti;

                var text = document.createElement("div");
                text.className = "voice-token-row-text";
                var dates = document.createElement("span");
                dates.className = "voice-token-row-dates";
                dates.textContent = label.dates;
                var meta = document.createElement("span");
                meta.className = "voice-token-row-meta";
                var state = document.createElement("strong");
                state.className = "voice-token-state " +
                    (label.state === "Active" ? "settings-ok" : "settings-warn");
                state.textContent = label.state;
                var idText = document.createElement("code");
                idText.textContent = row.jti;
                meta.appendChild(state);
                meta.appendChild(document.createTextNode(" · id "));
                meta.appendChild(idText);
                text.appendChild(dates);
                text.appendChild(meta);
                li.appendChild(text);

                if (label.canRevoke) {
                    var btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "btn btn-sm voice-token-revoke";
                    btn.textContent = "Revoke";
                    btn.setAttribute("aria-label", "Revoke the token " + label.dates.toLowerCase());
                    btn.addEventListener("click", function () {
                        if (!confirm("Revoke this token? A Shortcut that still uses it stops working.")) return;
                        window.withInflight(btn, function () { return revoke(row.jti); });
                    });
                    li.appendChild(btn);
                }
                listEl.appendChild(li);
            });
        }

        function loadTokens() {
            return window.apiFetch("/api/settings/voice-tokens")
                .then(function (data) {
                    sectionClearLoadError("settingsVoiceToken");
                    renderList((data && data.tokens) || []);
                })
                .catch(function (err) {
                    console.error("settings/voice-tokens failed:", err);
                    sectionLoadError("settingsVoiceToken", "your Siri tokens", err, loadTokens);
                });
        }

        function revoke(jti) {
            showStatus(revokeStatus, "");
            return window.apiFetch(
                "/api/settings/voice-tokens/" + encodeURIComponent(jti) + "/revoke",
                { method: "POST" }
            ).then(function () {
                showStatus(revokeStatus, "Revoked " + jti + ".", true);
                return loadTokens().then(function () { return true; });
            }).catch(function (err) {
                showStatus(revokeStatus, "Revoke didn't save: " + (err.message || "network error"), false);
                return false;
            });
        }

        function hideNew() {
            valueEl.value = "";
            newBox.hidden = true;
            showStatus(copyStatus, "");
        }

        makeBtn.addEventListener("click", function () {
            window.withInflight(makeBtn, function () {
                showStatus(makeStatus, "");
                return window.apiFetch("/api/settings/voice-tokens", {
                    method: "POST",
                    body: JSON.stringify({ days: h.clampDays(daysSel.value) }),
                }).then(function (made) {
                    valueEl.value = made.token;
                    newBox.hidden = false;
                    // Tall enough to show the whole token (5 lines at 375).
                    valueEl.style.height = "auto";
                    valueEl.style.height = (valueEl.scrollHeight + 2) + "px";
                    showStatus(copyStatus, "");
                    showStatus(makeStatus, "Made a token (id " + made.jti + "). Copy it below.", true);
                    copyBtn.focus();
                    return loadTokens();
                }).catch(function (err) {
                    showStatus(makeStatus, "Couldn't make a token: " + (err.message || "network error"), false);
                });
            });
        });

        function copy(text) {
            return h.copyText(text, valueEl, { navigator: navigator, document: document })
                .then(function (result) {
                    if (result === "copied") {
                        showStatus(copyStatus, "Copied. Paste it into the Shortcut.", true);
                    } else if (result === "selected") {
                        showStatus(copyStatus, "Selected — tap Copy in the menu.", null);
                    } else {
                        showStatus(copyStatus, "Couldn't copy — press and hold the token to select it.", false);
                    }
                });
        }

        copyBtn.addEventListener("click", function () {
            copy(valueEl.value);
        });
        copyHeaderBtn.addEventListener("click", function () {
            copy(h.headerValue(valueEl.value));
        });
        doneBtn.addEventListener("click", hideNew);

        byIdBtn.addEventListener("click", function () {
            var jti = h.normalizeJti(byIdInput.value);
            if (!h.isValidJti(jti)) {
                showStatus(revokeStatus, "That isn't a token id — it is 16 letters and digits (0-9, a-f).", false);
                return;
            }
            if (!confirm("Revoke the token " + jti + "? A Shortcut that still uses it stops working.")) return;
            window.withInflight(byIdBtn, function () {
                return revoke(jti).then(function (ok) { if (ok) byIdInput.value = ""; });
            });
        });

        loadTokens();
    })();
})();
