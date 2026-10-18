/**
 * Recycle Bin page — list soft-deleted batches, restore or purge them.
 *
 * State model (matches recycle_service.py):
 *   - "In the bin" = ImportLog.undone_at is set AND batch_id is set.
 *   - Restore puts the batch back into normal rotation.
 *   - Purge (per batch) hard-deletes the rows; requires typed "DELETE".
 *   - Empty Bin purges every batch at once; requires typed "DELETE".
 *
 * No automated cleanup — see BACKLOG.md Freezer for the deferred auto-TTL.
 *
 * #428: a Deleted tasks section lists tasks deleted the ordinary way
 * (GET /api/tasks?status=deleted) and restores one with
 * PATCH {status: "active"}. Ordering / labels: recycle_bin_helpers.js.
 */

(function () {
    "use strict";

    var listEl = document.getElementById("recycleList");
    var emptyMsg = document.getElementById("recycleEmptyMsg");
    var summaryText = document.getElementById("recycleSummaryText");
    var emptyBtn = document.getElementById("recycleEmptyBtn");

    var modal = document.getElementById("recycleModalOverlay");
    var modalTitle = document.getElementById("recycleModalTitle");
    var modalBody = document.getElementById("recycleModalBody");
    var modalConfirmRow = document.getElementById("recycleModalConfirmRow");
    var modalInput = document.getElementById("recycleModalConfirmInput");
    var modalConfirm = document.getElementById("recycleModalConfirm");
    var modalCancel = document.getElementById("recycleModalCancel");

    var deletedListEl = document.getElementById("recycleDeletedList");
    var deletedEmptyEl = document.getElementById("recycleDeletedEmpty");
    var deletedMoreBtn = document.getElementById("recycleDeletedMore");
    var DELETED_SHOWN = 25;
    var deletedTasks = [];
    var showAllDeleted = false;

    // --- Loading -------------------------------------------------------------

    // #440: a failed load is said in its own box inside the section (the
    // summary row holds Empty Bin, so it can't be replaced), with a Retry.
    function loadError(sectionId, hostId, what, err, retry) {
        var section = document.getElementById(sectionId);
        if (!section || !window.loadErrorHelpers) return;
        var host = document.getElementById(hostId);
        if (!host) {
            host = document.createElement("div");
            host.id = hostId;
            section.appendChild(host);
        }
        window.loadErrorHelpers.showLoadError(host, what, err, retry);
    }

    function clearLoadError(hostId) {
        var host = document.getElementById(hostId);
        if (host) host.remove();
    }

    function load() {
        // PR67 #132: window.apiFetch (auto-retry + recovery)
        Promise.all([
            window.apiFetch("/api/recycle-bin"),
            window.apiFetch("/api/recycle-bin/summary"),
        ]).then(function (results) {
            clearLoadError("recycleLoadError");
            renderBatches(results[0].batches || []);
            renderSummary(results[1]);
        }).catch(function (err) {
            console.error("Failed to load recycle bin:", err);
            // #440: it used to stay on "Loading…" with a blank list.
            summaryText.textContent = "";
            loadError("recycleSummary", "recycleLoadError", "the Recycle Bin", err, load);
        });
        loadDeleted();
    }

    // --- #428: Deleted tasks -------------------------------------------------

    function loadDeleted() {
        window.apiFetch("/api/tasks?status=deleted").then(function (tasks) {
            clearLoadError("recycleDeletedLoadError");
            deletedTasks = Array.isArray(tasks) ? tasks : [];
            renderDeleted();
        }).catch(function (err) {
            console.error("Failed to load deleted tasks:", err);
            loadError("recycleDeletedSection", "recycleDeletedLoadError",
                      "your deleted tasks", err, loadDeleted);
        });
    }

    function renderDeleted() {
        var out = window.recycleBinHelpers.binDeletedTasks(
            deletedTasks, showAllDeleted ? 0 : DELETED_SHOWN
        );
        deletedListEl.innerHTML = "";
        deletedEmptyEl.style.display = out.total ? "none" : "";
        out.rows.forEach(function (row) {
            deletedListEl.appendChild(deletedRow(row));
        });
        if (out.hidden) {
            deletedMoreBtn.style.display = "";
            deletedMoreBtn.textContent = "Show all " + out.total;
        } else {
            deletedMoreBtn.style.display = "none";
        }
    }

    deletedMoreBtn.addEventListener("click", function () {
        showAllDeleted = true;
        renderDeleted();
    });

    function deletedRow(row) {
        var li = document.createElement("li");
        li.className = "recycle-item";
        li.dataset.taskId = row.id;

        var header = document.createElement("div");
        header.className = "recycle-item-header";
        var title = document.createElement("div");
        title.className = "recycle-item-title";
        title.textContent = row.title;
        var dates = document.createElement("div");
        dates.className = "recycle-item-dates";
        dates.textContent = (row.deletedAt
            ? "Deleted " + row.deletedAt.toLocaleDateString() + " · "
            : "") + "was in " + row.section;
        header.appendChild(title);
        header.appendChild(dates);
        if (row.parentDeleted) {
            var note = document.createElement("div");
            note.className = "recycle-item-counts";
            note.textContent = "A subtask — its parent task is deleted too; restore that as well to see it.";
            header.appendChild(note);
        }
        // #433: the open subtasks deleted with it come back with it.
        if (row.subtaskCount) {
            var subNote = document.createElement("div");
            subNote.className = "recycle-item-counts recycle-item-subtasks";
            subNote.textContent = "+" + row.subtaskCount +
                (row.subtaskCount === 1 ? " subtask comes" : " subtasks come") + " back with it";
            header.appendChild(subNote);
        }

        var actions = document.createElement("div");
        actions.className = "recycle-item-actions";
        var restoreBtn = document.createElement("button");
        restoreBtn.className = "btn btn-sm";
        restoreBtn.textContent = "Restore";
        restoreBtn.addEventListener("click", function () {
            restoreTask(row, li, restoreBtn, dates);
        });
        actions.appendChild(restoreBtn);

        li.appendChild(header);
        li.appendChild(actions);
        return li;
    }

    function restoreTask(row, li, btn, statusEl) {
        btn.disabled = true;
        btn.textContent = "Restoring…";
        window.apiFetch("/api/tasks/" + row.id, {
            method: "PATCH",
            body: JSON.stringify({ status: "active" }),
        }).then(function (task) {
            // #433: the subtasks that went with it are back too.
            deletedTasks = deletedTasks.filter(function (t) {
                return t.id !== row.id && !(t.deleted_with_parent && t.parent_id === row.id);
            });
            li.classList.add("recycle-item-restored");
            // The "come back with it" promise is kept — the status says so.
            var subNote = li.querySelector(".recycle-item-subtasks");
            if (subNote) subNote.remove();
            btn.remove();
            statusEl.textContent = "Restored to " +
                window.recycleBinHelpers.binSectionLabel(task.tier) +
                (row.subtaskCount
                    ? " with its " + row.subtaskCount + " subtask" + (row.subtaskCount === 1 ? "" : "s")
                    : "") + ".";
            statusEl.setAttribute("role", "status");
        }).catch(function (err) {
            btn.disabled = false;
            btn.textContent = "Retry";
            statusEl.textContent = "Couldn't restore it: " + (err.message || err);
        });
    }

    function renderSummary(data) {
        // #478: projects count — a projects-only bin used to read empty.
        var H = window.recycleBinHelpers;
        if (H.binItemTotal(data) === 0) {
            summaryText.textContent = "No undone imports.";
            emptyBtn.disabled = true;
            return;
        }
        var batchWord = data.batch_count === 1 ? "batch" : "batches";
        summaryText.textContent = H.binItemPhrase(data) + " across " +
            data.batch_count + " " + batchWord + ".";
        emptyBtn.disabled = false;
    }

    function renderBatches(batches) {
        listEl.innerHTML = "";
        if (!batches.length) {
            emptyMsg.style.display = "";
            return;
        }
        emptyMsg.style.display = "none";

        batches.forEach(function (batch) {
            var li = document.createElement("li");
            li.className = "recycle-item";

            var header = document.createElement("div");
            header.className = "recycle-item-header";

            var title = document.createElement("div");
            title.className = "recycle-item-title";
            title.textContent = batch.source;

            var dates = document.createElement("div");
            dates.className = "recycle-item-dates";
            var imported = batch.imported_at ? new Date(batch.imported_at) : null;
            var undone = batch.undone_at ? new Date(batch.undone_at) : null;
            var datesLine = "";
            if (imported) {
                datesLine += "Imported " + imported.toLocaleDateString() +
                    " " + imported.toLocaleTimeString();
            }
            if (undone) {
                if (datesLine) datesLine += " · ";
                datesLine += "Undone " + undone.toLocaleDateString() +
                    " " + undone.toLocaleTimeString();
            }
            dates.textContent = datesLine;

            var counts = document.createElement("div");
            counts.className = "recycle-item-counts";
            // #478: projects too (a projects-only batch read "0 items").
            counts.textContent = (window.recycleBinHelpers.binItemTotal(batch)
                ? window.recycleBinHelpers.binItemPhrase(batch) : "0 items")
                // #494: and the subtasks you added that went with it.
                + (batch.subtask_count
                    ? " " + window.recycleBinHelpers.addedSubtasksPhrase(batch.subtask_count, "row")
                    : "");

            header.appendChild(title);
            header.appendChild(dates);
            header.appendChild(counts);

            var actions = document.createElement("div");
            actions.className = "recycle-item-actions";

            var restoreBtn = document.createElement("button");
            restoreBtn.className = "btn btn-sm";
            restoreBtn.textContent = "Restore";
            restoreBtn.addEventListener("click", function () {
                onRestore(batch);
            });

            var purgeBtn = document.createElement("button");
            purgeBtn.className = "btn btn-sm btn-danger";
            purgeBtn.textContent = "Purge";
            purgeBtn.addEventListener("click", function () {
                onPurge(batch);
            });

            actions.appendChild(restoreBtn);
            actions.appendChild(purgeBtn);

            li.appendChild(header);
            li.appendChild(actions);
            listEl.appendChild(li);
        });
    }

    // --- Actions -------------------------------------------------------------

    function onRestore(batch) {
        // #367: restore leaves a goal the user archived before the undo
        // alone, so count only the goals it will bring back. Purge below
        // still uses goal_count: it deletes every goal in the batch.
        // #478: the same for projects, which it now names.
        var body = "Restore " + window.recycleBinHelpers.binItemPhrase(batch, {
            goal: "restore_goal_count", project: "restore_project_count",
        }) + " from this batch?";
        // #494: and the subtasks you added that went with it.
        var subs = window.recycleBinHelpers.addedSubtasksPhrase(batch.subtask_count, "restore");
        if (subs) body += " " + subs;
        openModal({
            title: "Restore Batch",
            body: body,
            requireConfirmation: false,
            onConfirm: function () {
                // PR67 #132: window.apiFetch (auto-retry + recovery)
                // apiFetch throws on !ok, so wrap to keep modal's
                // {ok, body} contract.
                return window.apiFetch("/api/recycle-bin/restore/" + batch.batch_id, {
                    method: "POST",
                }).then(function (b) { return { ok: true, body: b }; })
                  .catch(function (e) { return { ok: false, body: { error: e.message } }; });
            },
        });
    }

    function onPurge(batch) {
        var body = "Permanently delete " + window.recycleBinHelpers.binItemPhrase(batch) +
            " from this batch? This cannot be undone.";   // #478: names projects
        // #494: and the subtasks you added that went with it.
        var subs = window.recycleBinHelpers.addedSubtasksPhrase(batch.subtask_count, "purge");
        if (subs) body = body.replace(" This cannot be undone.", " " + subs + " This cannot be undone.");
        // #373: and the repeating tasks it leaves paused for good.
        var paused = window.recycleBinHelpers.staysPausedPhrase(batch.stays_paused, "purge");
        if (paused) body = body.replace(" This cannot be undone.", " " + paused + " This cannot be undone.");
        openModal({
            title: "Purge Batch",
            body: body,
            requireConfirmation: true,
            onConfirm: function (token) {
                // PR67 #132: window.apiFetch (auto-retry + recovery)
                return window.apiFetch("/api/recycle-bin/purge/" + batch.batch_id, {
                    method: "POST",
                    body: JSON.stringify({ confirmation: token }),
                }).then(function (b) { return { ok: true, body: b }; })
                  .catch(function (e) { return { ok: false, body: { error: e.message } }; });
            },
        });
    }

    emptyBtn.addEventListener("click", function () {
        // PR67 #132: window.apiFetch (auto-retry + recovery)
        window.apiFetch("/api/recycle-bin/summary")
            .then(function (data) {
                // #478: names projects too.
                var body = "Permanently delete everything in the recycle bin?\n" +
                    window.recycleBinHelpers.binItemPhrase(data) + " across " +
                    data.batch_count + " batch" + (data.batch_count === 1 ? "" : "es") + ". " +
                    "This cannot be undone.";
                // #373: and the repeating tasks it leaves paused for good.
                var paused = window.recycleBinHelpers.staysPausedPhrase(data.stays_paused, "empty");
                if (paused) body = body.replace("This cannot be undone.", paused + " This cannot be undone.");
                openModal({
                    title: "Empty Recycle Bin",
                    body: body,
                    requireConfirmation: true,
                    onConfirm: function (token) {
                        return window.apiFetch("/api/recycle-bin/empty", {
                            method: "POST",
                            body: JSON.stringify({ confirmation: token }),
                        }).then(function (b) { return { ok: true, body: b }; })
                          .catch(function (e) { return { ok: false, body: { error: e.message } }; });
                    },
                });
            }).catch(function (err) {
                alert("Could not load summary: " + err.message);
            });
    });

    // --- Modal ---------------------------------------------------------------

    var currentHandler = null;

    function openModal(opts) {
        modalTitle.textContent = opts.title;
        modalBody.textContent = opts.body;
        modalConfirmRow.style.display = opts.requireConfirmation ? "" : "none";
        modalInput.value = "";
        modalConfirm.disabled = !!opts.requireConfirmation;
        currentHandler = opts;
        modal.style.display = "";
        if (opts.requireConfirmation) {
            setTimeout(function () { modalInput.focus(); }, 50);
        }
    }

    function closeModal() {
        modal.style.display = "none";
        currentHandler = null;
    }

    modalInput.addEventListener("input", function () {
        modalConfirm.disabled = modalInput.value !== "DELETE";
    });

    modalCancel.addEventListener("click", closeModal);

    modalConfirm.addEventListener("click", function () {
        if (!currentHandler) return;
        var token = currentHandler.requireConfirmation ? modalInput.value : null;
        modalConfirm.disabled = true;
        currentHandler.onConfirm(token).then(function (res) {
            if (!res.ok) {
                alert("Action failed: " + (res.body.error || "unknown error"));
                modalConfirm.disabled = false;
                return;
            }
            closeModal();
            load();
        }).catch(function (err) {
            alert("Action failed: " + err.message);
            modalConfirm.disabled = false;
        });
    });

    // --- Init ----------------------------------------------------------------

    load();
})();
