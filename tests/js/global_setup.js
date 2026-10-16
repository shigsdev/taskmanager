/**
 * #459: run every Jest test in the user's timezone. Jest calls this once,
 * in the parent process, before it starts the test workers — and the
 * workers inherit process.env, so TZ is set before any Date exists. Node
 * re-reads TZ when it changes, which also covers --runInBand (one process).
 * tests/js/unit/timezone_pin.test.js checks it took.
 */
module.exports = async () => {
    process.env.TZ = "America/New_York";
};
