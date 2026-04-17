/** @type {import('jest').Config} */
module.exports = {
  // Unit tests run in Node; DOM tests use jsdom (set per-file via docblock)
  testEnvironment: "node",

  // Test file locations
  testMatch: [
    "<rootDir>/tests/js/**/*.test.js",
  ],

  // Coverage configuration
  collectCoverageFrom: [
    "static/parse_capture.js",
  ],
  coverageDirectory: "coverage-js",
  coverageReporters: ["text", "text-summary"],
};
