// #502: is this config inside .claude/worktrees/<name>/ ?
const IN_A_WORKTREE = /[\\/]\.claude[\\/]worktrees[\\/]/.test(__dirname);

/** @type {import('jest').Config} */
module.exports = {
  // Unit tests run in Node; DOM tests use jsdom (set per-file via docblock)
  testEnvironment: "node",

  // #459: every test runs in US Eastern (the user's zone, with its DST
  // changes), whatever the machine's own timezone is.
  globalSetup: "./tests/js/global_setup.js",

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

  // #502: that relative glob also matched every NESTED worktree's tests
  // (.claude/worktrees/<name>/tests/js/...) when run from the main
  // checkout — another session's half-done work could fail this gate.
  // Skip them, unless this checkout is itself a worktree (then every path
  // has that segment and the skip would drop all of its own tests).
  testPathIgnorePatterns: IN_A_WORKTREE
    ? ["/node_modules/"]
    : ["/node_modules/", "[\\\\/]\\.claude[\\\\/]worktrees[\\\\/]"],

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
