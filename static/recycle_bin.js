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

    // --- Loading -------------------------------------------------------------

    function load() {
        Promise.all([
            fetch("/api/recycle-bin").then(function (r) { return r.json(); }),
            fetch("/api/recycle-bin/summary").then(function (r) { return r.json(); }),
        ]).then(function (results) {
            renderBatches(results[0].batches || []);
            renderSummary(results[1]);
        });
    }

    function renderSummary(data) {
        var total = (data.task_count || 0) + (data.goal_count || 0);
        if (total === 0) {
            summaryText.textContent = "The recycle bin is empty.";
            emptyBtn.disabled = true;
            return;
        }
        var parts = [];
        if (data.task_count) parts.push(data.task_count + " task" + (data.task_count === 1 ? "" : "s"));
        if (data.goal_count) parts.push(data.goal_count + " goal" + (data.goal_count === 1 ? "" : "s"));
        var batchWord = data.batch_count === 1 ? "batch" : "batches";
        summaryText.textContent = parts.join(" and ") + " across " +
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
            var countParts = [];
            if (batch.task_count) countParts.push(batch.task_count + " task" + (batch.task_count === 1 ? "" : "s"));
            if (batch.goal_count) countParts.push(batch.goal_count + " goal" + (batch.goal_count === 1 ? "" : "s"));
            counts.textContent = countParts.length ? countParts.join(", ") : "0 items";

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
        var body = "Restore " + batch.task_count + " task" +
            (batch.task_count === 1 ? "" : "s") +
            " and " + batch.goal_count + " goal" +
            (batch.goal_count === 1 ? "" : "s") +
            " from this batch back into your task list?";
        openModal({
            title: "Restore Batch",
            body: body,
            requireConfirmation: false,
            onConfirm: function () {
                return fetch("/api/recycle-bin/restore/" + batch.batch_id, {
                    method: "POST",
                }).then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); });
            },
        });
    }

    function onPurge(batch) {
        var body = "Permanently delete " + batch.task_count + " task" +
            (batch.task_count === 1 ? "" : "s") +
            " and " + batch.goal_count + " goal" +
            (batch.goal_count === 1 ? "" : "s") +
            " from this batch? This cannot be undone.";
        openModal({
            title: "Purge Batch",
            body: body,
            requireConfirmation: true,
            onConfirm: function (token) {
                return fetch("/api/recycle-bin/purge/" + batch.batch_id, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ confirmation: token }),
                }).then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); });
            },
        });
    }

    emptyBtn.addEventListener("click", function () {
        fetch("/api/recycle-bin/summary")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var body = "Permanently delete everything in the recycle bin?\n" +
                    data.task_count + " task(s) and " + data.goal_count + " goal(s) " +
                    "across " + data.batch_count + " batch(es). " +
                    "This cannot be undone.";
                openModal({
                    title: "Empty Recycle Bin",
                    body: body,
                    requireConfirmation: true,
                    onConfirm: function (token) {
                        return fetch("/api/recycle-bin/empty", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ confirmation: token }),
                        }).then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); });
                    },
                });
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
