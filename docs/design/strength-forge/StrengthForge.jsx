// ─────────────────────────────────────────────
//  Strength Forge — Main App Entry Point
//  Import this component into your existing app
//  and add it to your router or navigation
//
//  Example (React Router):
//    import StrengthForge from "./strength-forge/StrengthForge";
//    <Route path="/strength-forge" element={<StrengthForge />} />
//
//  Example (tab-based app):
//    import StrengthForge from "./strength-forge/StrengthForge";
//    { key: "fitness", label: "Fitness", component: <StrengthForge /> }
// ─────────────────────────────────────────────
import { useState } from "react";
import { COLORS } from "./constants";
import { Modal, WorkSec, Sched, Notes } from "./components";
import { exercises, bandPlanA, bandPlanB, milS1, milS2, milS3, flarePhases, avoidList, warnSigns } from "./exerciseData";

const { ACC1, ACC2, ACC3, ACC4, FIG } = COLORS;

export default function StrengthForge() {
  const [tab,   setTab]   = useState("band");
  const [bw,    setBw]    = useState("A");
  const [ms,    setMs]    = useState("1");
  const [fp,    setFp]    = useState("immediate");
  const [modal, setModal] = useState(null);

  const openModal      = id => { const ex = exercises[id]; if (ex) setModal({ ...ex, id }); };
  const openFlareModal = ex => setModal({ ...ex, title: ex.name });

  const bandPlan = bw === "A" ? bandPlanA : bandPlanB;
  const milPlan  = ms === "1" ? milS1 : ms === "2" ? milS2 : milS3;
  const phase    = flarePhases.find(p => p.id === fp);

  const mainTabs = [
    { key: "band",  label: "⚡ Bands",          color: ACC1 },
    { key: "mil",   label: "🎖 Military",        color: ACC3 },
    { key: "flare", label: "🔴 Flare-Up",        color: ACC4 },
  ];

  return (
    <div style={{ background: "#0a0c0f", minHeight: "100vh", color: FIG, fontFamily: "system-ui, sans-serif" }}>

      <Modal modal={modal} onClose={() => setModal(null)} />

      <div style={{ maxWidth: "840px", margin: "0 auto", padding: "24px 14px 80px" }}>

        {/* ── Header ── */}
        <div style={{ textAlign: "center", marginBottom: "26px" }}>
          <div style={{ fontFamily: "monospace", fontSize: "9px", letterSpacing: "0.25em", color: "#6b7280", textTransform: "uppercase", marginBottom: "5px" }}>
            Personalized Training Program
          </div>
          <div style={{ fontSize: "clamp(30px,8vw,60px)", fontWeight: 900, letterSpacing: "0.02em", lineHeight: 0.9, color: FIG }}>
            STRENGTH FORGE
          </div>
          <div style={{ fontSize: "11px", color: "#6b7280", marginTop: "8px" }}>
            Scott · Age 48+ · HRT-Supported · Back-Safe Protocol
          </div>
        </div>

        {/* ── Profile pills ── */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "5px", justifyContent: "center", marginBottom: "26px" }}>
          {[
            { label: "Beginner",                    t: "n" },
            { label: "2–3 Days/Week",               t: "n" },
            { label: "Under 30 Min",                t: "n" },
            { label: "L4/L5 · L5/S1 Herniation",   t: "w" },
            { label: "HRT Active",                  t: "g" },
            { label: "Testosterone · Anastrozole · DHEA", t: "n" },
            { label: "Weight Loss + Strength",      t: "g" },
          ].map((p, i) => (
            <span key={i} style={{
              fontFamily: "monospace", fontSize: "9px", letterSpacing: "0.1em",
              padding: "3px 9px", borderRadius: "20px", textTransform: "uppercase",
              border: `1px solid ${p.t === "w" ? "rgba(224,82,82,0.4)" : p.t === "g" ? "rgba(82,192,122,0.4)" : "#1e2430"}`,
              color:      p.t === "w" ? ACC4 : p.t === "g" ? ACC2 : "#9ca3af",
              background: p.t === "w" ? "rgba(224,82,82,0.05)" : p.t === "g" ? "rgba(82,192,122,0.05)" : "#111318",
            }}>{p.label}</span>
          ))}
        </div>

        {/* ── Main tabs ── */}
        <div style={{ display: "flex", border: "1px solid #1e2430", borderRadius: "8px", overflow: "hidden", marginBottom: "24px" }}>
          {mainTabs.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)} style={{
              flex: 1, padding: "12px 6px",
              background: tab === t.key ? "rgba(255,255,255,0.03)" : "#111318",
              border: "none", cursor: "pointer",
              fontSize: "clamp(11px,3vw,15px)", fontWeight: 800,
              color: tab === t.key ? t.color : "#6b7280",
              borderBottom: tab === t.key ? `2px solid ${t.color}` : "2px solid transparent",
              transition: "all 0.2s",
            }}>{t.label}</button>
          ))}
        </div>

        {/* ══ BAND PLAN ══════════════════════════════════ */}
        {tab === "band" && (
          <div>
            <div style={{ borderLeft: `3px solid ${ACC1}`, padding: "13px 16px", background: "#111318", borderRadius: "0 8px 8px 0", marginBottom: "22px" }}>
              <div style={{ fontWeight: 800, fontSize: "17px", color: ACC1, marginBottom: "5px" }}>Resistance Band Training</div>
              <div style={{ fontSize: "12px", color: "#9ca3af", lineHeight: 1.7 }}>Full-body strength and fat-loss using resistance bands only. Every exercise protects your L4/L5 and L5/S1 discs. Tap ℹ️ for a diagram, real photo link, and full instructions.</div>
            </div>

            <Sched days={["Full Body A", "Rest", "Full Body B", "Rest", "Full Body A", "Rest / Walk"]} activeColor={ACC1} />

            <div style={{ display: "flex", gap: "8px", marginBottom: "18px" }}>
              {["A", "B"].map(w => (
                <button key={w} onClick={() => setBw(w)} style={{
                  padding: "6px 16px", borderRadius: "6px",
                  border: `1px solid ${bw === w ? ACC1 : "#1e2430"}`,
                  background: bw === w ? "rgba(200,168,75,0.1)" : "#111318",
                  color: bw === w ? ACC1 : "#6b7280",
                  cursor: "pointer", fontWeight: 600, fontSize: "12px",
                }}>Workout {w}</button>
              ))}
            </div>

            {bandPlan.map((s, i) => <WorkSec key={i} {...s} accent={ACC1} onDemo={openModal} />)}

            <Notes color={ACC1} notes={[
              "Never train on consecutive days — your recovery needs that full rest day.",
              "If your lower back flares during any exercise, stop immediately. Switch to the Flare-Up tab.",
              "Start with light bands for the first 2 weeks. Let connective tissue adapt.",
              "Tempo matters more than resistance. Slow, controlled reps build more muscle.",
              "The Pallof Press and Dead Bug are non-negotiable — they protect your discs long-term.",
              "Progress every 2–3 weeks by moving to a heavier band, not rushing more reps.",
              "A 15–20 min walk on rest days improves fat loss and spinal health.",
            ]} />
          </div>
        )}

        {/* ══ MILITARY PLAN ══════════════════════════════ */}
        {tab === "mil" && (
          <div>
            <div style={{ borderLeft: `3px solid ${ACC3}`, padding: "13px 16px", background: "#111318", borderRadius: "0 8px 8px 0", marginBottom: "22px" }}>
              <div style={{ fontWeight: 800, fontSize: "17px", color: ACC3, marginBottom: "5px" }}>Military Calisthenics</div>
              <div style={{ fontSize: "12px", color: "#9ca3af", lineHeight: 1.7 }}>Adapted from military PT — fully modified for L4/L5 and L5/S1 disc protection. No sit-ups, no burpees, no jumping. Tap ℹ️ for a diagram, real photo link, and full instructions.</div>
            </div>

            <Sched days={["Push + Core", "Rest", "Pull + Legs", "Rest", "Full Body", "Walk / Mobility"]} activeColor={ACC3} />

            <div style={{ display: "flex", gap: "6px", marginBottom: "18px", flexWrap: "wrap" }}>
              {[
                { key: "1", label: "Session 1 — Push+Core"  },
                { key: "2", label: "Session 2 — Pull+Legs"  },
                { key: "3", label: "Session 3 — Circuit"    },
              ].map(s => (
                <button key={s.key} onClick={() => setMs(s.key)} style={{
                  padding: "6px 11px", borderRadius: "6px",
                  border: `1px solid ${ms === s.key ? ACC3 : "#1e2430"}`,
                  background: ms === s.key ? "rgba(109,159,232,0.1)" : "#111318",
                  color: ms === s.key ? ACC3 : "#6b7280",
                  cursor: "pointer", fontWeight: 600, fontSize: "11px",
                }}>{s.label}</button>
              ))}
            </div>

            {ms === "3" && (
              <div style={{ background: "#111318", border: "1px solid #1e2430", borderRadius: "8px", padding: "12px 14px", marginBottom: "18px" }}>
                <div style={{ fontWeight: 700, color: ACC3, marginBottom: "5px", fontSize: "12px" }}>Circuit Format</div>
                <div style={{ fontSize: "12px", color: "#9ca3af", lineHeight: 1.65 }}>
                  All 5 exercises back-to-back with <strong style={{ color: FIG }}>20 sec rest</strong> between each.
                  Rest <strong style={{ color: FIG }}>90 sec</strong> after the full circuit.
                  Complete <strong style={{ color: FIG }}>3 rounds</strong> total.
                </div>
              </div>
            )}

            {milPlan.map((s, i) => <WorkSec key={i} {...s} accent={ACC3} onDemo={openModal} />)}

            <Notes color={ACC3} notes={[
              "Sit-ups and crunches are permanently removed — contraindicated for herniated lumbar discs.",
              "Burpees, jump squats, and any plyometric jumping are excluded.",
              "Three sessions done right beats five done sloppy.",
              "The Session 3 circuit is the fat-loss engine of this plan.",
              "Over weeks 5–8, add push-up variations (wide grip, decline) to increase difficulty.",
              "A doorframe pull-up bar unlocks the most powerful back exercise in calisthenics.",
              "Box breathing at the end of every session is part of the recovery protocol — not optional.",
            ]} />
          </div>
        )}

        {/* ══ FLARE-UP PROTOCOL ══════════════════════════ */}
        {tab === "flare" && (
          <div>
            {/* Alert */}
            <div style={{ background: "rgba(224,82,82,0.08)", border: "1px solid rgba(224,82,82,0.3)", borderRadius: "8px", padding: "12px 16px", marginBottom: "22px", display: "flex", gap: "10px", alignItems: "flex-start" }}>
              <span style={{ fontSize: "18px", flexShrink: 0 }}>⚠️</span>
              <div style={{ fontSize: "12px", color: "#fca5a5", lineHeight: 1.65 }}>
                <strong>Stop all normal training immediately during a flare.</strong> Use this protocol instead. Moving gently is better than rest — but loading the spine will extend your flare significantly.
              </div>
            </div>

            {/* Phase selector */}
            <div style={{ display: "flex", gap: "8px", marginBottom: "22px" }}>
              {flarePhases.map(p => (
                <button key={p.id} onClick={() => setFp(p.id)} style={{
                  flex: 1, padding: "10px 6px", borderRadius: "8px",
                  border: `1px solid ${fp === p.id ? p.color + "88" : "#1e2430"}`,
                  background: fp === p.id ? `${p.color}12` : "#111318",
                  color: fp === p.id ? p.color : "#6b7280",
                  cursor: "pointer", fontWeight: 700, fontSize: "11px",
                  textAlign: "center", transition: "all 0.2s",
                }}>
                  <div style={{ fontSize: "18px", marginBottom: "3px" }}>{p.icon}</div>
                  <div style={{ fontFamily: "monospace", fontSize: "9px", marginBottom: "2px" }}>{p.label}</div>
                  <div>{p.title}</div>
                </button>
              ))}
            </div>

            {/* Phase content */}
            {phase && (
              <div>
                <div style={{ borderLeft: `3px solid ${phase.color}`, padding: "13px 16px", background: "#111318", borderRadius: "0 8px 8px 0", marginBottom: "20px" }}>
                  <div style={{ fontWeight: 800, fontSize: "16px", color: phase.color, marginBottom: "4px" }}>{phase.icon} {phase.title} — {phase.subtitle}</div>
                  <div style={{ fontSize: "12px", color: "#9ca3af", lineHeight: 1.7 }}>{phase.desc}</div>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginBottom: "28px" }}>
                  {phase.exercises.map((ex, i) => (
                    <div key={i} style={{ background: "#111318", border: "1px solid #1e2430", borderRadius: "8px", padding: "14px 16px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "10px", marginBottom: "6px" }}>
                        <div style={{ fontWeight: 700, fontSize: "14px", color: FIG }}>{ex.name}</div>
                        <button onClick={() => openFlareModal(ex)} style={{
                          flexShrink: 0, padding: "4px 10px", borderRadius: "6px",
                          border: `1px solid ${phase.color}44`, background: `${phase.color}10`,
                          color: phase.color, cursor: "pointer", fontSize: "11px",
                          fontWeight: 600, whiteSpace: "nowrap",
                        }}>ℹ️ How-to</button>
                      </div>
                      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
                        <div style={{ fontFamily: "monospace", fontSize: "10px", color: ACC1 }}>📊 {ex.duration}</div>
                        <div style={{ fontFamily: "monospace", fontSize: "10px", color: ACC2 }}>⏱ {ex.rest}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Avoid list */}
            <div style={{ marginBottom: "24px" }}>
              <div style={{ fontFamily: "monospace", fontSize: "10px", letterSpacing: "0.15em", color: "#6b7280", textTransform: "uppercase", marginBottom: "12px", display: "flex", alignItems: "center", gap: "10px" }}>
                <span>🚫 Avoid During Any Flare</span>
                <div style={{ flex: 1, height: "1px", background: "#1e2430" }} />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {avoidList.map((a, i) => (
                  <div key={i} style={{ background: "rgba(224,82,82,0.05)", border: "1px solid rgba(224,82,82,0.18)", borderRadius: "8px", padding: "11px 14px" }}>
                    <div style={{ fontWeight: 700, fontSize: "12px", color: ACC4, marginBottom: "3px" }}>✗ {a.item}</div>
                    <div style={{ fontSize: "11px", color: "#6b7280", lineHeight: 1.55 }}>{a.reason}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Warning signs */}
            <div style={{ marginBottom: "20px" }}>
              <div style={{ fontFamily: "monospace", fontSize: "10px", letterSpacing: "0.15em", color: "#6b7280", textTransform: "uppercase", marginBottom: "12px", display: "flex", alignItems: "center", gap: "10px" }}>
                <span>🚨 Seek Help If</span>
                <div style={{ flex: 1, height: "1px", background: "#1e2430" }} />
              </div>
              <div style={{ background: "rgba(224,82,82,0.06)", border: "1px solid rgba(224,82,82,0.25)", borderRadius: "8px", padding: "14px 16px" }}>
                {warnSigns.map((w, i) => (
                  <div key={i} style={{ display: "flex", gap: "10px", alignItems: "flex-start", marginBottom: i < warnSigns.length - 1 ? "10px" : 0 }}>
                    <span style={{ color: ACC4, fontSize: "12px", flexShrink: 0, marginTop: "2px" }}>!</span>
                    <span style={{ fontSize: "12px", color: "#fca5a5", lineHeight: 1.6 }}>{w}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Recovery mindset */}
            <div style={{ padding: "14px 16px", background: "rgba(82,192,122,0.06)", border: "1px solid rgba(82,192,122,0.25)", borderRadius: "8px" }}>
              <div style={{ fontWeight: 700, fontSize: "12px", color: ACC2, marginBottom: "6px" }}>✓ The Recovery Mindset</div>
              <div style={{ fontSize: "12px", color: "#9ca3af", lineHeight: 1.7 }}>
                Most flare-ups resolve in 3–7 days with this protocol. Your HRT support means your tissue repairs faster than average. The McKenzie Press-Up and Glute Bridge are your two most powerful recovery tools — do them every day until you're back to full training. A flare is not a setback, it's a signal to temporarily shift strategy.
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
