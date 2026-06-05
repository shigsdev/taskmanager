// ─────────────────────────────────────────────
//  Strength Forge — Shared Constants
// ─────────────────────────────────────────────

export const COLORS = {
  ACC1: "#c8a84b",   // gold — resistance band accent
  ACC2: "#52c07a",   // green — safe / therapeutic
  ACC3: "#6d9fe8",   // blue — military / cool-down
  ACC4: "#e05252",   // red — warning / flare-up
  DIM:  "#374151",   // dark muted
  FIG:  "#e8eaf0",   // figure / text
  BG:   "#0d1117",   // diagram background
};

export const SAFE_LABELS = {
  therapeutic: "✓ therapeutic",
  "back-safe": "✓ back-safe",
  monitor:     "⚠ monitor carefully",
  recovery:    "✓ recovery",
};

export const SAFE_COLORS = {
  therapeutic: COLORS.ACC2,
  "back-safe": COLORS.ACC3,
  monitor:     COLORS.ACC4,
  recovery:    "#a78bfa",
};

export function googleLink(query) {
  return `https://www.google.com/search?q=${encodeURIComponent(
    query + " exercise how to form"
  )}&tbm=isch`;
}
