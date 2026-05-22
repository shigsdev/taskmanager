/** @type {import('jest').Config} */
module.exports = {
  // Unit tests run in Node; DOM tests use jsdom (set per-file via docblock)
  testEnvironment: "node",

  // Test file locations.
  //
  // Use a relative glob instead of `<rootDir>/tests/...`. On Windows when
  // the project lives inside a `.claude/worktrees/...` directory, jest's
  // <rootDir> substitution produces a path with mixed separators
  // (forward slashes from the pattern + backslashes from Node's
  // path.resolve). Micromatch then interprets `\.claude` as an escaped
  // dot and silently matches zero files. The relative pattern bypasses
  // <rootDir> expansion and works on every checkout shape.
  testMatch: [
    "**/tests/js/**/*.test.js",
  ],

  // Coverage configuration (#202). The Jest-tested pure-logic modules:
  // every `*_helpers.js` dual-export plus the standalone ones. Keeps
  // `npm test -- --coverage` honest about what's actually exercised.
  collectCoverageFrom: [
    "static/*_helpers.js",
    "static/api_client.js",
    "static/parse_capture.js",
    "static/task_detail_payload.js",
  ],
  coverageDirectory: "coverage-js",
  coverageReporters: ["text", "text-summary"],
};
