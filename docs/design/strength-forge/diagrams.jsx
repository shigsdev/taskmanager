// ─────────────────────────────────────────────
//  Strength Forge — Exercise Diagrams
//  All inline SVG diagrams, keyed by exercise ID
//  No external URLs — guaranteed to render anywhere
// ─────────────────────────────────────────────
import { COLORS } from "./constants";
import { Svg, Lbl, Arr, Fig } from "./SvgHelpers";

const { ACC1, ACC2, ACC3, ACC4, DIM, FIG, BG } = COLORS;

export const diagrams = {

  "cat-cow": (
    <Svg h={185}>
      <Lbl x={160} y={16} text="CAT-COW STRETCH" color={ACC1} size={11}/>
      <path d="M 60 88 Q 160 68 260 88" fill="none" stroke={ACC2} strokeWidth={2} strokeDasharray="5 3"/>
      <path d="M 60 88 Q 160 110 260 88" fill="none" stroke={ACC3} strokeWidth={2} strokeDasharray="5 3"/>
      <circle cx={65} cy={93} r={5} fill="none" stroke={FIG} strokeWidth={2}/>
      <circle cx={255} cy={93} r={5} fill="none" stroke={FIG} strokeWidth={2}/>
      <circle cx={65} cy={128} r={5} fill="none" stroke={FIG} strokeWidth={2}/>
      <circle cx={255} cy={128} r={5} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={65} y1={93} x2={65} y2={128} stroke={FIG} strokeWidth={2}/>
      <line x1={255} y1={93} x2={255} y2={128} stroke={FIG} strokeWidth={2}/>
      <circle cx={65} cy={76} r={11} fill="none" stroke={FIG} strokeWidth={2}/>
      <Lbl x={160} y={152} text="↑ COW — arch back (inhale)" color={ACC2} size={10}/>
      <Lbl x={160} y={165} text="↓ CAT — round back (exhale)" color={ACC3} size={10}/>
      <Lbl x={160} y={179} text="10 slow reps · no rest" color={DIM} size={9}/>
    </Svg>
  ),

  "band-pull-apart": (
    <Svg h={185}>
      <Lbl x={160} y={16} text="BAND PULL-APART" color={ACC1} size={11}/>
      <Fig cx={160} cy={128} armAngle={0}/>
      <line x1={90} y1={100} x2={132} y2={100} stroke={ACC2} strokeWidth={3}/>
      <line x1={188} y1={100} x2={230} y2={100} stroke={ACC2} strokeWidth={3}/>
      <Arr x1={132} y1={100} x2={86} y2={100} color={ACC1}/>
      <Arr x1={188} y1={100} x2={234} y2={100} color={ACC1}/>
      <Lbl x={160} y={168} text="Pull band apart to a T · squeeze blades" color={DIM} size={9}/>
      <Lbl x={160} y={180} text="15 reps · light band warm-up" color={DIM} size={9}/>
    </Svg>
  ),

  "band-squat": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="BAND ASSISTED SQUAT" color={ACC1} size={11}/>
      <rect x={140} y={22} width={40} height={7} rx={3} fill={DIM}/>
      <line x1={160} y1={29} x2={160} y2={52} stroke={ACC2} strokeWidth={2} strokeDasharray="4 2"/>
      <line x1={60} y1={152} x2={260} y2={152} stroke={DIM} strokeWidth={1} strokeDasharray="3 3"/>
      <Lbl x={54} y={156} text="70%" color={ACC4} size={9} anchor="end"/>
      <Fig cx={160} cy={143} legBend={14} armAngle={-28}/>
      <Lbl x={160} y={183} text="60–70% depth only · spine neutral" color={DIM} size={9}/>
      <Lbl x={160} y={195} text="3×10 · 60s rest" color={ACC1} size={9}/>
    </Svg>
  ),

  "band-row": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="BAND SEATED ROW" color={ACC1} size={11}/>
      <line x1={30} y1={163} x2={290} y2={163} stroke={DIM} strokeWidth={2}/>
      <circle cx={100} cy={100} r={13} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={100} y1={113} x2={100} y2={153} stroke={FIG} strokeWidth={2}/>
      <line x1={100} y1={153} x2={78} y2={163} stroke={FIG} strokeWidth={2}/>
      <line x1={100} y1={153} x2={122} y2={163} stroke={FIG} strokeWidth={2}/>
      <line x1={100} y1={125} x2={145} y2={133} stroke={FIG} strokeWidth={2}/>
      <line x1={100} y1={153} x2={230} y2={153} stroke={FIG} strokeWidth={2}/>
      <line x1={230} y1={158} x2={278} y2={158} stroke={ACC2} strokeWidth={3}/>
      <Arr x1={155} y1={133} x2={110} y2={126} color={ACC1}/>
      <Lbl x={200} y={138} text="SIT TALL" color={ACC2} size={10}/>
      <Lbl x={160} y={183} text="Elbows back · squeeze blades · 3×12" color={DIM} size={9}/>
    </Svg>
  ),

  "band-chest-press": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="STANDING BAND CHEST PRESS" color={ACC1} size={11}/>
      <rect x={262} y={30} width={10} height={148} fill={DIM} rx={2}/>
      <line x1={195} y1={113} x2={265} y2={113} stroke={ACC2} strokeWidth={3}/>
      <Fig cx={160} cy={140} armAngle={10}/>
      <Arr x1={150} y1={113} x2={110} y2={113} color={ACC1}/>
      <Lbl x={85} y={108} text="PRESS →" color={ACC2} size={10}/>
      <Lbl x={160} y={185} text="Core braced · no back arch · 3×12" color={DIM} size={9}/>
    </Svg>
  ),

  "glute-bridge": (
    <Svg h={190}>
      <Lbl x={160} y={16} text="GLUTE BRIDGE" color={ACC1} size={11}/>
      <line x1={20} y1={158} x2={300} y2={158} stroke={DIM} strokeWidth={2}/>
      <circle cx={78} cy={128} r={13} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={78} y1={141} x2={178} y2={141} stroke={FIG} strokeWidth={2}/>
      <line x1={178} y1={98} x2={178} y2={141} stroke={FIG} strokeWidth={2}/>
      <line x1={178} y1={98} x2={208} y2={138} stroke={FIG} strokeWidth={2}/>
      <line x1={208} y1={138} x2={213} y2={158} stroke={FIG} strokeWidth={2}/>
      <line x1={178} y1={141} x2={153} y2={158} stroke={FIG} strokeWidth={2}/>
      <Arr x1={178} y1={128} x2={178} y2={96} color={ACC2}/>
      <Lbl x={210} y={95} text="SQUEEZE GLUTES" color={ACC2} size={9}/>
      <Lbl x={160} y={174} text="Drive hips up · hold 1s · lower slow" color={DIM} size={9}/>
    </Svg>
  ),

  "lateral-walk": (
    <Svg h={190}>
      <Lbl x={160} y={16} text="BAND LATERAL WALK" color={ACC1} size={11}/>
      <line x1={98} y1={160} x2={222} y2={160} stroke={ACC2} strokeWidth={3}/>
      <Fig cx={160} cy={136} legBend={22}/>
      <Arr x1={88} y1={118} x2={52} y2={118} color={ACC1}/>
      <Arr x1={232} y1={118} x2={268} y2={118} color={ACC1}/>
      <Lbl x={160} y={185} text="Stay in squat · toes forward · 3×12 each" color={DIM} size={9}/>
    </Svg>
  ),

  "pallof-press": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="PALLOF PRESS (ANTI-ROTATION)" color={ACC1} size={11}/>
      <rect x={20} y={78} width={10} height={60} fill={DIM} rx={2}/>
      <line x1={30} y1={113} x2={128} y2={113} stroke={ACC2} strokeWidth={3}/>
      <Fig cx={160} cy={143} armAngle={5}/>
      <Arr x1={143} y1={113} x2={103} y2={113} color={ACC1}/>
      <Arr x1={177} y1={113} x2={217} y2={113} color={ACC1}/>
      <Lbl x={232} y={108} text="HOLD 2s" color={ACC2} size={10}/>
      <path d="M 160 88 Q 192 73 197 103" fill="none" stroke={ACC4} strokeWidth={1.5} strokeDasharray="3 2"/>
      <Lbl x={205} y={78} text="resist" color={ACC4} size={9}/>
      <Lbl x={160} y={185} text="Press out · hold 2s · resist rotation · 3×10 each" color={DIM} size={9}/>
    </Svg>
  ),

  "dead-bug": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="DEAD BUG" color={ACC1} size={11}/>
      <line x1={20} y1={168} x2={300} y2={168} stroke={DIM} strokeWidth={2}/>
      <circle cx={98} cy={123} r={13} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={98} y1={136} x2={198} y2={136} stroke={FIG} strokeWidth={2}/>
      <line x1={198} y1={136} x2={198} y2={168} stroke={FIG} strokeWidth={2}/>
      <line x1={118} y1={128} x2={118} y2={93} stroke={FIG} strokeWidth={2}/>
      <line x1={178} y1={128} x2={178} y2={93} stroke={FIG} strokeWidth={2}/>
      <Arr x1={118} y1={93} x2={83} y2={66} color={ACC2}/>
      <line x1={198} y1={136} x2={233} y2={153} stroke={ACC2} strokeWidth={2}/>
      <Arr x1={233} y1={153} x2={263} y2={163} color={ACC2}/>
      <line x1={98} y1={168} x2={198} y2={168} stroke={ACC1} strokeWidth={2}/>
      <Lbl x={148} y={183} text="BACK FLAT TO FLOOR — always" color={ACC4} size={9}/>
    </Svg>
  ),

  "face-pull": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="BAND FACE PULL" color={ACC1} size={11}/>
      <rect x={265} y={83} width={10} height={50} fill={DIM} rx={2}/>
      <line x1={183} y1={110} x2={268} y2={110} stroke={ACC2} strokeWidth={3}/>
      <Fig cx={148} cy={143} armAngle={-5}/>
      <Arr x1={128} y1={106} x2={98} y2={106} color={ACC1}/>
      <line x1={126} y1={106} x2={106} y2={88} stroke={ACC2} strokeWidth={1.5} strokeDasharray="3 2"/>
      <line x1={170} y1={106} x2={190} y2={88} stroke={ACC2} strokeWidth={1.5} strokeDasharray="3 2"/>
      <Lbl x={160} y={78} text="ELBOWS HIGH" color={ACC2} size={10}/>
      <Lbl x={160} y={185} text="Pull to face · elbows out · squeeze · 3×15" color={DIM} size={9}/>
    </Svg>
  ),

  "band-rdl": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="BAND RDL — MINIMAL HINGE" color={ACC1} size={11}/>
      <circle cx={180} cy={70} r={13} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={180} y1={83} x2={160} y2={118} stroke={FIG} strokeWidth={2}/>
      <line x1={160} y1={118} x2={148} y2={163} stroke={FIG} strokeWidth={2}/>
      <line x1={160} y1={118} x2={172} y2={163} stroke={FIG} strokeWidth={2}/>
      <line x1={172} y1={93} x2={148} y2={128} stroke={FIG} strokeWidth={2}/>
      <line x1={188} y1={93} x2={172} y2={128} stroke={FIG} strokeWidth={2}/>
      <line x1={128} y1={163} x2={190} y2={163} stroke={ACC2} strokeWidth={3}/>
      <path d="M 160 118 Q 195 98 190 78" fill="none" stroke={ACC4} strokeWidth={1.5} strokeDasharray="3 2"/>
      <Lbl x={207} y={93} text="30–40°" color={ACC4} size={10}/>
      <Lbl x={207} y={105} text="MAX" color={ACC4} size={10}/>
      <Lbl x={160} y={185} text="Hinge 30–40° only · back flat · 3×10" color={DIM} size={9}/>
    </Svg>
  ),

  "band-ohp": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="SEATED BAND OVERHEAD PRESS" color={ACC1} size={11}/>
      <rect x={123} y={138} width={74} height={10} rx={2} fill={DIM}/>
      <line x1={130} y1={148} x2={130} y2={173} stroke={DIM} strokeWidth={3}/>
      <line x1={190} y1={148} x2={190} y2={173} stroke={DIM} strokeWidth={3}/>
      <circle cx={160} cy={88} r={13} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={160} y1={101} x2={160} y2={138} stroke={FIG} strokeWidth={2}/>
      <line x1={160} y1={138} x2={143} y2={153} stroke={FIG} strokeWidth={2}/>
      <line x1={160} y1={138} x2={177} y2={153} stroke={FIG} strokeWidth={2}/>
      <line x1={148} y1={113} x2={130} y2={78} stroke={FIG} strokeWidth={2}/>
      <line x1={172} y1={113} x2={190} y2={78} stroke={FIG} strokeWidth={2}/>
      <Arr x1={130} y1={78} x2={130} y2={53} color={ACC2}/>
      <Arr x1={190} y1={78} x2={190} y2={53} color={ACC2}/>
      <line x1={128} y1={163} x2={192} y2={163} stroke={ACC2} strokeWidth={3}/>
      <Lbl x={160} y={185} text="Sit tall · press overhead · 3×10" color={DIM} size={9}/>
    </Svg>
  ),

  "band-curl": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="BAND BICEP CURL" color={ACC1} size={11}/>
      <Fig cx={160} cy={148}/>
      <line x1={128} y1={168} x2={192} y2={168} stroke={ACC2} strokeWidth={3}/>
      <line x1={148} y1={120} x2={138} y2={98} stroke={ACC2} strokeWidth={2}/>
      <Arr x1={138} y1={110} x2={138} y2={90} color={ACC1}/>
      <Lbl x={116} y={88} text="CURL ↑" color={ACC1} size={10}/>
      <Lbl x={163} y={108} text="ELBOWS PINNED" color={DIM} size={9}/>
      <Lbl x={160} y={185} text="2s hold · 3s lower · 3×12" color={DIM} size={9}/>
    </Svg>
  ),

  "band-tricep": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="BAND TRICEP PUSHDOWN" color={ACC1} size={11}/>
      <rect x={140} y={22} width={40} height={7} rx={2} fill={DIM}/>
      <line x1={160} y1={29} x2={160} y2={78} stroke={ACC2} strokeWidth={3}/>
      <Fig cx={160} cy={148}/>
      <line x1={148} y1={120} x2={148} y2={146} stroke={ACC2} strokeWidth={2}/>
      <line x1={172} y1={120} x2={172} y2={146} stroke={ACC2} strokeWidth={2}/>
      <Arr x1={148} y1={128} x2={148} y2={148} color={ACC1}/>
      <Arr x1={172} y1={128} x2={172} y2={148} color={ACC1}/>
      <Lbl x={103} y={133} text="ELBOWS PINNED" color={DIM} size={9}/>
      <Lbl x={160} y={185} text="Press down · squeeze · 3×12" color={DIM} size={9}/>
    </Svg>
  ),

  "incline-pushup": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="INCLINE PUSH-UP" color={ACC1} size={11}/>
      <rect x={38} y={98} width={104} height={12} rx={4} fill={DIM}/>
      <line x1={48} y1={110} x2={28} y2={143} stroke={DIM} strokeWidth={3}/>
      <line x1={132} y1={110} x2={132} y2={143} stroke={DIM} strokeWidth={3}/>
      <circle cx={83} cy={74} r={12} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={83} y1={86} x2={200} y2={146} stroke={FIG} strokeWidth={2}/>
      <line x1={83} y1={90} x2={68} y2={104} stroke={FIG} strokeWidth={2}/>
      <line x1={83} y1={90} x2={98} y2={104} stroke={FIG} strokeWidth={2}/>
      <Arr x1={83} y1={88} x2={83} y2={106} color={ACC4}/>
      <Arr x1={83} y1={106} x2={83} y2={88} color={ACC2}/>
      <Lbl x={232} y={141} text="BODY STRAIGHT" color={DIM} size={9}/>
      <Lbl x={160} y={180} text="Higher surface = easier on lower back" color={DIM} size={9}/>
      <Lbl x={160} y={192} text="3×8–12 · 60s rest" color={ACC1} size={9}/>
    </Svg>
  ),

  "pike-pushup": (
    <Svg h={198}>
      <Lbl x={160} y={16} text="PIKE PUSH-UP" color={ACC1} size={11}/>
      <line x1={20} y1={168} x2={300} y2={168} stroke={DIM} strokeWidth={2}/>
      <line x1={78} y1={168} x2={160} y2={88} stroke={FIG} strokeWidth={2}/>
      <line x1={242} y1={168} x2={160} y2={88} stroke={FIG} strokeWidth={2}/>
      <circle cx={160} cy={88} r={12} fill="none" stroke={FIG} strokeWidth={2}/>
      <Arr x1={160} y1={100} x2={160} y2={126} color={ACC1}/>
      <Lbl x={185} y={123} text="HEAD ↓" color={ACC1} size={10}/>
      <Lbl x={160} y={78} text="HIPS HIGH" color={ACC2} size={10}/>
      <Lbl x={160} y={184} text="Hips stay UP throughout · 3×8" color={DIM} size={9}/>
    </Svg>
  ),

  "diamond-pushup": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="DIAMOND PUSH-UP" color={ACC1} size={11}/>
      <line x1={20} y1={168} x2={300} y2={168} stroke={DIM} strokeWidth={2}/>
      <circle cx={108} cy={83} r={12} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={108} y1={95} x2={200} y2={158} stroke={FIG} strokeWidth={2}/>
      <polygon points="158,138 168,146 178,138 168,130" fill="none" stroke={ACC2} strokeWidth={2}/>
      <Lbl x={168} y={118} text="◇ HANDS" color={ACC2} size={10}/>
      <Arr x1={108} y1={93} x2={148} y2={123} color={ACC1}/>
      <Lbl x={83} y={148} text="TRICEPS" color={ACC1} size={10}/>
      <Lbl x={160} y={185} text="Diamond hands · knees OK to start · 3×6–10" color={DIM} size={9}/>
    </Svg>
  ),

  "plank": (
    <Svg h={190}>
      <Lbl x={160} y={16} text="FOREARM PLANK" color={ACC1} size={11}/>
      <line x1={20} y1={153} x2={300} y2={153} stroke={DIM} strokeWidth={2}/>
      <circle cx={88} cy={108} r={12} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={88} y1={120} x2={230} y2={138} stroke={FIG} strokeWidth={3}/>
      <line x1={93} y1={123} x2={93} y2={153} stroke={FIG} strokeWidth={2}/>
      <line x1={113} y1={125} x2={113} y2={153} stroke={FIG} strokeWidth={2}/>
      <line x1={228} y1={138} x2={235} y2={153} stroke={FIG} strokeWidth={2}/>
      <line x1={86} y1={120} x2={230} y2={138} stroke={ACC2} strokeWidth={1} strokeDasharray="4 3"/>
      <Lbl x={160} y={103} text="STRAIGHT LINE" color={ACC2} size={10}/>
      <path d="M 88 138 Q 160 163 230 146" fill="none" stroke={ACC4} strokeWidth={1.5} strokeDasharray="3 2"/>
      <Lbl x={160} y={175} text="⚠ STOP if hips sag — disc risk" color={ACC4} size={9}/>
      <Lbl x={160} y={187} text="Start 20s · add 5s/week · 3 sets" color={ACC1} size={9}/>
    </Svg>
  ),

  "australian-pullup": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="AUSTRALIAN PULL-UP (TABLE ROW)" color={ACC1} size={11}/>
      <rect x={58} y={68} width={204} height={12} rx={3} fill={DIM}/>
      <line x1={78} y1={80} x2={78} y2={113} stroke={DIM} strokeWidth={4}/>
      <line x1={242} y1={80} x2={242} y2={113} stroke={DIM} strokeWidth={4}/>
      <line x1={20} y1={163} x2={300} y2={163} stroke={DIM} strokeWidth={2}/>
      <circle cx={88} cy={128} r={12} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={88} y1={140} x2={228} y2={150} stroke={FIG} strokeWidth={2}/>
      <line x1={228} y1={150} x2={233} y2={163} stroke={FIG} strokeWidth={2}/>
      <line x1={90} y1={128} x2={98} y2={80} stroke={FIG} strokeWidth={2}/>
      <line x1={108} y1={130} x2={118} y2={80} stroke={FIG} strokeWidth={2}/>
      <Arr x1={98} y1={118} x2={98} y2={83} color={ACC1}/>
      <Lbl x={160} y={43} text="GRIP TABLE EDGE" color={ACC2} size={10}/>
      <Lbl x={160} y={185} text="Pull chest to table · squeeze blades · 3×8–12" color={DIM} size={9}/>
    </Svg>
  ),

  "bw-squat": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="BODYWEIGHT SQUAT" color={ACC1} size={11}/>
      <line x1={50} y1={146} x2={270} y2={146} stroke={DIM} strokeWidth={1} strokeDasharray="4 3"/>
      <Lbl x={44} y={150} text="70%" color={ACC4} size={9} anchor="end"/>
      <Fig cx={160} cy={138} legBend={20} armAngle={-22}/>
      <Arr x1={160} y1={153} x2={160} y2={173} color={ACC4}/>
      <Arr x1={160} y1={173} x2={160} y2={153} color={ACC2}/>
      <Lbl x={222} y={168} text="DRIVE UP thru heels" color={ACC2} size={9}/>
      <Lbl x={160} y={190} text="Chest tall · 1s pause · 3×15" color={DIM} size={9}/>
    </Svg>
  ),

  "reverse-lunge": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="REVERSE LUNGE" color={ACC1} size={11}/>
      <line x1={20} y1={168} x2={300} y2={168} stroke={DIM} strokeWidth={2}/>
      <circle cx={148} cy={73} r={13} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={148} y1={86} x2={148} y2={128} stroke={FIG} strokeWidth={2}/>
      <line x1={148} y1={128} x2={138} y2={153} stroke={FIG} strokeWidth={2}/>
      <line x1={138} y1={153} x2={133} y2={168} stroke={FIG} strokeWidth={2}/>
      <line x1={148} y1={128} x2={193} y2={146} stroke={FIG} strokeWidth={2}/>
      <line x1={193} y1={146} x2={193} y2={168} stroke={FIG} strokeWidth={2}/>
      <Arr x1={148} y1={133} x2={183} y2={143} color={ACC1} dashed/>
      <Lbl x={216} y={145} text="STEP BACK" color={ACC1} size={9}/>
      <Lbl x={160} y={184} text="Step back · knee near floor · 3×10 each" color={DIM} size={9}/>
    </Svg>
  ),

  "glute-bridge-single": (
    <Svg h={195}>
      <Lbl x={160} y={16} text="SINGLE-LEG GLUTE BRIDGE" color={ACC1} size={11}/>
      <line x1={20} y1={160} x2={300} y2={160} stroke={DIM} strokeWidth={2}/>
      <circle cx={78} cy={120} r={12} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={78} y1={132} x2={183} y2={132} stroke={FIG} strokeWidth={2}/>
      <line x1={183} y1={98} x2={183} y2={132} stroke={FIG} strokeWidth={2}/>
      <line x1={183} y1={98} x2={198} y2={138} stroke={FIG} strokeWidth={2}/>
      <line x1={198} y1={138} x2={203} y2={160} stroke={FIG} strokeWidth={2}/>
      <line x1={183} y1={132} x2={238} y2={116} stroke={ACC2} strokeWidth={2}/>
      <line x1={238} y1={116} x2={266} y2={116} stroke={ACC2} strokeWidth={2}/>
      <Lbl x={268} y={111} text="EXTENDED" color={ACC2} size={9} anchor="start"/>
      <Arr x1={183} y1={118} x2={183} y2={96} color={ACC1}/>
      <Lbl x={160} y={178} text="Drive up · extend one leg · 3×10 each" color={DIM} size={9}/>
    </Svg>
  ),

  "box-breathing": (
    <Svg h={210}>
      <Lbl x={160} y={16} text="BOX BREATHING  4-4-4-4" color={ACC1} size={11}/>
      <rect x={73} y={33} width={114} height={114} rx={6} fill="none" stroke={ACC1} strokeWidth={1.5} strokeDasharray="5 3"/>
      <Arr x1={130} y1={33} x2={73} y2={33} color={ACC2}/>
      <Lbl x={115} y={28} text="INHALE 4s" color={ACC2} size={10}/>
      <Arr x1={187} y1={73} x2={187} y2={33} color={ACC3}/>
      <Lbl x={202} y={60} text="HOLD 4s" color={ACC3} size={9} anchor="start"/>
      <Arr x1={130} y1={147} x2={187} y2={147} color={ACC3}/>
      <Lbl x={115} y={160} text="EXHALE 4s" color={ACC3} size={10}/>
      <Arr x1={73} y1={107} x2={73} y2={147} color={ACC1}/>
      <Lbl x={60} y={124} text="HOLD 4s" color={ACC1} size={9} anchor="end"/>
      <Lbl x={160} y={177} text="Repeat 4–6 cycles · end of every session" color={DIM} size={9}/>
      <Lbl x={160} y={190} text="Lowers cortisol · used by Navy SEALs" color={ACC2} size={9}/>
    </Svg>
  ),

  "arm-swings": (
    <Svg h={195}>
      <Lbl x={160} y={16} text="ARM CIRCLES + SHOULDER ROLLS" color={ACC1} size={11}/>
      <Fig cx={160} cy={138} armAngle={0}/>
      <path d="M 128 108 A 35 35 0 1 1 128 108.1" fill="none" stroke={ACC1} strokeWidth={1.5} strokeDasharray="4 3"/>
      <path d="M 192 108 A 35 35 0 1 0 192 108.1" fill="none" stroke={ACC1} strokeWidth={1.5} strokeDasharray="4 3"/>
      <Arr x1={128} y1={73} x2={128} y2={76} color={ACC1}/>
      <Arr x1={192} y1={76} x2={192} y2={73} color={ACC1}/>
      <Lbl x={160} y={180} text="Full circles · forward then backward · 10 each" color={DIM} size={9}/>
    </Svg>
  ),

  "leg-swings": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="LEG SWINGS" color={ACC1} size={11}/>
      <rect x={36} y={28} width={10} height={157} fill={DIM} rx={2}/>
      <circle cx={93} cy={68} r={13} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={93} y1={81} x2={93} y2={128} stroke={FIG} strokeWidth={2}/>
      <line x1={93} y1={98} x2={46} y2={98} stroke={FIG} strokeWidth={2}/>
      <circle cx={46} cy={98} r={4} fill={ACC1}/>
      <line x1={93} y1={128} x2={86} y2={168} stroke={FIG} strokeWidth={2}/>
      <path d="M 93 128 Q 128 146 143 168" fill="none" stroke={ACC2} strokeWidth={2} strokeDasharray="4 2"/>
      <path d="M 93 128 Q 63 146 50 166" fill="none" stroke={ACC3} strokeWidth={2} strokeDasharray="4 2"/>
      <line x1={93} y1={128} x2={138} y2={160} stroke={ACC2} strokeWidth={2}/>
      <Arr x1={123} y1={156} x2={140} y2={161} color={ACC2}/>
      <Lbl x={153} y={160} text="FORWARD" color={ACC2} size={9}/>
      <Lbl x={40} y={173} text="BACK" color={ACC3} size={9} anchor="end"/>
      <Lbl x={160} y={192} text="10 swings each direction per leg" color={DIM} size={9}/>
    </Svg>
  ),

  // ── Flare-up specific diagrams ──

  "mckenzie": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="McKENZIE PRESS-UP" color={ACC4} size={11}/>
      <line x1={20} y1={168} x2={300} y2={168} stroke={DIM} strokeWidth={2}/>
      <circle cx={90} cy={138} r={12} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={90} y1={150} x2={230} y2={155} stroke={FIG} strokeWidth={2}/>
      <line x1={230} y1={155} x2={240} y2={168} stroke={FIG} strokeWidth={2}/>
      <line x1={100} y1={145} x2={105} y2={168} stroke={FIG} strokeWidth={2}/>
      <line x1={130} y1={147} x2={135} y2={168} stroke={FIG} strokeWidth={2}/>
      <circle cx={90} cy={108} r={12} fill="none" stroke={ACC2} strokeWidth={2} strokeDasharray="3 2"/>
      <Arr x1={90} y1={138} x2={90} y2={110} color={ACC2}/>
      <Lbl x={60} y={105} text="PRESS UP" color={ACC2} size={10}/>
      <Lbl x={195} y={148} text="HIPS STAY" color={DIM} size={9}/>
      <Lbl x={195} y={158} text="ON FLOOR" color={DIM} size={9}/>
      <Lbl x={160} y={182} text="#1 exercise for L4/L5 and L5/S1 flare" color={ACC2} size={9}/>
      <Lbl x={160} y={195} text="10 reps · hold 2s at top" color={ACC1} size={9}/>
    </Svg>
  ),

  "knee-hug": (
    <Svg h={195}>
      <Lbl x={160} y={16} text="SUPINE KNEE HUG" color={ACC4} size={11}/>
      <line x1={20} y1={165} x2={300} y2={165} stroke={DIM} strokeWidth={2}/>
      <circle cx={85} cy={125} r={13} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={85} y1={138} x2={180} y2={148} stroke={FIG} strokeWidth={2}/>
      <line x1={180} y1={148} x2={185} y2={165} stroke={FIG} strokeWidth={2}/>
      <path d="M 100 130 Q 155 100 165 130" fill="none" stroke={FIG} strokeWidth={2}/>
      <path d="M 100 138 Q 155 120 165 138" fill="none" stroke={FIG} strokeWidth={2}/>
      <ellipse cx={155} cy={128} rx={20} ry={15} fill="none" stroke={ACC2} strokeWidth={2}/>
      <Lbl x={155} y={128} text="KNEES" color={ACC2} size={9}/>
      <Arr x1={185} y1={145} x2={165} y2={132} color={ACC2}/>
      <Lbl x={160} y={180} text="Pull knees gently to chest · breathe · hold 30s" color={DIM} size={9}/>
      <Lbl x={160} y={192} text="Decompresses L4/L5 and L5/S1" color={ACC2} size={9}/>
    </Svg>
  ),

  "walking": (
    <Svg h={190}>
      <Lbl x={160} y={16} text="GENTLE WALKING" color={ACC4} size={11}/>
      <line x1={20} y1={168} x2={300} y2={168} stroke={DIM} strokeWidth={2}/>
      <Fig cx={100} cy={138} armAngle={-20} legBend={8}/>
      <Fig cx={210} cy={138} armAngle={20} legBend={-8} color="#4b5563"/>
      <Arr x1={130} y1={128} x2={178} y2={128} color={ACC2}/>
      <Lbl x={160} y={118} text="UPRIGHT POSTURE" color={ACC2} size={10}/>
      <Lbl x={160} y={182} text="Flat surface · 10–20 min · stop if pain increases" color={DIM} size={9}/>
    </Svg>
  ),

  "pelvic-tilt": (
    <Svg h={195}>
      <Lbl x={160} y={16} text="GLUTE BRIDGE — SMALL RANGE" color={ACC4} size={11}/>
      <line x1={20} y1={162} x2={300} y2={162} stroke={DIM} strokeWidth={2}/>
      <circle cx={80} cy={128} r={12} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={80} y1={140} x2={175} y2={142} stroke={FIG} strokeWidth={2}/>
      <line x1={175} y1={118} x2={175} y2={142} stroke={FIG} strokeWidth={2}/>
      <line x1={175} y1={118} x2={200} y2={148} stroke={FIG} strokeWidth={2}/>
      <line x1={200} y1={148} x2={204} y2={162} stroke={FIG} strokeWidth={2}/>
      <line x1={175} y1={142} x2={152} y2={162} stroke={FIG} strokeWidth={2}/>
      <Arr x1={175} y1={135} x2={175} y2={116} color={ACC2}/>
      <Lbl x={215} y={112} text="SMALL RANGE" color={ACC2} size={9}/>
      <Lbl x={215} y={122} text="50% only" color={DIM} size={9}/>
      <Lbl x={160} y={178} text="Small hip lift · squeeze glutes · 2s hold" color={DIM} size={9}/>
      <Lbl x={160} y={190} text="No band · 3×12" color={ACC1} size={9}/>
    </Svg>
  ),

  "dead-bug-arms": (
    <Svg h={200}>
      <Lbl x={160} y={16} text="DEAD BUG — ARMS ONLY (FLARE MOD)" color={ACC4} size={11}/>
      <line x1={20} y1={168} x2={300} y2={168} stroke={DIM} strokeWidth={2}/>
      <circle cx={98} cy={123} r={13} fill="none" stroke={FIG} strokeWidth={2}/>
      <line x1={98} y1={136} x2={198} y2={148} stroke={FIG} strokeWidth={2}/>
      <line x1={198} y1={148} x2={215} y2={168} stroke={FIG} strokeWidth={2}/>
      <line x1={175} y1={140} x2={152} y2={168} stroke={FIG} strokeWidth={2}/>
      <line x1={118} y1={128} x2={118} y2={93} stroke={FIG} strokeWidth={2}/>
      <line x1={178} y1={128} x2={178} y2={93} stroke={FIG} strokeWidth={2}/>
      <Arr x1={118} y1={93} x2={83} y2={66} color={ACC2}/>
      <line x1={98} y1={136} x2={75} y2={162} stroke={FIG} strokeWidth={2}/>
      <line x1={98} y1={136} x2={120} y2={162} stroke={FIG} strokeWidth={2}/>
      <Lbl x={240} y={155} text="LEGS STAY BENT" color={ACC4} size={9}/>
      <line x1={98} y1={168} x2={198} y2={168} stroke={ACC1} strokeWidth={2}/>
      <Lbl x={148} y={183} text="BACK FLAT — arms only during flare" color={ACC4} size={9}/>
    </Svg>
  ),
};
