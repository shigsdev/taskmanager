# Strength Forge — Developer Context & Integration Guide

> **Purpose:** This document gives Claude Code (or any developer) the full context needed to integrate the Strength Forge fitness app into an existing React application. Read this before touching any of the component files.

---

## 1. What This App Is

**Strength Forge** is a personalized fitness application built for a specific user (Scott) with the following characteristics:

- **Age:** 48+
- **Condition:** Two herniated discs at **L4/L5 and L5/S1** — this is a hard constraint that shapes every single exercise choice
- **Fitness level:** Beginner (little to no recent training)
- **Schedule:** 2–3 days/week, sessions under 30 minutes
- **Equipment:** Resistance bands and bodyweight only — no gym access
- **Goals:** Weight loss + strength building
- **Health context:** On hormone replacement therapy (Testosterone, Anastrozole, DHEA) — supports faster recovery and muscle building than typical for age
- **Lifestyle:** High stress, 5–6 hours disrupted sleep, sedentary desk job, young child

The app has **three tabs:**

| Tab | Description |
|-----|-------------|
| ⚡ Resistance Bands | Two rotating full-body workouts (A and B), alternating across 2–3 training days |
| 🎖 Military Calisthenics | Three sessions: Push+Core, Pull+Legs, Full Body Circuit — military PT adapted for disc safety |
| 🔴 Flare-Up Protocol | Three-phase recovery protocol (Acute → Recovery → Return to Training) for when the back flares |

---

## 2. Non-Negotiable Design Rules

These rules must **never** be violated when modifying exercise content:

### Permanently Excluded Movements
These are removed from all plans regardless of context:
- ❌ Sit-ups and crunches (spinal flexion under load — worst for herniated discs)
- ❌ Burpees (high spinal impact on landing)
- ❌ Jump squats and all plyometric jumping
- ❌ Full deadlifts (high spinal compression)
- ❌ Forward lunges (excessive trunk lean — reverse lunges are used instead)
- ❌ Any rotation under load

### Depth Restrictions
- Squats: **60–70% depth maximum** during normal training, **50% during flare**
- Romanian deadlift hinge: **30–40° maximum** — not a full RDL

### Core Exercises — Always Include
These two exercises must appear in every main workout session:
- **Pallof Press** — anti-rotation core, the safest core exercise for herniated discs
- **Dead Bug** — approved in herniated disc rehabilitation protocols

### The Golden Rule
> If any exercise causes pain radiating down the leg (sciatica), it must stop immediately. Leg pain = nerve compression = stop.

---

## 3. File Structure

```
strength-forge/
├── constants.js          # Colors, safe labels, Google link helper
├── SvgHelpers.jsx        # Svg, Lbl, Arr, Fig (stick figure) components
├── diagrams.jsx          # All 30 inline SVG exercise diagrams (keyed by exercise ID)
├── exerciseData.js       # Exercise metadata + all workout plan structures + flare-up data
├── components.jsx        # ExRow, RestDiv, WorkSec, Sched, Notes, Modal (shared UI)
├── StrengthForge.jsx     # Main app entry point — import this into your router
└── CONTEXT.md            # This file
```

### Import chain
```
StrengthForge.jsx
  ├── constants.js
  ├── components.jsx
  │     ├── constants.js
  │     ├── diagrams.jsx
  │     │     ├── constants.js
  │     │     └── SvgHelpers.jsx
  │     └── exerciseData.js
  └── exerciseData.js
```

---

## 4. How to Integrate Into Your Existing App

### Step 1 — Copy the folder
Copy the entire `strength-forge/` folder into your project's `src/` directory:
```
your-app/src/strength-forge/
```

### Step 2 — Add a route (React Router example)
```jsx
import StrengthForge from "./strength-forge/StrengthForge";

// In your router:
<Route path="/strength-forge" element={<StrengthForge />} />
```

### Step 3 — Add to navigation
```jsx
// Tab-based nav example:
{ key: "fitness", label: "💪 Strength Forge", path: "/strength-forge" }

// Bottom nav example (mobile):
<NavItem icon="💪" label="Workout" href="/strength-forge" />
```

### Step 4 — Check for conflicts
Run a quick check before integrating:
```bash
# Check for naming conflicts with your existing components
grep -r "ExRow\|WorkSec\|RestDiv\|Sched\|Modal" src/ --include="*.jsx" --include="*.js"
```

If conflicts exist, rename the imports in `StrengthForge.jsx` and `components.jsx`. All components are named clearly and prefixed where needed.

### Step 5 — Verify it renders
```bash
npm start
# Navigate to /strength-forge
```

---

## 5. Theming & Styling

The app uses **inline styles only** — no CSS files, no Tailwind, no styled-components. This means:
- ✅ Zero risk of CSS conflicts with your existing app
- ✅ Works in any React project regardless of CSS setup
- ✅ Self-contained — just works

### Color tokens (from `constants.js`)
```js
ACC1: "#c8a84b"  // Gold — resistance band accent, sets/reps display
ACC2: "#52c07a"  // Green — therapeutic exercises, safe indicators, arrows
ACC3: "#6d9fe8"  // Blue — military plan, cool-down badges
ACC4: "#e05252"  // Red — flare-up protocol, warnings, disc risk callouts
FIG:  "#e8eaf0"  // Off-white — body text, stick figure strokes
BG:   "#0d1117"  // Near-black — SVG diagram backgrounds
```

To retheme the app, update these values in `constants.js` and all diagrams and UI will update automatically.

---

## 6. SVG Diagrams

All 30 exercise diagrams are **fully inline SVG** — no external image URLs, no CDN dependencies, no network requests. They will always render regardless of network conditions.

Each diagram:
- Uses the `Svg`, `Lbl`, `Arr`, and `Fig` primitives from `SvgHelpers.jsx`
- Is keyed by the exercise ID string (e.g. `"glute-bridge"`, `"dead-bug"`)
- Includes form cues, movement arrows, and safety warnings baked into the graphic
- Color codes therapeutic exercises (green) and disc-risk warnings (red)

### Diagrams list
**Workout exercises (24):**
`cat-cow`, `band-pull-apart`, `band-squat`, `band-row`, `band-chest-press`, `glute-bridge`, `lateral-walk`, `pallof-press`, `dead-bug`, `face-pull`, `band-rdl`, `band-ohp`, `band-curl`, `band-tricep`, `incline-pushup`, `pike-pushup`, `diamond-pushup`, `plank`, `australian-pullup`, `bw-squat`, `reverse-lunge`, `glute-bridge-single`, `box-breathing`, `arm-swings`, `leg-swings`

**Flare-up specific (5):**
`mckenzie`, `knee-hug`, `walking`, `pelvic-tilt`, `dead-bug-arms`

To add a new diagram, add a new key to the `diagrams` object in `diagrams.jsx` using the same SVG primitives.

---

## 7. Exercise Modal System

Tapping ℹ️ on any exercise opens a modal containing:
1. **SVG diagram** — the inline illustration for that exercise
2. **Google Images button** — opens a pre-built image search in the browser (links are generated dynamically via `googleLink()` in `constants.js`)
3. **Safe label badge** — color coded: therapeutic (green), back-safe (blue), monitor (red), recovery (purple)
4. **Sets and rest times**
5. **Step-by-step form instructions**
6. **Tip box** (flare-up exercises)
7. **Disc warning box** (for exercises tagged `monitor`)
8. **Therapeutic callout box** (for exercises tagged `therapeutic`)

The same `Modal` component handles both workout exercises and flare-up exercises — it reads `modal.diagramId` for flare-up diagrams and `modal.id` for workout diagrams.

---

## 8. Flare-Up Protocol — Clinical Background

This section is clinically grounded. When integrating, **do not reorder or remove these phases:**

### 🔴 Day 1–2: Acute Phase
- Inflammation at peak
- **McKenzie Press-Up** is the #1 recommended exercise for L4/L5 and L5/S1 — pushes disc material back toward center
- Centralization of pain (moving from leg toward spine) is a positive sign
- No loading of any kind

### 🟡 Day 3–5: Recovery Phase
- Reactivate glutes and deep core
- **Glute Bridge at 50% range** — glute weakness is a primary driver of disc stress
- **Dead Bug arms-only** — skips leg extension to avoid lumbar load
- Walking increases to 15–20 min

### 🟢 Day 6+: Return to Training
- **50% intensity on first session back** — non-negotiable
- McKenzie Press-Up continues as a maintenance dose for 2 weeks post-flare
- Full Dead Bug and Pallof Press confirm core readiness before resuming all exercises

### Warning signs requiring medical attention
- Pain or weakness spreading down both legs
- Loss of bladder or bowel control (emergency)
- Numbness in groin or inner thigh (saddle area)
- No improvement after 5–7 days

---

## 9. Adding or Modifying Exercises

### To add a new exercise to a workout plan:

**1. Add to `exerciseData.js`:**
```js
"my-exercise": {
  title: "My Exercise",
  search: "my exercise how to form",  // Used for Google Images link
  sets: "3 × 12",
  rest: "45 sec between sets",
  desc: "Step by step form description here.",
  safe: "back-safe",  // "therapeutic" | "back-safe" | "monitor" | "recovery"
},
```

**2. Add a diagram to `diagrams.jsx`:**
```jsx
"my-exercise": (
  <Svg h={200}>
    <Lbl x={160} y={16} text="MY EXERCISE" color={ACC1} size={11}/>
    <Fig cx={160} cy={140}/>
    {/* Add Arr and Lbl components for form cues */}
  </Svg>
),
```

**3. Add to a workout plan array in `exerciseData.js`:**
```js
{ id: "my-exercise", name: "My Exercise", sets: "3 × 12", rest: "45s sets · 30s next" },
```

### Safe tags explained
| Tag | Meaning | Visual |
|-----|---------|--------|
| `therapeutic` | Specifically good for herniated discs — should not be skipped | 🟢 Green |
| `back-safe` | Standard safe movement for disc conditions | 🔵 Blue |
| `monitor` | Use with caution — stop if disc pain occurs | 🔴 Red |
| `recovery` | Recovery/breathing — end of session | 🟣 Purple |

---

## 10. Claude Code Prompt Templates

Use these prompts directly in Claude Code for common tasks:

### Merge into existing app
```
I have a fitness component in src/strength-forge/StrengthForge.jsx.
My existing app uses [React Router v6 / Next.js App Router / tab-based navigation].
My existing nav component is at [path].
Please add Strength Forge as a new route/tab and wire it into the navigation.
Keep all existing routes intact.
```

### Add a new exercise
```
Add a new exercise to Strength Forge called "[Exercise Name]".
It should go in [band plan A / band plan B / military session 1/2/3].
Safe classification: [therapeutic / back-safe / monitor].
Sets and rest: [e.g. 3 × 12, 45 sec rest].
Description: [form description].
Also create an inline SVG diagram for it in diagrams.jsx using the existing Svg/Lbl/Arr/Fig primitives.
```

### Add a new flare-up exercise
```
Add a new exercise to the flare-up protocol's [acute / recovery / return] phase.
Exercise name: [name].
Clinical rationale: [why it's appropriate for herniated discs].
Create a diagram keyed as "[diagram-id]" in diagrams.jsx.
```

### Retheme the app
```
Retheme Strength Forge to match our existing app's design system.
Our primary color is [hex].
Our success/positive color is [hex].
Our danger/warning color is [hex].
Our background is [hex].
Update constants.js and verify all diagrams and UI reflect the new colors.
```

### Convert to TypeScript
```
Convert all Strength Forge component files to TypeScript.
Add proper types for all props, exercise data objects, and flare-up phase objects.
Export all types from a new types.ts file.
Keep all functionality identical.
```

---

## 11. Known Constraints & Decisions

| Decision | Reason |
|----------|--------|
| Inline styles only | Zero CSS conflict risk with any host app |
| No external image URLs | Claude.ai sandbox blocks external fetches; all diagrams are self-contained SVG |
| Google Images links instead of embedded images | Most reliable cross-environment approach for photo references |
| Box breathing at end of every session | Clinically reduces cortisol — critical given high stress lifestyle |
| No consecutive training days | Limited sleep (5–6 hrs) constrains recovery capacity |
| Pallof Press + Dead Bug non-negotiable | These two exercises are the primary disc protection movements — they must not be removed |
| RDL tagged `monitor` not `back-safe` | 30–40° hinge is generally safe but requires careful monitoring given L5/S1 position |
| Military plan excludes sit-ups permanently | Lumbar flexion under load is the primary mechanism of disc herniation aggravation |

---

## 12. File Sizes (approximate)

| File | Lines | Purpose |
|------|-------|---------|
| `StrengthForge.jsx` | ~280 | Main app, tabs, state management |
| `components.jsx` | ~180 | All shared UI components |
| `exerciseData.js` | ~340 | All exercise data + workout plans + flare-up data |
| `diagrams.jsx` | ~430 | All 30 SVG diagrams |
| `SvgHelpers.jsx` | ~60 | SVG primitives |
| `constants.js` | ~30 | Colors and utilities |

---

*Last updated: Built in conversation with Claude, June 2026*
*User: the operator · L4/L5 + L5/S1 herniated discs · HRT protocol active (home location redacted before commit)*
