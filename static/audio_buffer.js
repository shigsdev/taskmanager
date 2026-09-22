/**
 * audioBuffer — transient on-device buffer for in-flight recording audio
 * (#327, ADR: "audio may rest on disk temporarily").
 *
 * WHY THIS EXISTS
 * ---------------
 * A reflection segment's audio used to live ONLY in a JS array until the
 * user hit Pause. If iOS evicted the backgrounded tab mid-recording, up
 * to 30 minutes of speech vanished silently — and #326 tripled that
 * exposure by raising the segment cap. #324's drafts protect transcribed
 * TEXT, not un-uploaded AUDIO.
 *
 * WHAT CHANGED, PRECISELY
 * -----------------------
 * The app's long-standing promise was "audio is processed in memory only
 * — never written to disk". That is now narrowed, NOT abandoned:
 *
 *   SERVER  — still strictly in-memory. No audio ever touches server
 *             disk or the database. This half is UNCHANGED and binding.
 *   DEVICE  — chunks rest in this origin's IndexedDB, inside the
 *             browser's sandboxed profile storage, ONLY until that
 *             segment is transcribed. Unencrypted at rest (relies on OS
 *             disk encryption) — an accepted risk for a single-user app
 *             holding the user's own voice on their own device.
 *
 * TRANSIENT BY CONSTRUCTION — every path that ends a segment deletes it:
 *   - transcribed successfully        -> dropSegment()
 *   - Done / Cancel                   -> purgeAll()
 *   - older than RETENTION_MS on load -> purgeExpired()
 * Orphans are OFFERED to the user on next load rather than silently
 * transcribed (that costs money) or silently binned (that's the bug we
 * are fixing).
 *
 * FAILS OPEN. Every call resolves rather than rejects: if IndexedDB is
 * unavailable (private mode, quota, an old browser) recording must still
 * work exactly as it did before. A buffer is insurance, never a
 * dependency.
 *
 * Dual-export: window.audioBuffer in the browser, module.exports for Jest.
 */
"use strict";

(function () {
    var DB_NAME = "taskmanager-audio";
    var DB_VERSION = 1;
    var CHUNK_STORE = "chunks";
    var SEG_STORE = "segments";
    // Bounded retention: an orphan older than this is purged unread on
    // the next load. Long enough to recover "I came back the next
    // morning", short enough that stale audio doesn't accumulate.
    var RETENTION_MS = 24 * 60 * 60 * 1000;

    function _idb() {
        try {
            return (typeof indexedDB !== "undefined") ? indexedDB : null;
        } catch (e) { return null; }
    }

    function openDb() {
        return new Promise(function (resolve) {
            var idb = _idb();
            if (!idb) { resolve(null); return; }
            var req;
            try { req = idb.open(DB_NAME, DB_VERSION); }
            catch (e) { resolve(null); return; }
            req.onupgradeneeded = function () {
                var db = req.result;
                if (!db.objectStoreNames.contains(CHUNK_STORE)) {
                    // Composite key keeps chunks ordered within a segment
                    // — reassembly order is correctness, not cosmetics.
                    var cs = db.createObjectStore(CHUNK_STORE, {
                        keyPath: ["segmentId", "seq"],
                    });
                    cs.createIndex("bySegment", "segmentId", { unique: false });
                }
                if (!db.objectStoreNames.contains(SEG_STORE)) {
                    db.createObjectStore(SEG_STORE, { keyPath: "segmentId" });
                }
            };
            req.onsuccess = function () { resolve(req.result); };
            req.onerror = function () { resolve(null); };
            req.onblocked = function () { resolve(null); };
        });
    }

    function _tx(db, stores, mode, fn) {
        return new Promise(function (resolve) {
            if (!db) { resolve(null); return; }
            var tx;
            try { tx = db.transaction(stores, mode); }
            catch (e) { resolve(null); return; }
            var out = null;
            tx.oncomplete = function () { resolve(out); };
            tx.onerror = function () { resolve(null); };
            tx.onabort = function () { resolve(null); };
            try { fn(tx, function (v) { out = v; }); }
            catch (e) { resolve(null); }
        });
    }

    /** Register a new segment. Safe to call repeatedly. */
    async function beginSegment(segmentId, meta) {
        var db = await openDb();
        return _tx(db, [SEG_STORE], "readwrite", function (tx) {
            tx.objectStore(SEG_STORE).put({
                segmentId: segmentId,
                startedAt: (meta && meta.startedAt) || Date.now(),
                mime: (meta && meta.mime) || "",
                bytes: 0,
                chunkCount: 0,
            });
        });
    }

    /** Persist one chunk and bump the segment's running totals. */
    async function putChunk(segmentId, seq, blob, mime) {
        var db = await openDb();
        return _tx(db, [CHUNK_STORE, SEG_STORE], "readwrite", function (tx) {
            tx.objectStore(CHUNK_STORE).put({
                segmentId: segmentId, seq: seq, blob: blob,
            });
            var segs = tx.objectStore(SEG_STORE);
            var get = segs.get(segmentId);
            get.onsuccess = function () {
                var rec = get.result || {
                    segmentId: segmentId, startedAt: Date.now(),
                    mime: mime || "", bytes: 0, chunkCount: 0,
                };
                rec.bytes += (blob && blob.size) || 0;
                rec.chunkCount += 1;
                if (mime && !rec.mime) rec.mime = mime;
                segs.put(rec);
            };
        });
    }

    /** All buffered segments, newest first. [] when unavailable. */
    async function listSegments() {
        var db = await openDb();
        var rows = await _tx(db, [SEG_STORE], "readonly", function (tx, set) {
            var req = tx.objectStore(SEG_STORE).getAll();
            req.onsuccess = function () { set(req.result || []); };
        });
        return (rows || []).sort(function (a, b) {
            return (b.startedAt || 0) - (a.startedAt || 0);
        });
    }

    /** One segment's chunks as a single Blob, or null if nothing stored. */
    async function assembleSegment(segmentId) {
        var db = await openDb();
        var rows = await _tx(db, [CHUNK_STORE], "readonly", function (tx, set) {
            var idx = tx.objectStore(CHUNK_STORE).index("bySegment");
            var req = idx.getAll(IDBKeyRange.only(segmentId));
            req.onsuccess = function () { set(req.result || []); };
        });
        if (!rows || !rows.length) return null;
        rows.sort(function (a, b) { return a.seq - b.seq; });
        var mime = "";
        var segs = await listSegments();
        for (var i = 0; i < segs.length; i++) {
            if (segs[i].segmentId === segmentId) { mime = segs[i].mime || ""; break; }
        }
        try {
            return new Blob(rows.map(function (r) { return r.blob; }),
                            mime ? { type: mime } : undefined);
        } catch (e) { return null; }
    }

    /** Delete one segment and its chunks. The main cleanup path. */
    async function dropSegment(segmentId) {
        var db = await openDb();
        return _tx(db, [CHUNK_STORE, SEG_STORE], "readwrite", function (tx) {
            var idx = tx.objectStore(CHUNK_STORE).index("bySegment");
            var cur = idx.openCursor(IDBKeyRange.only(segmentId));
            cur.onsuccess = function () {
                var c = cur.result;
                if (!c) return;
                c.delete();
                c.continue();
            };
            tx.objectStore(SEG_STORE).delete(segmentId);
        });
    }

    /** Delete everything. Used on Done / Cancel. */
    async function purgeAll() {
        var db = await openDb();
        return _tx(db, [CHUNK_STORE, SEG_STORE], "readwrite", function (tx) {
            tx.objectStore(CHUNK_STORE).clear();
            tx.objectStore(SEG_STORE).clear();
        });
    }

    /** Drop anything past the retention window. Returns how many went. */
    async function purgeExpired(nowMs, maxAgeMs) {
        var now = typeof nowMs === "number" ? nowMs : Date.now();
        var maxAge = typeof maxAgeMs === "number" ? maxAgeMs : RETENTION_MS;
        var segs = await listSegments();
        var dropped = 0;
        for (var i = 0; i < segs.length; i++) {
            if (isExpired(segs[i].startedAt, now, maxAge)) {
                await dropSegment(segs[i].segmentId);
                dropped += 1;
            }
        }
        return dropped;
    }

    // --- pure helpers (Jest-tested directly) ---------------------------

    /** Past the retention window? Missing/!finite timestamps count as
     *  expired — an undatable orphan must not linger forever. */
    function isExpired(startedAt, nowMs, maxAgeMs) {
        if (typeof startedAt !== "number" || !isFinite(startedAt)) return true;
        var now = typeof nowMs === "number" && isFinite(nowMs) ? nowMs : Date.now();
        var maxAge = typeof maxAgeMs === "number" && maxAgeMs > 0
            ? maxAgeMs : RETENTION_MS;
        return (now - startedAt) >= maxAge;
    }

    /**
     * describeOrphan — the recovery prompt's wording.
     *
     * Estimates duration from BYTES, not wall-clock: the recording was
     * interrupted, so "started 9 hours ago" says nothing about how much
     * audio exists. At the pinned 32kbps that's 4000 bytes/sec.
     */
    function describeOrphan(seg, bitsPerSecond) {
        if (!seg || !seg.bytes) return "";
        var bps = typeof bitsPerSecond === "number" && bitsPerSecond > 0
            ? bitsPerSecond : 32000;
        var seconds = Math.round(seg.bytes * 8 / bps);
        if (seconds < 60) return "about " + Math.max(1, seconds) + "s of audio";
        var mins = Math.round(seconds / 60);
        return "about " + mins + (mins === 1 ? " minute" : " minutes") + " of audio";
    }

    var api = {
        RETENTION_MS: RETENTION_MS,
        openDb: openDb,
        beginSegment: beginSegment,
        putChunk: putChunk,
        listSegments: listSegments,
        assembleSegment: assembleSegment,
        dropSegment: dropSegment,
        purgeAll: purgeAll,
        purgeExpired: purgeExpired,
        isExpired: isExpired,
        describeOrphan: describeOrphan,
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else if (typeof window !== "undefined") {
        window.audioBuffer = api;
    }
})();
