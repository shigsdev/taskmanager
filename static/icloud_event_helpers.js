/**
 * #371: pure helpers for the user's iCloud Calendar events on /calendar.
 *
 * Dual export, same as calendar_bucket_helpers.js:
 *   Browser: window.icloudEventHelpers (classic <script>).
 *   Node:    module.exports (tests/js/unit/icloud_event_helpers.test.js).
 *
 * Event shape (icloud_service.events_from_ics): {uid, title, start, end,
 * all_day, location, calendar, color}. Timed start/end are ISO strings
 * already in the app's zone ("2026-10-20T09:30-04:00"), so the date and
 * clock are read straight off the string -- never through the browser's
 * own zone, which would move a 23:30 event to the next day for someone
 * travelling. All-day ends are exclusive ("2026-10-22".."2026-10-24" is
 * the 22nd and 23rd), as in iCalendar.
 */
(function () {
    "use strict";

    var MAX_DAYS = 70;   // the longest window /api/icloud/events serves
    var DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    var ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/;

    function _utc(iso) {
        var m = ISO_DATE.exec(String(iso || ""));
        return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : null;
    }

    function _iso(ms) {
        var d = new Date(ms);
        return d.getUTCFullYear() + "-" +
            String(d.getUTCMonth() + 1).padStart(2, "0") + "-" +
            String(d.getUTCDate()).padStart(2, "0");
    }

    // Calendar arithmetic (Date.UTC rolls day 32 into the next month), not
    // milliseconds per day: #424's rule, and UTC has no DST anyway.
    function addDaysIso(iso, n) {
        var m = ISO_DATE.exec(String(iso || ""));
        return m ? _iso(Date.UTC(+m[1], +m[2] - 1, +m[3] + n)) : iso;
    }

    function _datePart(s) {
        var m = ISO_DATE.exec(String(s || ""));
        return m ? m[0] : "";
    }

    function _clock(s) {
        var m = /T(\d{2}):(\d{2})/.exec(String(s || ""));
        return m ? m[1] + ":" + m[2] : "";
    }

    /** Every day (ISO date) the event covers, first to last. */
    function eventDays(ev) {
        if (!ev) return [];
        var first = _datePart(ev.start);
        if (!first) return [];
        var endDay = _datePart(ev.end);
        var last = first;
        if (ev.all_day) {
            if (endDay > first) last = addDaysIso(endDay, -1);
        } else if (endDay > first) {
            // Ending exactly at midnight doesn't reach into that day.
            last = _clock(ev.end) === "00:00" ? addDaysIso(endDay, -1) : endDay;
        }
        var days = [];
        for (var d = first; d <= last && days.length < MAX_DAYS; d = addDaysIso(d, 1)) {
            days.push(d);
        }
        return days;
    }

    function _order(a, b) {
        if (a.all_day !== b.all_day) return a.all_day ? -1 : 1;
        if (a.start !== b.start) return a.start < b.start ? -1 : 1;
        return String(a.title).localeCompare(String(b.title));
    }

    /** {isoDate: [events]} for the days in [startIso, endIso] (inclusive). */
    function bucketEventsByDay(events, startIso, endIso) {
        var by = {};
        (events || []).forEach(function (ev) {
            eventDays(ev).forEach(function (d) {
                if (d < startIso || d > endIso) return;
                (by[d] = by[d] || []).push(ev);
            });
        });
        Object.keys(by).forEach(function (d) { by[d].sort(_order); });
        return by;
    }

    /** "13:15" -> "1:15 PM". */
    function clockLabel(hhmm) {
        var m = /^(\d{2}):(\d{2})$/.exec(String(hhmm || ""));
        if (!m) return "";
        var h = +m[1];
        var suffix = h < 12 ? "AM" : "PM";
        var h12 = h % 12 === 0 ? 12 : h % 12;
        return h12 + ":" + m[2] + " " + suffix;
    }

    function _dayLabel(iso) {
        var ms = _utc(iso);
        if (ms === null) return "";
        var d = new Date(ms);
        return DOW[d.getUTCDay()] + ", " + MON[d.getUTCMonth()] + " " + d.getUTCDate();
    }

    function eventTimeLabel(ev) {
        return ev.all_day ? "All day" : clockLabel(_clock(ev.start));
    }

    /** The time on one day's line: a red-eye shows "10:00 PM" on its first
     *  day and "until 6:30 AM" on the next, not the start time twice. */
    function eventTimeLabelOn(ev, dayIso) {
        if (ev.all_day) return "";
        var days = eventDays(ev);
        if (days.length < 2 || dayIso === days[0]) return clockLabel(_clock(ev.start));
        if (dayIso === days[days.length - 1]) return "until " + clockLabel(_clock(ev.end));
        return "all day";
    }

    /** "Tue, Oct 20 · 9:30 AM – 10:30 AM", "All day · Thu, Oct 22 – Fri, Oct 23". */
    function eventWhenText(ev) {
        var days = eventDays(ev);
        var first = days[0] || _datePart(ev.start);
        var last = days[days.length - 1] || first;
        if (ev.all_day) {
            return "All day · " + _dayLabel(first) +
                (last !== first ? " – " + _dayLabel(last) : "");
        }
        var s = clockLabel(_clock(ev.start));
        var e = clockLabel(_clock(ev.end));
        if (last !== first) {
            return _dayLabel(first) + ", " + s + " – " + _dayLabel(last) + ", " + e;
        }
        return _dayLabel(first) + " · " + s + (e && ev.end !== ev.start ? " – " + e : "");
    }

    /** Rows for the read-only details dialog. */
    function eventDetailRows(ev) {
        var rows = [{ label: "When", value: eventWhenText(ev) }];
        if (ev.location) rows.push({ label: "Where", value: ev.location });
        if (ev.calendar) rows.push({ label: "Calendar", value: ev.calendar });
        return rows;
    }

    /** #498: "09:30" -> "9:30am", "14:00" -> "2pm" — the board's day box
     *  is narrow. */
    function shortClock(hhmm) {
        var m = /^(\d{2}):(\d{2})$/.exec(String(hhmm || ""));
        if (!m) return "";
        var h = +m[1];
        return (h % 12 === 0 ? 12 : h % 12) + (m[2] === "00" ? "" : ":" + m[2]) +
            (h < 12 ? "am" : "pm");
    }

    /** #498: what one board day box shows for its events (already in the
     *  bucketEventsByDay order): the first event, compact ("9:30am
     *  Dentist"), how many more, a spoken label and a hover list. Null when
     *  the day has none. */
    function dayStripSummary(events, dayIso) {
        if (!events || !events.length) return null;
        var first = events[0];
        var label = eventTimeLabelOn(first, dayIso);   // "", "9:30 AM", "until …", "all day"
        var compact = label.indexOf("until ") === 0
            ? "until " + shortClock(_clock(first.end))
            : (label && label !== "all day" ? shortClock(_clock(first.start)) : "");
        var spoken = function (ev) {
            return ((eventTimeLabelOn(ev, dayIso) || "All day") + " " + ev.title).trim();
        };
        var more = events.length - 1;
        return {
            text: (compact ? compact + " " : "") + first.title,
            more: more,
            label: "iCloud: " + spoken(first) + (more ? " and " + more + " more" : "") +
                " — open the calendar",
            title: events.map(spoken).join("\n"),
        };
    }

    /** A calendar color fit for a CSS value: "#RRGGBB" or "". */
    function safeColor(c) {
        return /^#[0-9A-Fa-f]{6}$/.test(String(c || "")) ? c : "";
    }

    var api = {
        addDaysIso: addDaysIso,
        eventDays: eventDays,
        bucketEventsByDay: bucketEventsByDay,
        clockLabel: clockLabel,
        eventTimeLabel: eventTimeLabel,
        eventTimeLabelOn: eventTimeLabelOn,
        eventWhenText: eventWhenText,
        eventDetailRows: eventDetailRows,
        safeColor: safeColor,
        shortClock: shortClock,
        dayStripSummary: dayStripSummary,
    };
    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    } else if (typeof window !== "undefined") {
        window.icloudEventHelpers = api;
    }
})();
