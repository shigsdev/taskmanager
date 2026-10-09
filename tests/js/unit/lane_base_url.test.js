/**
 * #402: each Playwright worker talks to its own local server ("lane"), chosen
 * by its parallelIndex, so no two concurrent workers ever share a DB.
 */
const { laneBaseURL } = require("../../lane_base_url");

describe("laneBaseURL (#402)", () => {
    test("lane i targets port base + i", () => {
        expect(laneBaseURL("http://127.0.0.1:5111", 0, "5111")).toBe("http://127.0.0.1:5111");
        expect(laneBaseURL("http://127.0.0.1:5111", 3, "5111")).toBe("http://127.0.0.1:5114");
        expect(laneBaseURL("http://127.0.0.1:5111", 7, 5111)).toBe("http://127.0.0.1:5118");
    });

    test("without the gate's lane env the configured URL is kept (plain local run)", () => {
        expect(laneBaseURL("http://127.0.0.1:5111", 2, undefined)).toBe("http://127.0.0.1:5111");
        expect(laneBaseURL("http://127.0.0.1:5111", 2, "")).toBe("http://127.0.0.1:5111");
    });

    test("the prod project's URL is never rewritten", () => {
        const prod = "https://web-production-3e3ae.up.railway.app";
        expect(laneBaseURL(prod, 2, "5111")).toBe(prod);
    });

    test("an unset baseURL stays unset", () => {
        expect(laneBaseURL(undefined, 1, "5111")).toBeUndefined();
    });

    test("a non-numeric lane port is ignored rather than producing a bad URL", () => {
        expect(laneBaseURL("http://127.0.0.1:5111", 1, "abc")).toBe("http://127.0.0.1:5111");
    });
});
