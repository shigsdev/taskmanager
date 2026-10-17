/**
 * Jest unit tests for static/icloud_event_helpers.js (#371): iCloud
 * Calendar events on /calendar. Events arrive from /api/icloud/events with
 * times already in the app's zone ("2026-10-20T09:30-04:00") and all-day
 * ends exclusive ("2026-10-22" .. "2026-10-24" is two days).
 */
const {
    addDaysIso,
    eventDays,
    bucketEventsByDay,
    clockLabel,
    eventTimeLabel,
    eventTimeLabelOn,
    eventWhenText,
    eventDetailRows,
    safeColor,
    shortClock,
    dayStripSummary,
} = require("../../../static/icloud_event_helpers");

function ev(over) {
    return Object.assign({
        uid: "u", title: "Dentist", start: "2026-10-20T09:30-04:00",
        end: "2026-10-20T10:30-04:00", all_day: false, location: "",
        calendar: "Home", color: "#1BADF8",
    }, over);
}

describe("addDaysIso", () => {
    test("crosses a month and a year", () => {
        expect(addDaysIso("2026-10-31", 1)).toBe("2026-11-01");
        expect(addDaysIso("2026-12-31", 1)).toBe("2027-01-01");
        expect(addDaysIso("2026-03-01", -1)).toBe("2026-02-28");
    });
    test("ignores the DST change (date math, not clock math)", () => {
        expect(addDaysIso("2026-11-01", 1)).toBe("2026-11-02");
    });
});

describe("eventDays", () => {
    test("a timed event is on its start day", () => {
        expect(eventDays(ev())).toEqual(["2026-10-20"]);
    });
    test("an all-day event's end is exclusive", () => {
        expect(eventDays(ev({ all_day: true, start: "2026-10-22", end: "2026-10-24" })))
            .toEqual(["2026-10-22", "2026-10-23"]);
        expect(eventDays(ev({ all_day: true, start: "2026-10-22", end: "2026-10-23" })))
            .toEqual(["2026-10-22"]);
    });
    test("an all-day event with no usable end is one day", () => {
        expect(eventDays(ev({ all_day: true, start: "2026-10-22", end: "2026-10-22" })))
            .toEqual(["2026-10-22"]);
    });
    test("a timed event past midnight shows on both days", () => {
        expect(eventDays(ev({ start: "2026-10-20T22:00-04:00", end: "2026-10-21T01:00-04:00" })))
            .toEqual(["2026-10-20", "2026-10-21"]);
    });
    test("a timed event ending exactly at midnight stays on its day", () => {
        expect(eventDays(ev({ start: "2026-10-20T22:00-04:00", end: "2026-10-21T00:00-04:00" })))
            .toEqual(["2026-10-20"]);
    });
    test("a runaway span is capped", () => {
        const days = eventDays(ev({ all_day: true, start: "2026-01-01", end: "2027-01-01" }));
        expect(days.length).toBe(70);
    });
    test("an unreadable start is no days", () => {
        expect(eventDays(ev({ start: "" }))).toEqual([]);
        expect(eventDays(null)).toEqual([]);
    });
});

describe("bucketEventsByDay", () => {
    test("each event lands on its days, inside the grid only", () => {
        const trip = ev({ uid: "t", title: "Trip", all_day: true, start: "2026-10-31", end: "2026-11-03" });
        const by = bucketEventsByDay([ev(), trip], "2026-10-19", "2026-11-01");
        expect(by["2026-10-20"].map((e) => e.title)).toEqual(["Dentist"]);
        expect(by["2026-10-31"].map((e) => e.title)).toEqual(["Trip"]);
        expect(by["2026-11-01"].map((e) => e.title)).toEqual(["Trip"]);
        expect(by["2026-11-02"]).toBeUndefined();
    });
    test("all-day events come first, then by time, then title", () => {
        const by = bucketEventsByDay([
            ev({ uid: "b", title: "B late", start: "2026-10-20T15:00-04:00" }),
            ev({ uid: "a", title: "A early", start: "2026-10-20T08:00-04:00" }),
            ev({ uid: "d", title: "Holiday", all_day: true, start: "2026-10-20", end: "2026-10-21" }),
        ], "2026-10-19", "2026-11-01");
        expect(by["2026-10-20"].map((e) => e.title)).toEqual(["Holiday", "A early", "B late"]);
    });
    test("nothing in, nothing out", () => {
        expect(bucketEventsByDay([], "2026-10-19", "2026-11-01")).toEqual({});
        expect(bucketEventsByDay(null, "2026-10-19", "2026-11-01")).toEqual({});
    });
});

describe("clock + labels", () => {
    test.each([
        ["00:00", "12:00 AM"], ["09:05", "9:05 AM"], ["12:00", "12:00 PM"],
        ["12:30", "12:30 PM"], ["13:15", "1:15 PM"], ["23:59", "11:59 PM"],
    ])("clockLabel(%s) = %s", (hhmm, want) => {
        expect(clockLabel(hhmm)).toBe(want);
    });
    test("clockLabel of junk is empty", () => {
        expect(clockLabel("nope")).toBe("");
    });
    test("time label: the start, or All day", () => {
        expect(eventTimeLabel(ev())).toBe("9:30 AM");
        expect(eventTimeLabel(ev({ all_day: true, start: "2026-10-20", end: "2026-10-21" }))).toBe("All day");
    });
});

describe("eventTimeLabelOn (the label on one day's line)", () => {
    const redEye = ev({ start: "2026-10-22T22:00-04:00", end: "2026-10-23T06:30-04:00" });
    const long = ev({ start: "2026-10-22T22:00-04:00", end: "2026-10-24T09:00-04:00" });
    test("its first day shows the start", () => {
        expect(eventTimeLabelOn(redEye, "2026-10-22")).toBe("10:00 PM");
    });
    test("its last day shows when it ends, not the start again", () => {
        expect(eventTimeLabelOn(redEye, "2026-10-23")).toBe("until 6:30 AM");
    });
    test("a day in the middle is all day", () => {
        expect(eventTimeLabelOn(long, "2026-10-23")).toBe("all day");
    });
    test("an all-day event has no time on any day", () => {
        expect(eventTimeLabelOn(ev({ all_day: true, start: "2026-10-22", end: "2026-10-24" }), "2026-10-23")).toBe("");
    });
    test("a same-day event is its start", () => {
        expect(eventTimeLabelOn(ev(), "2026-10-20")).toBe("9:30 AM");
    });
});

describe("eventWhenText", () => {
    test("same-day timed", () => {
        expect(eventWhenText(ev())).toBe("Tue, Oct 20 · 9:30 AM – 10:30 AM");
    });
    test("timed with no length", () => {
        expect(eventWhenText(ev({ end: "2026-10-20T09:30-04:00" }))).toBe("Tue, Oct 20 · 9:30 AM");
    });
    test("timed over midnight names both days", () => {
        expect(eventWhenText(ev({ start: "2026-10-20T22:00-04:00", end: "2026-10-21T01:00-04:00" })))
            .toBe("Tue, Oct 20, 10:00 PM – Wed, Oct 21, 1:00 AM");
    });
    test("one all-day day", () => {
        expect(eventWhenText(ev({ all_day: true, start: "2026-10-22", end: "2026-10-23" })))
            .toBe("All day · Thu, Oct 22");
    });
    test("several all-day days show the last day, not the exclusive end", () => {
        expect(eventWhenText(ev({ all_day: true, start: "2026-10-22", end: "2026-10-24" })))
            .toBe("All day · Thu, Oct 22 – Fri, Oct 23");
    });
});

describe("eventDetailRows", () => {
    test("when, where and calendar", () => {
        expect(eventDetailRows(ev({ location: "12 Main St" }))).toEqual([
            { label: "When", value: "Tue, Oct 20 · 9:30 AM – 10:30 AM" },
            { label: "Where", value: "12 Main St" },
            { label: "Calendar", value: "Home" },
        ]);
    });
    test("no location, no Where row", () => {
        expect(eventDetailRows(ev()).map((r) => r.label)).toEqual(["When", "Calendar"]);
    });
});

describe("#498 shortClock", () => {
    test.each([
        ["09:30", "9:30am"], ["14:00", "2pm"], ["00:00", "12am"],
        ["12:15", "12:15pm"], ["nope", ""],
    ])("shortClock(%s) = %s", (hhmm, want) => {
        expect(shortClock(hhmm)).toBe(want);
    });
});

describe("#498 dayStripSummary (the board's day box)", () => {
    const D = "2026-10-20";
    test("no events, nothing", () => {
        expect(dayStripSummary([], D)).toBeNull();
        expect(dayStripSummary(undefined, D)).toBeNull();
    });
    test("first event with a compact time, and how many more", () => {
        const s = dayStripSummary([
            ev({ title: "Dentist", start: `${D}T09:30-04:00`, end: `${D}T10:30-04:00` }),
            ev({ uid: "b", title: "Call", start: `${D}T14:00-04:00`, end: `${D}T15:00-04:00` }),
            ev({ uid: "c", title: "Gym", start: `${D}T18:00-04:00`, end: `${D}T19:00-04:00` }),
        ], D);
        expect(s.text).toBe("9:30am Dentist");
        expect(s.more).toBe(2);
        expect(s.label).toBe("iCloud: 9:30 AM Dentist and 2 more — open the calendar");
        expect(s.title).toBe("9:30 AM Dentist\n2:00 PM Call\n6:00 PM Gym");
    });
    test("an all-day first event is just its title", () => {
        const s = dayStripSummary([ev({ all_day: true, start: D, end: "2026-10-21", title: "Offsite" })], D);
        expect(s.text).toBe("Offsite");
        expect(s.more).toBe(0);
        expect(s.label).toBe("iCloud: All day Offsite — open the calendar");
    });
    test("a red-eye's second day reads until its end", () => {
        const s = dayStripSummary([ev({ title: "Red-eye", start: "2026-10-19T22:00-04:00",
            end: `${D}T06:30-04:00` })], D);
        expect(s.text).toBe("until 6:30am Red-eye");
    });
});

describe("safeColor", () => {
    test("a hex color passes", () => {
        expect(safeColor("#1BADF8")).toBe("#1BADF8");
    });
    test.each(["", null, "red", "#12345", "#1234567", "url(x)", "#12345g"])("%p is dropped", (c) => {
        expect(safeColor(c)).toBe("");
    });
});
