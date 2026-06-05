// ─────────────────────────────────────────────
//  Strength Forge — SVG Helpers
//  Shared primitives used by all diagrams
// ─────────────────────────────────────────────
import { COLORS } from "./constants";

const { DIM, FIG, BG } = COLORS;

export function Svg({ children, h = 200 }) {
  return (
    <svg
      viewBox={`0 0 320 ${h}`}
      style={{ width: "100%", background: BG, display: "block" }}
    >
      {children}
    </svg>
  );
}

export function Lbl({ x, y, text, color = DIM, size = 10, anchor = "middle" }) {
  return (
    <text x={x} y={y} textAnchor={anchor} fill={color} fontSize={size} fontFamily="monospace">
      {text}
    </text>
  );
}

export function Arr({ x1, y1, x2, y2, color = COLORS.ACC1, dashed = false }) {
  const dx = x2 - x1, dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy);
  const ux = dx / len, uy = dy / len;
  const hx = x2 - ux * 7, hy = y2 - uy * 7;
  return (
    <g>
      <line
        x1={x1} y1={y1} x2={hx} y2={hy}
        stroke={color} strokeWidth={1.5}
        strokeDasharray={dashed ? "4 3" : undefined}
      />
      <polygon
        points={`${x2},${y2} ${hx - uy * 4},${hy + ux * 4} ${hx + uy * 4},${hy - ux * 4}`}
        fill={color}
      />
    </g>
  );
}

/**
 * Stick-figure helper
 * @param {number} cx        - hip center x
 * @param {number} cy        - hip center y
 * @param {number} headR     - head radius
 * @param {number} torsoH    - torso height
 * @param {number} legL      - leg length
 * @param {number} armAngle  - arm angle in degrees (0 = horizontal)
 * @param {string} color     - stroke color
 * @param {number} legBend   - lateral knee offset (simulates squat bend)
 */
export function Fig({
  cx = 160, cy = 120, headR = 13, torsoH = 38,
  legL = 44, armAngle = 0, color = FIG, legBend = 0,
}) {
  const neck = cy - torsoH;
  const headY = neck - headR;
  const ax = Math.cos((armAngle * Math.PI) / 180) * 30;
  const ay = Math.sin((armAngle * Math.PI) / 180) * 30;
  const kX = legBend, kY = cy + legL * 0.5, fY = cy + legL;
  return (
    <g>
      <circle cx={cx} cy={headY} r={headR} fill="none" stroke={color} strokeWidth={2} />
      <line x1={cx} y1={headY + headR} x2={cx} y2={cy} stroke={color} strokeWidth={2} />
      <line x1={cx} y1={neck + 8} x2={cx - 28 + ax} y2={neck + 8 + ay} stroke={color} strokeWidth={2} />
      <line x1={cx} y1={neck + 8} x2={cx + 28 - ax} y2={neck + 8 - ay} stroke={color} strokeWidth={2} />
      <line x1={cx} y1={cy} x2={cx - kX} y2={kY} stroke={color} strokeWidth={2} />
      <line x1={cx - kX} y1={kY} x2={cx - 8} y2={fY} stroke={color} strokeWidth={2} />
      <line x1={cx} y1={cy} x2={cx + kX} y2={kY} stroke={color} strokeWidth={2} />
      <line x1={cx + kX} y1={kY} x2={cx + 8} y2={fY} stroke={color} strokeWidth={2} />
    </g>
  );
}
