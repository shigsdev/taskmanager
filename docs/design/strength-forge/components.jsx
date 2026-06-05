// ─────────────────────────────────────────────
//  Strength Forge — Shared UI Components
// ─────────────────────────────────────────────
import { COLORS, SAFE_LABELS, SAFE_COLORS, googleLink } from "./constants";
import { diagrams } from "./diagrams";
import { exercises } from "./exerciseData";

const { ACC1, ACC2, ACC3, ACC4, DIM, FIG, BG } = COLORS;

// ── Exercise row (used in workout plans) ──────
export function ExRow({ ex, accent, onDemo }) {
  const info = exercises[ex.id];
  const sc = SAFE_COLORS[info?.safe] ?? DIM;
  return (
    <div style={{ display:"grid", gridTemplateColumns:"40px 1fr auto", alignItems:"start", gap:"10px", padding:"12px 14px", background:"#111318", border:"1px solid #1e2430", borderRadius:"8px" }}>
      <button
        onClick={() => onDemo(ex.id)}
        title="Instructions + demo"
        style={{ width:"34px", height:"34px", borderRadius:"7px", border:"1px solid #2a3040", background:"#181c23", cursor:"pointer", fontSize:"15px", display:"flex", alignItems:"center", justifyContent:"center", flexShrink:0 }}
      >ℹ️</button>
      <div>
        <div style={{ fontWeight:600, fontSize:"13px", color:FIG, marginBottom:"2px" }}>{ex.name}</div>
        {info?.safe && <div style={{ fontSize:"10px", fontFamily:"monospace", color:sc }}>{SAFE_LABELS[info.safe]}</div>}
      </div>
      <div style={{ fontFamily:"monospace", fontSize:"11px", color:accent, whiteSpace:"nowrap", paddingTop:"2px", textAlign:"right" }}>{ex.sets}</div>
    </div>
  );
}

// ── Rest period divider ───────────────────────
export function RestDiv({ text }) {
  return (
    <div style={{ display:"flex", alignItems:"center", gap:"8px", padding:"3px 14px", fontFamily:"monospace", fontSize:"10px", color:DIM }}>
      <div style={{ flex:1, height:"1px", background:"#1e2430" }}/>
      <span>⏱ {text}</span>
      <div style={{ flex:1, height:"1px", background:"#1e2430" }}/>
    </div>
  );
}

// ── Workout section block ─────────────────────
export function WorkSec({ section, badge, badgeColor, num, items, accent, onDemo }) {
  return (
    <div style={{ marginBottom:"22px" }}>
      <div style={{ display:"flex", alignItems:"center", gap:"10px", marginBottom:"10px" }}>
        <div style={{ fontWeight:900, fontSize:"24px", color:"#1e2430", lineHeight:1 }}>{num}</div>
        <div style={{ fontWeight:800, fontSize:"15px", color:FIG }}>{section}</div>
        <div style={{ marginLeft:"auto", fontFamily:"monospace", fontSize:"10px", padding:"3px 9px", borderRadius:"20px", textTransform:"uppercase", background:`${badgeColor}18`, color:badgeColor, border:`1px solid ${badgeColor}33` }}>{badge}</div>
      </div>
      <div style={{ display:"flex", flexDirection:"column" }}>
        {items.map((ex, i) => (
          <div key={i}>
            <ExRow ex={ex} accent={accent} onDemo={onDemo}/>
            {i < items.length - 1 && <RestDiv text={ex.rest}/>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Weekly schedule grid ──────────────────────
export function Sched({ days, activeColor }) {
  return (
    <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:"8px", marginBottom:"22px" }}>
      {days.map((day, i) => {
        const on = [0, 2, 4].includes(i);
        return (
          <div key={i} style={{ background:on?"rgba(255,255,255,0.03)":"#111318", border:`1px solid ${on ? activeColor+"55" : "#1e2430"}`, borderRadius:"8px", padding:"11px 8px", textAlign:"center" }}>
            <div style={{ fontFamily:"monospace", fontSize:"9px", letterSpacing:"0.2em", color:"#6b7280", textTransform:"uppercase", marginBottom:"3px" }}>Day {i+1}</div>
            <div style={{ fontWeight:700, fontSize:"12px", color:on ? activeColor : "#6b7280" }}>{day}</div>
          </div>
        );
      })}
    </div>
  );
}

// ── Key rules notes box ───────────────────────
export function Notes({ notes, color }) {
  return (
    <div style={{ background:"#111318", border:"1px solid #1e2430", borderRadius:"8px", padding:"14px 16px", marginTop:"18px" }}>
      <div style={{ fontWeight:800, fontSize:"12px", color:"#9ca3af", marginBottom:"10px" }}>KEY RULES</div>
      {notes.map((n, i) => (
        <div key={i} style={{ display:"flex", gap:"8px", alignItems:"flex-start", marginBottom:"7px" }}>
          <span style={{ color, fontSize:"11px", marginTop:"2px", flexShrink:0 }}>—</span>
          <span style={{ fontSize:"12px", color:"#6b7280", lineHeight:1.6 }}>{n}</span>
        </div>
      ))}
    </div>
  );
}

// ── Shared modal (workout + flare-up) ─────────
export function Modal({ modal, onClose }) {
  if (!modal) return null;
  const diagramKey = modal.diagramId || modal.id;
  const searchQuery = modal.search || exercises[modal.id]?.search || modal.title || "";
  const sets  = modal.duration || modal.sets  || "";
  const rest  = modal.rest  || "";
  const desc  = modal.how   || modal.desc  || "";
  const tip   = modal.tip   || null;
  const safe  = modal.safe  || null;
  const sc    = SAFE_COLORS[safe] ?? null;

  return (
    <div
      onClick={onClose}
      style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.92)", zIndex:1000, display:"flex", alignItems:"center", justifyContent:"center", padding:"14px", backdropFilter:"blur(8px)" }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{ background:"#111318", border:"1px solid #1e2430", borderRadius:"12px", maxWidth:"440px", width:"100%", maxHeight:"92vh", display:"flex", flexDirection:"column", overflow:"hidden" }}
      >
        {/* Header */}
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"13px 16px", borderBottom:"1px solid #1e2430", flexShrink:0 }}>
          <div style={{ fontWeight:700, fontSize:"14px", color:FIG }}>{modal.title || modal.name}</div>
          <button onClick={onClose} style={{ background:"none", border:"none", color:"#6b7280", fontSize:"20px", cursor:"pointer", lineHeight:1 }}>✕</button>
        </div>

        <div style={{ overflowY:"auto", flex:1 }}>
          {/* SVG diagram */}
          {diagrams[diagramKey] && (
            <div style={{ borderBottom:"1px solid #1e2430" }}>{diagrams[diagramKey]}</div>
          )}

          {/* Google Images link */}
          <div style={{ padding:"12px 16px", borderBottom:"1px solid #1e2430", background:BG }}>
            <a
              href={googleLink(searchQuery)}
              target="_blank"
              rel="noopener noreferrer"
              style={{ display:"flex", alignItems:"center", justifyContent:"center", gap:"10px", padding:"11px 16px", borderRadius:"8px", textDecoration:"none", background:"linear-gradient(135deg,#1a73e8,#0d5bba)", color:"#fff", fontWeight:700, fontSize:"13px", boxShadow:"0 2px 12px rgba(26,115,232,0.3)" }}
            >
              <span>🔍</span>
              <span>See Real Photos — Google Images</span>
              <span style={{ opacity:0.7 }}>↗</span>
            </a>
            <div style={{ textAlign:"center", marginTop:"6px", fontSize:"10px", fontFamily:"monospace", color:"#4b5563" }}>opens in browser · real photos &amp; GIFs</div>
          </div>

          {/* Info */}
          <div style={{ padding:"13px 16px" }}>
            {safe && sc && (
              <div style={{ display:"inline-flex", alignItems:"center", gap:"6px", padding:"3px 10px", borderRadius:"20px", marginBottom:"10px", background:`${sc}18`, border:`1px solid ${sc}44`, fontFamily:"monospace", fontSize:"10px", color:sc, letterSpacing:"0.08em" }}>
                {SAFE_LABELS[safe]}
              </div>
            )}
            <div style={{ fontFamily:"monospace", fontSize:"11px", color:ACC1, marginBottom:"4px" }}>📊 {sets}</div>
            <div style={{ fontFamily:"monospace", fontSize:"11px", color:ACC2, marginBottom:"10px" }}>⏱ {rest}</div>
            <div style={{ fontWeight:700, fontSize:"11px", color:"#9ca3af", marginBottom:"6px", textTransform:"uppercase", letterSpacing:"0.05em" }}>How to do it</div>
            <div style={{ fontSize:"13px", color:"#9ca3af", lineHeight:"1.75", marginBottom:tip ? "12px" : 0 }}>{desc}</div>
            {tip && (
              <div style={{ padding:"10px 12px", background:"rgba(200,168,75,0.08)", border:"1px solid rgba(200,168,75,0.25)", borderRadius:"8px", fontSize:"12px", color:ACC1, lineHeight:1.6 }}>
                💡 {tip}
              </div>
            )}
            {safe === "monitor" && (
              <div style={{ marginTop:"12px", padding:"10px 12px", background:"rgba(224,82,82,0.08)", border:"1px solid rgba(224,82,82,0.3)", borderRadius:"8px", fontSize:"12px", color:ACC4, lineHeight:1.6 }}>
                ⚠ Stop immediately and replace with Glute Bridge if any lower back or disc pain occurs.
              </div>
            )}
            {safe === "therapeutic" && (
              <div style={{ marginTop:"12px", padding:"10px 12px", background:"rgba(82,192,122,0.08)", border:"1px solid rgba(82,192,122,0.3)", borderRadius:"8px", fontSize:"12px", color:ACC2, lineHeight:1.6 }}>
                ✓ Specifically recommended for L4/L5 and L5/S1 herniated discs. Do not skip this exercise.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
