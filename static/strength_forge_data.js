/* ============================================================
 * Strength Forge — data module (#282)
 * ------------------------------------------------------------
 * Verbatim port of the prototype's exerciseData.js + constants.js
 * (docs/design/strength-forge/). Plain data only — no rendering.
 * Exposed as window.SFData for static/strength_forge.js (classic
 * script, same pattern as the other page data/helpers).
 *
 * CLINICAL SAFETY: every exercise description, the avoid-list, the
 * warning signs, and the flare-phase protocol are copied EXACTLY from
 * the signed-off prototype. Do not paraphrase — these are clinically
 * grounded for L4/L5 + L5/S1 herniated discs (CONTEXT.md §2/§8).
 * ============================================================ */
(function () {
  "use strict";

  var SAFE_LABELS = {
    therapeutic: "✓ therapeutic",
    "back-safe": "✓ back-safe",
    monitor: "⚠ monitor carefully",
    recovery: "✓ recovery",
  };

  // Safe-tag → Soft Concrete accent role (resolved to CSS vars in
  // strength_forge.js via a class, not inline color).
  var SAFE_CLASS = {
    therapeutic: "sf-safe-therapeutic",
    "back-safe": "sf-safe-backsafe",
    monitor: "sf-safe-monitor",
    recovery: "sf-safe-recovery",
  };

  function googleLink(query) {
    return (
      "https://www.google.com/search?q=" +
      encodeURIComponent(query + " exercise how to form") +
      "&tbm=isch"
    );
  }

  var exercises = {
    "cat-cow": { title: "Cat-Cow Stretch", search: "cat cow stretch", sets: "10 slow reps", rest: "No rest", desc: "Start on all fours, wrists under shoulders, knees under hips. Inhale: drop belly, lift head and tailbone (Cow). Exhale: round spine toward ceiling, tuck chin and pelvis (Cat). Move slowly. Gently mobilizes L4/L5 and L5/S1 without any compression.", safe: "therapeutic" },
    "band-pull-apart": { title: "Band Pull-Apart", search: "resistance band pull apart", sets: "15 reps", rest: "No rest", desc: "Hold band at chest width, arms straight. Pull band apart horizontally until arms form a T, squeezing shoulder blades together. Control the return. Light band only.", safe: "back-safe" },
    "band-squat": { title: "Band Assisted Squat", search: "resistance band assisted squat", sets: "3 × 10", rest: "60 sec between sets · 30 sec before next", desc: "Anchor band above you (door frame). Hold band for support as you squat. Feet shoulder-width, toes slightly out. Squat to only 60–70% depth. Drive up through heels. Keep chest tall and spine neutral.", safe: "back-safe" },
    "band-row": { title: "Band Seated Row", search: "resistance band seated row", sets: "3 × 12", rest: "60 sec between sets · 30 sec before next", desc: "Sit on floor with legs extended. Loop band around both feet. Sit TALL — do not round forward. Pull elbows back past your torso, squeezing shoulder blades together. Critical for correcting the forward-rounded posture that worsens back pain.", safe: "back-safe" },
    "band-chest-press": { title: "Standing Band Chest Press", search: "resistance band standing chest press", sets: "3 × 12", rest: "60 sec between sets · 30 sec before next", desc: "Anchor band behind you at chest height. Press both hands forward until arms are nearly straight, then slowly return. Keep core braced — do not arch your lower back. Standing removes all spinal compression.", safe: "back-safe" },
    "glute-bridge": { title: "Glute Bridge", search: "glute bridge exercise form", sets: "3 × 15", rest: "45 sec between sets · 30 sec before next", desc: "Lie on back, knees bent, feet flat on floor hip-width apart. Drive hips up by squeezing glutes hard — body forms a straight line from shoulders to knees. Hold 1 second at top, lower slowly. Directly strengthens muscles that stabilize L4/L5 and L5/S1.", safe: "therapeutic" },
    "lateral-walk": { title: "Band Lateral Walk", search: "resistance band lateral walk glute", sets: "3 × 12 each way", rest: "45 sec between sets · 30 sec before next", desc: "Band around ankles. Sink into a slight squat and hold that position throughout. Step sideways maintaining tension at all times. Targets the glute medius — the hip stabilizer that protects your lower back and knees.", safe: "back-safe" },
    "pallof-press": { title: "Pallof Press", search: "pallof press band anti rotation core", sets: "3 × 10 each side", rest: "45 sec between sets", desc: "Anchor band at chest height to your side. Stand perpendicular to anchor. Brace core hard and press both hands straight out — hold 2 seconds resisting the band's pull to rotate you. Safest core exercise for herniated discs — never flexes the spine.", safe: "therapeutic" },
    "dead-bug": { title: "Dead Bug", search: "dead bug exercise core", sets: "3 × 8 each side", rest: "45 sec between sets", desc: "Lie on back. Raise both arms toward ceiling and bend both knees to 90°. Press lower back FIRMLY into floor the entire time. Slowly extend right arm overhead and left leg straight simultaneously. Return, switch sides. Approved in herniated disc rehabilitation protocols.", safe: "therapeutic" },
    "face-pull": { title: "Band Face Pull", search: "resistance band face pull", sets: "3 × 15", rest: "45 sec between sets", desc: "Anchor band at face height. Pull band toward your face keeping elbows HIGH. Hands come to either side of face, elbows pointing out. Corrects forward-head and rounded-shoulder posture from desk work.", safe: "back-safe" },
    "band-rdl": { title: "Band Romanian Deadlift", search: "resistance band romanian deadlift", sets: "3 × 10", rest: "60 sec between sets · 30 sec before next", desc: "Stand on band, hold one end in each hand. Hinge at hips by pushing hips BACKWARD — only 30–40°, not a full RDL. Back flat and neutral throughout. Stop and replace with Glute Bridge if any disc pain triggers.", safe: "monitor" },
    "band-ohp": { title: "Seated Band Overhead Press", search: "resistance band seated overhead press", sets: "3 × 10", rest: "60 sec between sets · 30 sec before next", desc: "Sit on sturdy chair, band looped under both feet. Press both hands overhead until arms fully extended, then slowly lower. Seated position prevents lumbar hyperextension that can compress herniated discs.", safe: "back-safe" },
    "band-curl": { title: "Band Bicep Curl", search: "resistance band bicep curl", sets: "3 × 12", rest: "45 sec between sets · 30 sec before next", desc: "Stand on band, palms facing forward. Keep elbows pinned to sides throughout. Curl both hands toward shoulders, hold 2 seconds at top, lower for 3 seconds. Slow tempo builds more muscle than fast reps.", safe: "back-safe" },
    "band-tricep": { title: "Band Tricep Pushdown", search: "resistance band tricep pushdown", sets: "3 × 12", rest: "45 sec between sets · 30 sec before next", desc: "Anchor band above head at door frame. Elbows pinned tightly to sides — they must not move. Push both hands down until arms fully extended, squeeze triceps hard at bottom.", safe: "back-safe" },
    "incline-pushup": { title: "Incline Push-Up", search: "incline push up elevated hands", sets: "3 × 8–12", rest: "60 sec between sets · 30 sec before next", desc: "Hands on counter, table, or wall — higher surface means easier. Body forms a straight line from head to heels. Lower chest toward surface, elbows at roughly 45° from body. Elevated hands removes lower back stress.", safe: "back-safe" },
    "pike-pushup": { title: "Pike Push-Up", search: "pike push up shoulder exercise", sets: "3 × 8", rest: "60 sec between sets · 30 sec before next", desc: "Start in downward-dog — hands and feet on floor, hips raised high forming an inverted V. Keep hips elevated throughout. Bend elbows to lower head toward floor. Hips MUST stay high — if they drop you lose the form and the back protection.", safe: "back-safe" },
    "diamond-pushup": { title: "Diamond Push-Up", search: "diamond push up tricep", sets: "3 × 6–10", rest: "60 sec between sets · 30 sec before next", desc: "Hands close together beneath chest forming a diamond. Do on knees until you build strength. Lower chest toward hands, elbows tracking back. Places maximum tension on the triceps.", safe: "back-safe" },
    "plank": { title: "Forearm Plank", search: "forearm plank proper form", sets: "3 × 20–45 sec", rest: "45 sec between sets · 30 sec before next", desc: "Forearms on floor, elbows under shoulders. Body forms a straight line. Actively squeeze glutes and brace core. CRITICAL: stop the moment hips begin to sag — a sagging plank places significant compressive force on L4/L5 and L5/S1.", safe: "back-safe" },
    "australian-pullup": { title: "Australian Pull-Up (Table Row)", search: "australian pull up inverted row table", sets: "3 × 8–12", rest: "60 sec between sets · 30 sec before next", desc: "Lie under a sturdy table and grip the edge. Body straight, pull chest up to the table squeezing shoulder blades together at the top. Lower slowly. Best bodyweight back exercise without a pull-up bar.", safe: "back-safe" },
    "bw-squat": { title: "Bodyweight Squat", search: "bodyweight squat proper form", sets: "3 × 15", rest: "60 sec between sets · 30 sec before next", desc: "Feet shoulder-width, toes slightly out. Chest tall, core braced, weight in heels. Lower to about 70% depth with a neutral spine. Pause 1 second at bottom. Drive up through heels.", safe: "back-safe" },
    "reverse-lunge": { title: "Reverse Lunge", search: "reverse lunge bodyweight form", sets: "3 × 10 each leg", rest: "60 sec between sets · 30 sec before next", desc: "Stand tall, step one foot directly backward and lower back knee toward floor. Front shin stays vertical. Push off front foot to return. Disc-safer than forward lunges — less forward trunk lean required.", safe: "back-safe" },
    "glute-bridge-single": { title: "Single-Leg Glute Bridge", search: "single leg glute bridge", sets: "3 × 10 each leg", rest: "45 sec between sets · 30 sec before next", desc: "Lie on back, knees bent. Extend one leg straight out. Drive hips up through the planted foot, squeezing glutes hard at the top. Hold 1 second. Lower slowly. Work up to this from the standard bridge first.", safe: "therapeutic" },
    "box-breathing": { title: "Box Breathing (4-4-4-4)", search: "box breathing technique", sets: "4–6 full cycles", rest: "End of every session — mandatory", desc: "Inhale 4 sec → Hold 4 sec → Exhale 4 sec → Hold empty 4 sec = 1 cycle. Complete 4–6 cycles. Used by Navy SEALs for stress regulation. Clinically activates the parasympathetic nervous system, directly lowering cortisol.", safe: "recovery" },
    "arm-swings": { title: "Arm Circles + Shoulder Rolls", search: "arm circles shoulder rolls warm up", sets: "10 each direction", rest: "No rest", desc: "Stand tall. Make small circles forward for 10 reps, then large circles backward for 10 reps. Then roll both shoulders forward 10 times and backward 10 times. Mobilizes shoulder joints without stressing the lumbar region.", safe: "back-safe" },
    "leg-swings": { title: "Leg Swings", search: "leg swings warm up hip mobility", sets: "10 each direction/leg", rest: "No rest", desc: "Stand facing a wall with one hand for balance. Swing one leg forward and back 10 times. Turn 90° and swing side to side 10 times. Switch legs. Keep spine upright and relaxed. Warms hips without any spinal loading.", safe: "back-safe" },
    // Cool-down stretches — each has its own entry so the detail modal
    // shows the right exercise (bug fix: these previously reused another
    // exercise's id and showed its details/diagram). No SVG diagram yet;
    // the modal omits it gracefully and the Google Images link still works.
    "hip-90-90": { title: "90/90 Hip Stretch", search: "90 90 hip stretch mobility", sets: "45s × 2 sides", rest: "15s to switch", desc: "Sit on the floor with the front leg bent 90° in front of you and the back leg bent 90° out to the side. Keep your spine tall and gently hinge forward from the hips over the front shin until you feel a stretch deep in the outer hip and glute. Hold, then switch sides. Opens the hips without loading the lower back.", safe: "back-safe" },
    "quad-stretch": { title: "Standing Quad Stretch", search: "standing quad stretch", sets: "45s × 2 sides", rest: "15s to switch", desc: "Stand tall and hold a wall or chair for balance. Bend one knee and grasp that ankle, drawing the heel toward your glute. Keep your knees together and push your hips slightly forward — do NOT arch your lower back. Hold, then switch legs.", safe: "back-safe" },
    "chest-stretch": { title: "Doorway Chest Stretch", search: "doorway chest stretch pec", sets: "30s × 2 sides", rest: "15s to switch", desc: "Stand in a doorway with one forearm against the frame, elbow at shoulder height. Step gently forward through the doorway until you feel a stretch across the chest and front of the shoulder. Keep your core braced and spine neutral. Hold, then switch sides. Counteracts the rounded-shoulder posture from desk work.", safe: "back-safe" },
  };

  var bandPlanA = [
    { section: "Warm-Up", badge: "5 min", role: "band", num: "01", items: [
      { id: "cat-cow", name: "Cat-Cow Stretch", sets: "10 reps", rest: "No rest" },
      { id: "band-pull-apart", name: "Band Pull-Apart", sets: "15 reps", rest: "No rest" },
    ] },
    { section: "Main Work", badge: "20 min", role: "safe", num: "02", items: [
      { id: "band-squat", name: "Band Assisted Squat", sets: "3 × 10", rest: "60s sets · 30s next" },
      { id: "band-row", name: "Band Seated Row", sets: "3 × 12", rest: "60s sets · 30s next" },
      { id: "band-chest-press", name: "Standing Band Chest Press", sets: "3 × 12", rest: "60s sets · 30s next" },
      { id: "glute-bridge", name: "Band Glute Bridge", sets: "3 × 15", rest: "45s sets · 30s next" },
      { id: "lateral-walk", name: "Band Lateral Walk", sets: "3 × 12 each", rest: "45s sets · 30s next" },
      { id: "pallof-press", name: "Pallof Press", sets: "3 × 10 each", rest: "45s between sets" },
    ] },
    { section: "Cool-Down", badge: "4 min", role: "mil", num: "03", items: [
      { id: "hip-90-90", name: "90/90 Hip Stretch", sets: "45s × 2 sides", rest: "15s to switch" },
      { id: "box-breathing", name: "Box Breathing (4-4-4-4)", sets: "4–6 cycles", rest: "End of session" },
    ] },
  ];

  var bandPlanB = [
    { section: "Warm-Up", badge: "5 min", role: "band", num: "01", items: [
      { id: "cat-cow", name: "Cat-Cow Stretch", sets: "10 reps", rest: "No rest" },
      { id: "glute-bridge", name: "Glute Bridge Warm-Up (No Band)", sets: "15 reps", rest: "No rest" },
    ] },
    { section: "Main Work", badge: "20 min", role: "safe", num: "02", items: [
      { id: "band-rdl", name: "Band RDL (Minimal Hinge)", sets: "3 × 10", rest: "60s sets · 30s next" },
      { id: "band-ohp", name: "Seated Band Overhead Press", sets: "3 × 10", rest: "60s sets · 30s next" },
      { id: "band-curl", name: "Band Bicep Curl", sets: "3 × 12", rest: "45s sets · 30s next" },
      { id: "band-tricep", name: "Band Tricep Pushdown", sets: "3 × 12", rest: "45s sets · 30s next" },
      { id: "dead-bug", name: "Dead Bug", sets: "3 × 8 each", rest: "45s sets · 30s next" },
      { id: "face-pull", name: "Band Face Pull", sets: "3 × 15", rest: "45s between sets" },
    ] },
    { section: "Cool-Down", badge: "4 min", role: "mil", num: "03", items: [
      { id: "quad-stretch", name: "Standing Quad Stretch", sets: "45s × 2 sides", rest: "15s to switch" },
      { id: "box-breathing", name: "Box Breathing (4-4-4-4)", sets: "4–6 cycles", rest: "End of session" },
    ] },
  ];

  var milS1 = [
    { section: "PT Warm-Up", badge: "5 min", role: "band", num: "01", items: [
      { id: "cat-cow", name: "Cat-Cow Stretch", sets: "10 reps", rest: "No rest" },
      { id: "arm-swings", name: "Arm Circles + Shoulder Rolls", sets: "10 each", rest: "No rest" },
    ] },
    { section: "Main Work — Push + Core", badge: "20 min", role: "safe", num: "02", items: [
      { id: "incline-pushup", name: "Incline Push-Up", sets: "3 × 8–12", rest: "60s sets · 30s next" },
      { id: "pike-pushup", name: "Pike Push-Up", sets: "3 × 8", rest: "60s sets · 30s next" },
      { id: "diamond-pushup", name: "Diamond Push-Up (Knees if Needed)", sets: "3 × 6–10", rest: "60s sets · 30s next" },
      { id: "plank", name: "Forearm Plank", sets: "3 × 20–45s", rest: "45s sets · 30s next" },
      { id: "dead-bug", name: "Dead Bug", sets: "3 × 8 each", rest: "45s between sets" },
    ] },
    { section: "Cool-Down", badge: "4 min", role: "mil", num: "03", items: [
      { id: "chest-stretch", name: "Doorway Chest Stretch", sets: "30s × 2 sides", rest: "15s to switch" },
      { id: "box-breathing", name: "Box Breathing (4-4-4-4)", sets: "4–6 cycles", rest: "End of session" },
    ] },
  ];

  var milS2 = [
    { section: "PT Warm-Up", badge: "5 min", role: "band", num: "01", items: [
      { id: "leg-swings", name: "Leg Swings (Front/Back + Side)", sets: "10 each", rest: "No rest" },
      { id: "glute-bridge", name: "Glute Bridge Warm-Up", sets: "15 reps", rest: "No rest" },
    ] },
    { section: "Main Work — Pull + Legs", badge: "20 min", role: "safe", num: "02", items: [
      { id: "australian-pullup", name: "Australian Pull-Up (Table Row)", sets: "3 × 8–12", rest: "60s sets · 30s next" },
      { id: "bw-squat", name: "Bodyweight Squat", sets: "3 × 15", rest: "60s sets · 30s next" },
      { id: "reverse-lunge", name: "Reverse Lunge", sets: "3 × 10 each", rest: "60s sets · 30s next" },
      { id: "glute-bridge-single", name: "Single-Leg Glute Bridge", sets: "3 × 10 each", rest: "45s sets · 30s next" },
      { id: "dead-bug", name: "Dead Bug", sets: "3 × 8 each", rest: "45s between sets" },
    ] },
    { section: "Cool-Down", badge: "4 min", role: "mil", num: "03", items: [
      { id: "box-breathing", name: "Box Breathing (4-4-4-4)", sets: "4–6 cycles", rest: "End of session" },
    ] },
  ];

  var milS3 = [
    { section: "Full Body Circuit — 3 Rounds", badge: "22 min", role: "safe", num: "01", items: [
      { id: "incline-pushup", name: "Incline Push-Up", sets: "10 reps", rest: "20s before next" },
      { id: "bw-squat", name: "Bodyweight Squat", sets: "12 reps", rest: "20s before next" },
      { id: "australian-pullup", name: "Australian Pull-Up", sets: "8 reps", rest: "20s before next" },
      { id: "glute-bridge", name: "Glute Bridge", sets: "15 reps", rest: "20s before next" },
      { id: "plank", name: "Forearm Plank", sets: "Max hold", rest: "90s — repeat circuit" },
    ] },
  ];

  var flarePhases = [
    { id: "immediate", label: "Day 1–2", title: "Acute Phase", subtitle: "First 24–48 hrs", role: "flare", icon: "🔴",
      desc: "Inflammation is peaking. Goal is decompression and gentle movement only. No loading whatsoever.",
      exercises: [
        { name: "McKenzie Press-Up", diagramId: "mckenzie", search: "mckenzie press up prone extension lumbar", duration: "3 sets × 10 reps", rest: "30 sec between sets", how: "Lie face down. Place hands under shoulders. Press your upper body up gently while hips stay on the floor. Hold 2 seconds at the top, lower slowly. The #1 clinically recommended movement for L4/L5 and L5/S1 disc herniations.", tip: "If it causes centralization (pain moves from leg back toward spine) that is a GOOD sign — continue." },
        { name: "Supine Knee Hug", diagramId: "knee-hug", search: "supine knee to chest stretch back pain", duration: "5 reps × 30 sec hold", rest: "15 sec between reps", how: "Lie on your back. Slowly pull both knees gently to your chest. Hold 30 seconds breathing deeply. Slowly lower. Gently decompresses L4/L5 and L5/S1.", tip: "If both legs together hurts, do one knee at a time." },
        { name: "Cat-Cow (Minimal Range)", diagramId: "cat-cow", search: "cat cow stretch gentle back pain", duration: "10 reps · very slow", rest: "No rest", how: "Same as your normal Cat-Cow but cut the range of motion in half. Only move as far as feels comfortable. The goal is gentle fluid movement, not stretch.", tip: "Think of it as breathing movement, not stretching." },
        { name: "Gentle Walking", diagramId: "walking", search: "walking for lower back pain disc herniation", duration: "10–15 min · slow pace", rest: "Stop if pain increases", how: "Walk slowly on a flat surface. Keep posture upright, shoulders relaxed. Swing arms naturally. Walking pumps fluid into the discs, reduces inflammation, and maintains blood flow to healing tissue.", tip: "Do not walk on inclines or uneven ground during a flare." },
      ] },
    { id: "recovery", label: "Day 3–5", title: "Recovery Phase", subtitle: "Pain reducing", role: "band", icon: "🟡",
      desc: "Inflammation is reducing. Begin gently reactivating the muscles that protect your discs. Still no loading.",
      exercises: [
        { name: "McKenzie Press-Up", diagramId: "mckenzie", search: "mckenzie press up prone extension lumbar", duration: "3 sets × 10 reps", rest: "30 sec between sets", how: "Same as Day 1–2 but increase the range slightly if tolerated. Press higher and hold 2–3 seconds at the top. Continue daily until symptoms fully resolve.", tip: "Continue even when feeling better. Stop only when fully symptom-free." },
        { name: "Glute Bridge (Small Range)", diagramId: "pelvic-tilt", search: "glute bridge lower back pain rehab", duration: "3 sets × 12 reps", rest: "45 sec between sets", how: "Lie on back, knees bent. Drive hips up only about 50% of your normal range — just enough to feel glute activation. Squeeze hard at the top for 2 seconds. Lower very slowly. No band.", tip: "If full bridge hurts, just do pelvic tilts: gently flatten your lower back into the floor and release." },
        { name: "Dead Bug (Arms Only)", diagramId: "dead-bug-arms", search: "dead bug exercise modified arms only", duration: "3 sets × 10 reps", rest: "45 sec between sets", how: "Lie on back, arms raised toward ceiling, knees bent with feet on floor. Lower back pressed flat to the floor throughout. Slowly lower one arm overhead and return. Switch sides. Skip the leg component entirely.", tip: "Press your lower back harder into the floor the moment you feel it lifting." },
        { name: "Supine Knee Hug", diagramId: "knee-hug", search: "supine knee to chest stretch back pain", duration: "5 reps × 30 sec hold", rest: "15 sec between reps", how: "Same as Day 1–2. Continue daily. By now the decompression effect should feel more noticeable and comfortable.", tip: "Add gentle ankle circles while holding the knees to maintain hip mobility." },
        { name: "Gentle Walking", diagramId: "walking", search: "walking for lower back pain disc herniation", duration: "15–20 min · comfortable pace", rest: "Stop if pain increases", how: "Increase to 15–20 minutes at a comfortable pace. Posture upright, core gently braced, breathing relaxed.", tip: "Walk after your exercises, not before." },
      ] },
    { id: "return", label: "Day 6+", title: "Return to Training", subtitle: "Pain resolved", role: "safe", icon: "🟢",
      desc: "Pain has resolved or nearly resolved. Return to your normal plan at 50% intensity. Do not jump straight back to full sets and resistance.",
      exercises: [
        { name: "Full Glute Bridge (Bodyweight)", diagramId: "glute-bridge", search: "glute bridge exercise form", duration: "3 sets × 15 reps", rest: "45 sec between sets", how: "Return to your full glute bridge range. Bodyweight only — no band yet. If this feels completely pain-free across all 3 sets, you are ready to reintroduce light bands next session.", tip: "Pain-free full range of motion is your green light to resume normal training." },
        { name: "Dead Bug (Full — Arms + Legs)", diagramId: "dead-bug", search: "dead bug exercise core", duration: "3 sets × 8 each side", rest: "45 sec between sets", how: "Return to the full Dead Bug — opposite arm and leg extending simultaneously, lower back pressed firmly to the floor. If this is pain-free, your deep core stabilizers are re-engaged.", tip: "Go slower than normal on your first return session." },
        { name: "Pallof Press (Light Band)", diagramId: "pallof-press", search: "pallof press band anti rotation", duration: "3 sets × 8 each side", rest: "45 sec between sets", how: "Return to the Pallof Press using your lightest band. The anti-rotation demand confirms your core is ready to protect the spine under light load again.", tip: "If any disc pain returns during this exercise, go back to Day 3–5 protocol for two more days." },
        { name: "McKenzie Press-Up (Maintenance)", diagramId: "mckenzie", search: "mckenzie press up prone extension", duration: "1 set × 10 reps", rest: "End of session", how: "Do 10 McKenzie press-ups as a maintenance dose at the end of every workout for 2 weeks after a flare. This keeps the disc tissue healthy and reduces re-injury risk.", tip: "Make this a permanent end-of-session habit whenever your back has been under stress." },
      ] },
  ];

  var avoidList = [
    { item: "Sit-ups, crunches, any spinal flexion under load", reason: "Compresses the herniated disc directly — worst possible movement during a flare" },
    { item: "Deadlifts or Romanian deadlifts", reason: "High spinal loading — skip entirely until at least 1 week post-flare" },
    { item: "Squats below 50% depth", reason: "Increases lumbar compression significantly at deeper angles" },
    { item: "Forearm plank", reason: "Sustained core tension can spike disc pressure during acute phase" },
    { item: "Any twisting or rotation under load", reason: "Rotational forces directly stress the L4/L5 and L5/S1 disc annulus" },
    { item: "Sitting for more than 30 minutes", reason: "Sitting increases disc pressure more than standing — get up and walk every 30 min" },
    { item: "Any exercise that increases leg pain", reason: "Radiating pain down the leg means the disc is pressing on a nerve — stop immediately" },
  ];

  var warnSigns = [
    "Pain or weakness spreading down one or both legs during exercise",
    "Loss of bladder or bowel control — seek emergency care immediately",
    "Numbness or tingling in the groin or inner thigh area",
    "No improvement after 5–7 days of the recovery protocol",
  ];

  window.SFData = {
    exercises: exercises,
    bandPlanA: bandPlanA,
    bandPlanB: bandPlanB,
    milS1: milS1,
    milS2: milS2,
    milS3: milS3,
    flarePhases: flarePhases,
    avoidList: avoidList,
    warnSigns: warnSigns,
    SAFE_LABELS: SAFE_LABELS,
    SAFE_CLASS: SAFE_CLASS,
    googleLink: googleLink,
  };
})();
