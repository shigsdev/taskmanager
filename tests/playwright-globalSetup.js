/**
 * Playwright global setup — macOS no-IPv6 workaround.
 *
 * See playwright.config.js for the full diagnosis. Short version:
 * macOS's resolver returns IPv4-mapped IPv6 addresses (`::ffff:1.2.3.4`)
 * for AAAA queries even when no real AAAA record exists and v6 isn't
 * routable on this network. Playwright's Happy Eyeballs implementation
 * tries those mapped addresses first → hangs → 15s timeout.
 *
 * This globalSetup patches `dns.promises.lookup` to return an empty
 * array for any v6-family lookup. v4 lookups pass through unchanged,
 * so normal page navigation (Chrome's network stack, separate from
 * this) is unaffected.
 *
 * Note: globalSetup runs ONCE in the parent process before workers
 * spawn. Modules are cached per-process. Workers inherit this patch
 * because Playwright forks them after globalSetup completes — the
 * patched `dns.promises.lookup` is a property of the dns module
 * exports, which is structured-cloned across the fork (in CommonJS,
 * the worker re-requires the dns module fresh, so the patch wouldn't
 * survive). For redundancy, smoke.spec.js requires this file directly
 * at the top so the patch is applied in each worker too.
 */
const dns = require("dns");

const origPromisesLookup = dns.promises.lookup;
const origCallbackLookup = dns.lookup;

if (!dns.promises.lookup.__noV6Patched) {
    dns.promises.lookup = function patchedPromisesLookup(hostname, options) {
        if (
            typeof options === "object" &&
            options !== null &&
            options.family === 6
        ) {
            return Promise.resolve(options.all ? [] : null);
        }
        return origPromisesLookup(hostname, options);
    };
    dns.promises.lookup.__noV6Patched = true;

    // Also patch the callback form in case Playwright uses it.
    dns.lookup = function patchedCallbackLookup(hostname, options, callback) {
        let opts = options;
        let cb = callback;
        if (typeof options === "function") {
            cb = options;
            opts = {};
        }
        if (
            typeof opts === "object" &&
            opts !== null &&
            opts.family === 6
        ) {
            const empty = opts.all ? [] : null;
            process.nextTick(() => {
                if (opts.all) cb(null, empty);
                else cb(new Error("ENOTFOUND (no IPv6)"), null);
            });
            return;
        }
        return origCallbackLookup(hostname, opts, cb);
    };
    dns.lookup.__noV6Patched = true;
}

module.exports = async () => {
    // No-op exported function — the patch is applied at require-time above.
};
