/**
 * @jest-environment jsdom
 *
 * Jest tests for #440 — a failed first load says so, with a Retry,
 * instead of a blank page or an empty state that reads like real data.
 */
const H = require("../../../static/load_error_helpers.js");

describe("loadErrorText (#440)", () => {
    test("names what didn't load", () => {
        expect(H.loadErrorText("your goals")).toBe("Couldn't load your goals.");
    });

    test("adds the server's reason", () => {
        expect(H.loadErrorText("your goals", new Error("Database error")))
            .toBe("Couldn't load your goals. Database error.");
    });

    test("doesn't repeat what apiFetch already told the user", () => {
        const err = new Error("Authentication required");
        err.userNotified = true;
        expect(H.loadErrorText("your goals", err)).toBe("Couldn't load your goals.");
    });
});

describe("showLoadError (#440)", () => {
    test("replaces the container's contents with the message and a Retry", () => {
        const box = document.createElement("div");
        box.innerHTML = "<p>Loading...</p>";
        const retry = jest.fn();
        H.showLoadError(box, "completed tasks", new Error("Server error"), retry);
        expect(box.querySelector(".loading-msg, p:not(.load-error-text)")).toBeNull();
        const el = box.querySelector(".load-error");
        expect(el.getAttribute("role")).toBe("alert");
        expect(el.querySelector(".load-error-text").textContent)
            .toBe("Couldn't load completed tasks. Server error.");
        const btn = el.querySelector("button.load-error-retry");
        btn.click();
        expect(retry).toHaveBeenCalledTimes(1);
        expect(btn.disabled).toBe(true);
        expect(btn.textContent).toBe("Retrying…");
    });

    test("no Retry button without a retry function", () => {
        const box = document.createElement("div");
        H.showLoadError(box, "x", null);
        expect(box.querySelector("button")).toBeNull();
    });

    test("the reason is text, never markup", () => {
        const box = document.createElement("div");
        H.showLoadError(box, "x", new Error("<img src=x onerror=alert(1)>"));
        expect(box.querySelector("img")).toBeNull();
    });

    test("clearLoadError removes it; a missing container is a no-op", () => {
        const box = document.createElement("div");
        H.showLoadError(box, "x", null, () => {});
        H.clearLoadError(box);
        expect(box.querySelector(".load-error")).toBeNull();
        expect(H.showLoadError(null, "x", null)).toBeNull();
        expect(() => H.clearLoadError(null)).not.toThrow();
    });
});
