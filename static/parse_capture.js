/**
 * parseCapture — extract tier, type, repeat, and URL shortcuts from
 * quick-capture text.
 *
 * This module is the single source of truth for capture parsing logic.
 * It is imported by both capture.js (browser) and Jest tests (Node).
 *
 * Parsing order (critical for avoiding prefix collisions):
 *   1. URL detection
 *   1b. @project hint (#207)
 *   2. Repeat shortcuts (#daily, #weekdays, #weekly, #monthly)
 *   3. Type shortcuts (#personal, #work)
 *   4. Tier shortcuts (#today, #week, #backlog, #freezer)
 *   5. Empty title fallback
 */
"use strict";

function parseCapture(text) {
    var result = { title: text, tier: "inbox" };

    // 1. Detect a URL anywhere in the text
    var urlMatch = text.match(/https?:\/\/\S+/i);
    if (urlMatch) {
        result.url = urlMatch[0];
        var remaining = text.replace(urlMatch[0], "").trim();
        result.title = remaining || urlMatch[0];
        result._titleProvided = remaining.length > 0;
    }

    // 1b. @project hint (#207). A single @token of letters/digits
    //     anywhere in the text — e.g. "@Audit" — is lifted out as a
    //     project hint. parseCapture cannot know project names (it's a
    //     pure client-side function), so it only extracts the raw
    //     token; the server resolves it to a project_id by
    //     case-insensitive substring match in POST /api/tasks.
    //     Detected AFTER URL extraction so an "@" inside a URL path
    //     (e.g. /@handle) isn't mistaken for a project hint. The
    //     "(^|[^\w@])" prefix — a captured leading char rather than a
    //     lookbehind, for older-Safari (<16.4) safety — requires the
    //     "@" to sit at the start or after a non-word char, so
    //     "user@example" (an email) does NOT match.
    var projMatch = result.title.match(/(^|[^\w@])@([A-Za-z0-9]+)/);
    if (projMatch) {
        result.project_hint = projMatch[2];
        result.title = result.title
            // Drop "@token" but keep the captured leading char. A
            // function replacer avoids "$"-substitution surprises.
            .replace(projMatch[0], function () { return projMatch[1]; })
            // "Foo (@bar)" leaves an empty "()" behind once @bar is
            // gone — drop empty brackets + collapse the double space.
            .replace(/\(\s*\)/g, "")
            .replace(/\[\s*\]/g, "")
            .replace(/\s{2,}/g, " ")
            .trim();
    }

    // 2. Repeat shortcuts (BEFORE tier — longer tags like #weekly
    //    must be consumed before #week matches as a tier prefix)
    var repeatMap = {
        "#daily": { frequency: "daily" },
        "#weekdays": { frequency: "weekdays" },
        "#weekly": { frequency: "weekly", day_of_week: new Date().getDay() === 0 ? 6 : new Date().getDay() - 1 },
        "#monthly": { frequency: "monthly_date", day_of_month: new Date().getDate() },
    };
    var repeatTags = Object.keys(repeatMap);
    for (var i = 0; i < repeatTags.length; i++) {
        var tag = repeatTags[i];
        if (result.title.toLowerCase().includes(tag)) {
            result.repeat = repeatMap[tag];
            result.title = result.title.replace(new RegExp(tag, "gi"), "").trim();
            break;
        }
    }

    // 3. Type shortcuts (before tier — #work must not match #week prefix)
    if (result.title.toLowerCase().includes("#personal")) {
        result.type = "personal";
        result.title = result.title.replace(/#personal/gi, "").trim();
    } else if (result.title.toLowerCase().includes("#work")) {
        result.type = "work";
        result.title = result.title.replace(/#work/gi, "").trim();
    }

    // 4. Tier shortcuts: #today #tomorrow #week #next_week #backlog #freezer
    // Longest-first matters because #includes() would match #week inside
    // #next_week if we checked #week first — so we sort tags by length
    // descending before scanning. Same reason we process repeat shortcuts
    // before tier shortcuts (#weekly vs #week).
    var tierMap = {
        "#today": "today",
        "#tomorrow": "tomorrow",     // backlog #27
        "#next_week": "next_week",   // backlog #23 (was missing — fixed here)
        "#nextweek": "next_week",    // common user typo without underscore
        "#week": "this_week",
        "#backlog": "backlog",
        "#freezer": "freezer",
    };
    var tierTags = Object.keys(tierMap).sort(function (a, b) {
        return b.length - a.length;
    });
    // Longest-first scan + first-hit-wins. Can't use `if (result.tier)`
    // as the stop condition because the default tier is "inbox" from
    // line ~18 — that would break before scanning any tag. Track an
    // explicit `tierMatched` flag instead.
    var tierMatched = false;
    for (var j = 0; j < tierTags.length; j++) {
        if (tierMatched) break;
        var tierTag = tierTags[j];
        if (result.title.toLowerCase().includes(tierTag)) {
            result.tier = tierMap[tierTag];
            result.title = result.title.replace(new RegExp(tierTag, "gi"), "").trim();
            tierMatched = true;
        }
    }

    // 5. Empty title fallback
    if (!result.title && result.url) {
        result.title = result.url;
    }

    return result;
}

// Export for Node.js (Jest) — browser ignores this
if (typeof module !== "undefined" && module.exports) {
    module.exports = { parseCapture: parseCapture };
}
