/**
 * #460: one label for a repeat rule, used by the board card badge, the
 * recurring previews, the /recurring list and the voice memo row. They each
 * had their own map and showed raw values ("monthly_nth_weekday", a weekday
 * number) or nothing ("Repeat") for some frequencies.
 */
const { repeatLabel } = require("../../../static/recurring_helpers.js");

describe("repeatLabel (#460)", () => {
    test("every frequency the server has gets a name (no raw value)", () => {
        const all = ["daily", "weekdays", "weekly", "day_of_week",
            "multi_day_of_week", "monthly_date", "monthly_nth_weekday"];
        for (const f of all) {
            const full = repeatLabel({ frequency: f });
            const short = repeatLabel({ frequency: f }, { short: true });
            expect(full).not.toMatch(/_/);
            expect(short).not.toMatch(/_/);
            expect(full).not.toBe("Repeats");
        }
    });

    test("with the day fields: the details", () => {
        expect(repeatLabel({ frequency: "daily" })).toBe("Daily");
        expect(repeatLabel({ frequency: "weekdays" })).toBe("Weekdays");
        expect(repeatLabel({ frequency: "weekly", day_of_week: 0 })).toBe("Weekly on Mon");
        expect(repeatLabel({ frequency: "day_of_week", day_of_week: 6 })).toBe("Weekly on Sun");
        expect(repeatLabel({ frequency: "multi_day_of_week", days_of_week: [0, 2, 4] }))
            .toBe("Weekly on Mon, Wed, Fri");
        expect(repeatLabel({ frequency: "monthly_date", day_of_month: 15 })).toBe("Monthly on the 15th");
        expect(repeatLabel({ frequency: "monthly_nth_weekday", week_of_month: 2, day_of_week: 1 }))
            .toBe("Monthly on the 2nd Tue");
    });

    test("ordinals", () => {
        const d = (n) => repeatLabel({ frequency: "monthly_date", day_of_month: n });
        expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 31].map(d)).toEqual([
            "Monthly on the 1st", "Monthly on the 2nd", "Monthly on the 3rd", "Monthly on the 4th",
            "Monthly on the 11th", "Monthly on the 12th", "Monthly on the 13th",
            "Monthly on the 21st", "Monthly on the 22nd", "Monthly on the 23rd", "Monthly on the 31st",
        ]);
    });

    test("without the day fields (a preview): the dropdown's names", () => {
        expect(repeatLabel({ frequency: "weekly" })).toBe("Weekly");
        expect(repeatLabel({ frequency: "multi_day_of_week" })).toBe("Specific weekdays");
        expect(repeatLabel({ frequency: "multi_day_of_week", days_of_week: [] })).toBe("Specific weekdays");
        expect(repeatLabel({ frequency: "monthly_date" })).toBe("Monthly (same date)");
        expect(repeatLabel({ frequency: "monthly_nth_weekday" })).toBe("Monthly (nth weekday)");
    });

    test("short: just the kind, for a card badge", () => {
        const s = (r) => repeatLabel(r, { short: true });
        expect(s({ frequency: "weekly", day_of_week: 0 })).toBe("Weekly");
        expect(s({ frequency: "day_of_week", day_of_week: 3 })).toBe("Weekly");
        expect(s({ frequency: "multi_day_of_week", days_of_week: [5, 6] })).toBe("Specific weekdays");
        expect(s({ frequency: "monthly_date", day_of_month: 3 })).toBe("Monthly");
        expect(s({ frequency: "monthly_nth_weekday", week_of_month: 1, day_of_week: 0 })).toBe("Monthly");
        expect(s({ frequency: "weekdays" })).toBe("Weekdays");
    });

    test("out-of-range or missing values never print raw", () => {
        expect(repeatLabel({ frequency: "weekly", day_of_week: 9 })).toBe("Weekly");
        expect(repeatLabel({ frequency: "monthly_nth_weekday", week_of_month: 2 })).toBe("Monthly (nth weekday)");
        expect(repeatLabel({ frequency: "multi_day_of_week", days_of_week: [0, 12] })).toBe("Weekly on Mon");
        expect(repeatLabel({ frequency: "something_new" })).toBe("Repeats");
        expect(repeatLabel(null)).toBe("Repeats");
        expect(repeatLabel(undefined, { short: true })).toBe("Repeats");
    });
});
