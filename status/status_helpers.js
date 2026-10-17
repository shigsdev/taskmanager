/**
 * #204 option E — the off-Railway status page's decisions, kept pure so
 * Jest can assert them (CLAUDE.md anti-pattern #3). The page itself
 * (status/index.html) only fetches /healthz and draws what this returns.
 *
 * Dual export: browser → window.statusHelpers; Node (Jest) → module.exports.
 */
(function () {
    "use strict";

    /**
     * What one /healthz poll means.
     *
     * @param {{reached: boolean, httpStatus?: number, body?: object}} r
     *   reached=false: the request failed outright (network error, CORS,
     *   timeout) — the app couldn't be reached at all.
     * @returns {{level: "up"|"degraded"|"down", headline: string,
     *            problems: string[]}}
     *   up       — answered, every check ok / warn / skipped;
     *   degraded — answered, but a non-critical check failed (HTTP 200);
     *   down     — unreachable, an unreadable answer, or a critical check
     *              failed (HTTP 503: Railway won't route to it).
     */
    function classify(r) {
        if (!r || !r.reached) {
            return { level: "down", headline: "Can't reach the app — Railway may be down.", problems: [] };
        }
        const body = r.body;
        if (!body || typeof body !== "object" || typeof body.checks !== "object" || !body.checks) {
            return { level: "down", headline: "The app answered, but not with a health report.", problems: [] };
        }
        const problems = Object.keys(body.checks)
            .filter((k) => String(body.checks[k]).startsWith("fail"))
            .map((k) => `${k}: ${body.checks[k]}`);
        if (r.httpStatus === 503 || (Array.isArray(body.critical_failed) && body.critical_failed.length)) {
            return { level: "down", headline: "The app is running but unhealthy.", problems };
        }
        if (problems.length) {
            return { level: "degraded", headline: "The app is up, with a problem.", problems };
        }
        return { level: "up", headline: "The app is up.", problems: [] };
    }

    /** "just now", "4 min ago", "3 h ago", "2 days ago" — or "never". */
    function ago(thenMs, nowMs) {
        if (!Number.isFinite(thenMs)) return "never";
        const s = Math.max(0, Math.round((nowMs - thenMs) / 1000));
        if (s < 60) return "just now";
        const m = Math.round(s / 60);
        if (m < 60) return `${m} min ago`;
        const h = Math.round(m / 60);
        if (h < 48) return `${h} h ago`;
        return `${Math.round(h / 24)} days ago`;
    }

    /** The deployed commit, short: first 8 characters, or "unknown". */
    function shortSha(sha) {
        return typeof sha === "string" && sha.length >= 7 ? sha.slice(0, 8) : "unknown";
    }

    const api = { classify, ago, shortSha };
    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else if (typeof window !== "undefined") {
        window.statusHelpers = api;
    }
})();
