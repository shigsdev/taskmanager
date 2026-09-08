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
    "band-pull-apart": { resist: true, title: "Band Pull-Apart", search: "resistance band pull apart", sets: "15 reps", rest: "No rest", desc: "Hold band at chest width, arms straight. Pull band apart horizontally until arms form a T, squeezing shoulder blades together. Control the return. Light band only.", safe: "back-safe" },
    "band-squat": { resist: true, title: "Band Assisted Squat", search: "resistance band assisted squat", sets: "3 × 10", rest: "60 sec between sets · 30 sec before next", desc: "Anchor band above you (door frame). Hold band for support as you squat. Feet shoulder-width, toes slightly out. Squat to only 60–70% depth. Drive up through heels. Keep chest tall and spine neutral.", safe: "back-safe" },
    "band-row": { resist: true, title: "Band Seated Row", search: "resistance band seated row", sets: "3 × 12", rest: "60 sec between sets · 30 sec before next", desc: "Sit on floor with legs extended. Loop band around both feet. Sit TALL — do not round forward. Pull elbows back past your torso, squeezing shoulder blades together. Critical for correcting the forward-rounded posture that worsens back pain.", safe: "back-safe" },
    "band-chest-press": { resist: true, title: "Standing Band Chest Press", search: "resistance band standing chest press", sets: "3 × 12", rest: "60 sec between sets · 30 sec before next", desc: "Anchor band behind you at chest height. Press both hands forward until arms are nearly straight, then slowly return. Keep core braced — do not arch your lower back. Standing removes all spinal compression.", safe: "back-safe" },
    "glute-bridge": { title: "Glute Bridge", search: "glute bridge exercise form", sets: "3 × 15", rest: "45 sec between sets · 30 sec before next", desc: "Lie on back, knees bent, feet flat on floor hip-width apart. Drive hips up by squeezing glutes hard — body forms a straight line from shoulders to knees. Hold 1 second at top, lower slowly. Directly strengthens muscles that stabilize L4/L5 and L5/S1.", safe: "therapeutic" },
    // #317: the BANDED bridge needs its own entry. It used to reuse
    // "glute-bridge", so the ℹ️ modal for "Band Glute Bridge" described the
    // plain bodyweight bridge with no mention of the band — user-reported
    // 2026-09-07. Same bug class as the #290 cool-down stretches (an item
    // borrowing another exercise's id shows the wrong how-to); #290 explicitly
    // waved this one through as a "legitimate variant", which it isn't.
    "band-glute-bridge": { resist: true, title: "Band Glute Bridge", search: "banded glute bridge resistance band above knees", sets: "3 × 15", rest: "45 sec between sets · 30 sec before next", desc: "Loop a light band just ABOVE your knees. Lie on your back, knees bent, feet flat and hip-width apart. Press your knees OUTWARD into the band and hold that outward tension for the entire set — that is what makes this different from the plain bridge. Drive your hips up by squeezing your glutes hard; body forms a straight line from shoulders to knees. Hold 1 second at the top, then lower slowly. The band recruits the glute medius on top of the main hip drive. The lift comes from your glutes — never from arching your lower back.", safe: "therapeutic" },
    "lateral-walk": { resist: true, title: "Band Lateral Walk", search: "resistance band lateral walk glute", sets: "3 × 12 each way", rest: "45 sec between sets · 30 sec before next", desc: "Band around ankles. Sink into a slight squat and hold that position throughout. Step sideways maintaining tension at all times. Targets the glute medius — the hip stabilizer that protects your lower back and knees.", safe: "back-safe" },
    "pallof-press": { resist: true, title: "Pallof Press", search: "pallof press band anti rotation core", sets: "3 × 10 each side", rest: "45 sec between sets", desc: "Anchor band at chest height to your side. Stand perpendicular to anchor. Brace core hard and press both hands straight out — hold 2 seconds resisting the band's pull to rotate you. Safest core exercise for herniated discs — never flexes the spine.", safe: "therapeutic" },
    "dead-bug": { title: "Dead Bug", search: "dead bug exercise core", sets: "3 × 8 each side", rest: "45 sec between sets", desc: "Lie on back. Raise both arms toward ceiling and bend both knees to 90°. Press lower back FIRMLY into floor the entire time. Slowly extend right arm overhead and left leg straight simultaneously. Return, switch sides. Approved in herniated disc rehabilitation protocols.", safe: "therapeutic" },
    "face-pull": { resist: true, title: "Band Face Pull", search: "resistance band face pull", sets: "3 × 15", rest: "45 sec between sets", desc: "Anchor band at face height. Pull band toward your face keeping elbows HIGH. Hands come to either side of face, elbows pointing out. Corrects forward-head and rounded-shoulder posture from desk work.", safe: "back-safe" },
    "band-rdl": { resist: true, title: "Band Romanian Deadlift", search: "resistance band romanian deadlift", sets: "3 × 10", rest: "60 sec between sets · 30 sec before next", desc: "Stand on band, hold one end in each hand. Hinge at hips by pushing hips BACKWARD — only 30–40°, not a full RDL. Back flat and neutral throughout. Stop and replace with Glute Bridge if any disc pain triggers.", safe: "monitor" },
    "band-ohp": { resist: true, title: "Seated Band Overhead Press", search: "resistance band seated overhead press", sets: "3 × 10", rest: "60 sec between sets · 30 sec before next", desc: "Sit on sturdy chair, band looped under both feet. Press both hands overhead until arms fully extended, then slowly lower. Seated position prevents lumbar hyperextension that can compress herniated discs.", safe: "back-safe" },
    "band-curl": { resist: true, title: "Band Bicep Curl", search: "resistance band bicep curl", sets: "3 × 12", rest: "45 sec between sets · 30 sec before next", desc: "Stand on band, palms facing forward. Keep elbows pinned to sides throughout. Curl both hands toward shoulders, hold 2 seconds at top, lower for 3 seconds. Slow tempo builds more muscle than fast reps.", safe: "back-safe" },
    "band-tricep": { resist: true, title: "Band Tricep Pushdown", search: "resistance band tricep pushdown", sets: "3 × 12", rest: "45 sec between sets · 30 sec before next", desc: "Anchor band above head at door frame. Elbows pinned tightly to sides — they must not move. Push both hands down until arms fully extended, squeeze triceps hard at bottom.", safe: "back-safe" },
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
    // #315 — band ISOLATION moves for the "One Muscle at a Time" plan. All
    // resistance-band, all done standing / seated / supported with a neutral
    // spine (no spinal loading), so they stay back-safe for L4/L5 · L5/S1.
    "band-chest-fly": { resist: true, title: "Standing Band Chest Fly", search: "standing band chest fly", sets: "3 × 12", rest: "45s between sets", desc: "Anchor the band behind you at chest height. Hold one end in each hand, arms out to the sides with a slight elbow bend. Brace your core and stand tall — do NOT arch your lower back. Bring both hands together in front of your chest in a wide hugging arc, squeeze the chest for 1 second, then control the return. Standing removes all spinal compression.", safe: "back-safe" },
    "band-low-fly": { resist: true, title: "Band Low-to-High Fly", search: "band low to high chest fly upper chest", sets: "3 × 12", rest: "45s between sets", desc: "Anchor the band low behind you, near the floor. Start with hands down by your hips, palms forward. Keeping the arms fairly straight with a soft elbow, sweep both hands up and together to about shoulder height in a scooping arc. Squeeze the upper chest, lower slowly. Stay tall and braced — no leaning back.", safe: "back-safe" },
    "band-lat-pulldown": { resist: true, title: "Band Lat Pulldown", search: "resistance band lat pulldown kneeling", sets: "3 × 12", rest: "60s between sets", desc: "Anchor the band high overhead (top of a door frame). Kneel tall or stand with a tall, neutral spine. Hold one end in each hand, arms extended overhead. Pull both hands down and slightly out toward your shoulders, driving the elbows down and squeezing your lats. Control the return. Keep the torso upright — do not lean back or round.", safe: "back-safe" },
    "band-straight-arm-pulldown": { resist: true, title: "Band Straight-Arm Pulldown", search: "band straight arm pulldown lat", sets: "3 × 12", rest: "45s between sets", desc: "Anchor the band high. Stand tall, arms extended overhead holding the band. Keeping your arms straight, pull the band down in a wide arc to your thighs using your lats, then slowly return overhead. Brace your core and keep your spine neutral — the movement comes from the shoulders, not the back.", safe: "back-safe" },
    "band-lateral-raise": { resist: true, title: "Band Lateral Raise", search: "resistance band lateral raise side delt", sets: "3 × 15", rest: "45s between sets", desc: "Stand on the middle of the band, one end in each hand at your sides. Stand tall, core braced. With a slight elbow bend, raise both arms out to the sides until they reach shoulder height, leading with the elbows. Pause, then lower slowly. Do not swing or lean — keep the spine still and let the side shoulders do the work.", safe: "back-safe" },
    "band-front-raise": { resist: true, title: "Band Front Raise", search: "resistance band front raise shoulder", sets: "3 × 12", rest: "45s between sets", desc: "Stand on the band, one end in each hand in front of your thighs, palms down. Keeping the arms straight, raise both hands forward and up to shoulder height. Pause, then lower slowly. Brace your core so you do not lean back to help — the front of the shoulder should do all the work.", safe: "back-safe" },
    "band-rear-delt-fly": { resist: true, title: "Standing Band Rear Delt Fly", search: "band rear delt fly standing", sets: "3 × 15", rest: "45s between sets", desc: "Anchor the band in front of you at chest height, or hold it with arms crossed. Stand tall with arms extended forward. Pull both hands apart and back in a wide arc, squeezing the rear shoulders and upper back. Keep your torso upright and still — do NOT bend forward. Control the return.", safe: "back-safe" },
    "band-hammer-curl": { resist: true, title: "Band Hammer Curl", search: "resistance band hammer curl", sets: "3 × 12", rest: "45s between sets", desc: "Stand on the band, one end in each hand, palms facing each other (thumbs up). Keep your elbows pinned to your sides. Curl both hands up toward your shoulders keeping the neutral grip, squeeze, then lower for 3 seconds. Stay tall and still — no swinging or leaning back.", safe: "back-safe" },
    "band-concentration-curl": { resist: true, title: "Seated Band Concentration Curl", search: "seated concentration curl band", sets: "3 × 10 each", rest: "45s between sets", desc: "Sit on a sturdy chair, feet flat. Loop the band under one foot and hold that end with the same-side hand, the back of your upper arm resting against the inside of your thigh. Curl the hand toward your shoulder, squeeze the bicep hard, lower slowly. Switch sides. The seated, braced position keeps all load off your spine.", safe: "back-safe" },
    "band-overhead-tricep": { resist: true, title: "Band Overhead Tricep Extension", search: "band overhead tricep extension", sets: "3 × 12", rest: "45s between sets", desc: "Stand on the band and reach one end overhead with both hands, elbows pointing up and staying close to your head. Extend both hands straight up until the arms lock out, squeezing the triceps, then lower slowly behind your head. Brace your core hard — do NOT arch your lower back as you press up.", safe: "back-safe" },
    "band-tricep-kickback": { resist: true, title: "Band Tricep Kickback", search: "resistance band tricep kickback", sets: "3 × 12 each", rest: "45s between sets", desc: "Anchor the band low in front of you. Stagger your stance and rest your free hand on your front thigh for support, keeping your back flat and nearly upright (only a slight hinge). Tuck the working elbow to your side, then extend the hand straight back until the arm locks, squeezing the tricep. Return slowly. Switch sides.", safe: "back-safe" },
    "band-leg-curl": { resist: true, title: "Standing Band Hamstring Curl", search: "standing band hamstring leg curl", sets: "3 × 12 each", rest: "45s between sets", desc: "Anchor the band low in front of you and loop the other end around one ankle. Hold a wall or chair for balance and stand tall. Keeping your thigh vertical, curl your heel up toward your glute against the band, squeeze the hamstring, then lower slowly. Switch legs. Standing and supported — no spinal loading.", safe: "back-safe" },
    "band-glute-kickback": { resist: true, title: "Standing Band Glute Kickback", search: "standing band glute kickback", sets: "3 × 12 each", rest: "45s between sets", desc: "Anchor the band low in front of you and loop it around one ankle. Hold a wall for balance, stand tall with a braced core. Keeping the leg fairly straight, push it straight back behind you using your glute — only about 20–30°. Squeeze at the top, return slowly. Do NOT arch your lower back to get more range. Switch legs.", safe: "back-safe" },
    "band-calf-raise": { resist: true, title: "Band Calf Raise", search: "band calf raise standing", sets: "3 × 15", rest: "45s between sets", desc: "Stand on the middle of the band, holding an end in each hand at your sides for light tension. Stand tall. Rise up onto the balls of your feet as high as you can, squeeze the calves at the top, then lower slowly under control. Hold a wall for balance if needed. Upright and back-safe.", safe: "back-safe" },
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
      { id: "band-glute-bridge", name: "Band Glute Bridge", sets: "3 × 15", rest: "45s sets · 30s next" },
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

  // #315 — "One Muscle at a Time" (Isolation) plan: band-only sessions that
  // each focus on a SINGLE muscle group, for the days you want to isolate
  // rather than train full-body. Every move is back-safe (upright / seated /
  // supported, neutral spine). Do any 2–3 of these per week, rotating.
  var isoChest = [
    { section: "Warm-Up", badge: "3 min", role: "band", num: "01", items: [
      { id: "arm-swings", name: "Arm Circles + Shoulder Rolls", sets: "10 each", rest: "No rest" },
      { id: "band-pull-apart", name: "Band Pull-Apart", sets: "15 reps", rest: "No rest" },
    ] },
    { section: "Chest — Main Work", badge: "18 min", role: "iso", num: "02", items: [
      { id: "band-chest-press", name: "Standing Band Chest Press", sets: "3 × 12", rest: "45s between sets" },
      { id: "band-chest-fly", name: "Standing Band Chest Fly", sets: "3 × 12", rest: "45s between sets" },
      { id: "band-low-fly", name: "Band Low-to-High Fly (Upper Chest)", sets: "3 × 12", rest: "45s between sets" },
      { id: "incline-pushup", name: "Incline Push-Up", sets: "3 × 8–12", rest: "60s between sets" },
    ] },
    { section: "Cool-Down", badge: "3 min", role: "mil", num: "03", items: [
      { id: "chest-stretch", name: "Doorway Chest Stretch", sets: "30s × 2 sides", rest: "15s to switch" },
      { id: "box-breathing", name: "Box Breathing (4-4-4-4)", sets: "4–6 cycles", rest: "End of session" },
    ] },
  ];

  var isoBack = [
    { section: "Warm-Up", badge: "3 min", role: "band", num: "01", items: [
      { id: "cat-cow", name: "Cat-Cow Stretch", sets: "10 reps", rest: "No rest" },
      { id: "band-pull-apart", name: "Band Pull-Apart", sets: "15 reps", rest: "No rest" },
    ] },
    { section: "Back — Main Work", badge: "18 min", role: "iso", num: "02", items: [
      { id: "band-lat-pulldown", name: "Band Lat Pulldown", sets: "3 × 12", rest: "60s between sets" },
      { id: "band-row", name: "Band Seated Row", sets: "3 × 12", rest: "60s between sets" },
      { id: "band-straight-arm-pulldown", name: "Band Straight-Arm Pulldown", sets: "3 × 12", rest: "45s between sets" },
      { id: "face-pull", name: "Band Face Pull", sets: "3 × 15", rest: "45s between sets" },
    ] },
    { section: "Cool-Down", badge: "2 min", role: "mil", num: "03", items: [
      { id: "box-breathing", name: "Box Breathing (4-4-4-4)", sets: "4–6 cycles", rest: "End of session" },
    ] },
  ];

  var isoShoulders = [
    { section: "Warm-Up", badge: "3 min", role: "band", num: "01", items: [
      { id: "arm-swings", name: "Arm Circles + Shoulder Rolls", sets: "10 each", rest: "No rest" },
      { id: "band-pull-apart", name: "Band Pull-Apart", sets: "15 reps", rest: "No rest" },
    ] },
    { section: "Shoulders — Main Work", badge: "18 min", role: "iso", num: "02", items: [
      { id: "band-ohp", name: "Seated Band Overhead Press", sets: "3 × 10", rest: "60s between sets" },
      { id: "band-lateral-raise", name: "Band Lateral Raise", sets: "3 × 15", rest: "45s between sets" },
      { id: "band-front-raise", name: "Band Front Raise", sets: "3 × 12", rest: "45s between sets" },
      { id: "band-rear-delt-fly", name: "Standing Band Rear Delt Fly", sets: "3 × 15", rest: "45s between sets" },
    ] },
    { section: "Cool-Down", badge: "3 min", role: "mil", num: "03", items: [
      { id: "chest-stretch", name: "Doorway Chest Stretch", sets: "30s × 2 sides", rest: "15s to switch" },
      { id: "box-breathing", name: "Box Breathing (4-4-4-4)", sets: "4–6 cycles", rest: "End of session" },
    ] },
  ];

  var isoBiceps = [
    { section: "Warm-Up", badge: "2 min", role: "band", num: "01", items: [
      { id: "arm-swings", name: "Arm Circles + Shoulder Rolls", sets: "10 each", rest: "No rest" },
    ] },
    { section: "Biceps — Main Work", badge: "15 min", role: "iso", num: "02", items: [
      { id: "band-curl", name: "Band Bicep Curl", sets: "3 × 12", rest: "45s between sets" },
      { id: "band-hammer-curl", name: "Band Hammer Curl", sets: "3 × 12", rest: "45s between sets" },
      { id: "band-concentration-curl", name: "Seated Band Concentration Curl", sets: "3 × 10 each", rest: "45s between sets" },
      { id: "band-curl", name: "Band Curl — 21s Finisher", sets: "1 × 21", rest: "End of session" },
    ] },
    { section: "Cool-Down", badge: "2 min", role: "mil", num: "03", items: [
      { id: "box-breathing", name: "Box Breathing (4-4-4-4)", sets: "4–6 cycles", rest: "End of session" },
    ] },
  ];

  var isoTriceps = [
    { section: "Warm-Up", badge: "2 min", role: "band", num: "01", items: [
      { id: "arm-swings", name: "Arm Circles + Shoulder Rolls", sets: "10 each", rest: "No rest" },
    ] },
    { section: "Triceps — Main Work", badge: "15 min", role: "iso", num: "02", items: [
      { id: "band-tricep", name: "Band Tricep Pushdown", sets: "3 × 12", rest: "45s between sets" },
      { id: "band-overhead-tricep", name: "Band Overhead Tricep Extension", sets: "3 × 12", rest: "45s between sets" },
      { id: "band-tricep-kickback", name: "Band Tricep Kickback", sets: "3 × 12 each", rest: "45s between sets" },
      { id: "diamond-pushup", name: "Diamond Push-Up (Knees if Needed)", sets: "3 × 6–10", rest: "60s between sets" },
    ] },
    { section: "Cool-Down", badge: "2 min", role: "mil", num: "03", items: [
      { id: "box-breathing", name: "Box Breathing (4-4-4-4)", sets: "4–6 cycles", rest: "End of session" },
    ] },
  ];

  var isoLegs = [
    { section: "Warm-Up", badge: "4 min", role: "band", num: "01", items: [
      { id: "leg-swings", name: "Leg Swings (Front/Back + Side)", sets: "10 each", rest: "No rest" },
      { id: "glute-bridge", name: "Glute Bridge Warm-Up (No Band)", sets: "15 reps", rest: "No rest" },
    ] },
    { section: "Legs — Main Work", badge: "20 min", role: "iso", num: "02", items: [
      { id: "band-squat", name: "Band Assisted Squat", sets: "3 × 12", rest: "60s between sets" },
      { id: "band-leg-curl", name: "Standing Band Hamstring Curl", sets: "3 × 12 each", rest: "45s between sets" },
      { id: "band-glute-bridge", name: "Band Glute Bridge", sets: "3 × 15", rest: "45s between sets" },
      { id: "band-glute-kickback", name: "Standing Band Glute Kickback", sets: "3 × 12 each", rest: "45s between sets" },
      { id: "band-calf-raise", name: "Band Calf Raise", sets: "3 × 15", rest: "45s between sets" },
    ] },
    { section: "Cool-Down", badge: "4 min", role: "mil", num: "03", items: [
      { id: "quad-stretch", name: "Standing Quad Stretch", sets: "45s × 2 sides", rest: "15s to switch" },
      { id: "hip-90-90", name: "90/90 Hip Stretch", sets: "45s × 2 sides", rest: "15s to switch" },
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

  // #320 — "Split Routine", per the nutritionist's 2026-09-08 note. A 4-day
  // repeating cycle (Day 1 → Day 2 → Day 3 → Rest → repeat), NOT a fixed
  // weekday grid:
  //   Day 1: chest, triceps, front shoulders, abs
  //   Day 2: back, biceps, rear shoulders, abs
  //   Day 3: legs
  //   Day 4: rest, then restart at Day 1
  // Every exercise is 3 × 10–12 per their prescription, with band tension as
  // the load: pick a band where the last 2–3 reps are hard but your form holds.
  //
  // ABS ADAPTATION (deliberate deviation, do not "fix"): the note says abs on
  // Days 1 and 2. Sit-ups / crunches / any loaded spinal flexion are on this
  // app's permanent avoid-list — contraindicated for L4/L5 + L5/S1 herniation.
  // Pallof Press (anti-rotation) and Dead Bug are used instead; both are tagged
  // `therapeutic` in the catalog and train the same deep core without ever
  // flexing the spine.
  //
  // This is the NEXT block, not a replacement — the nutritionist explicitly
  // said to run the Isolation plan consistently for a couple of months first.
  var splitDay1 = [
    { section: "Warm-Up", badge: "4 min", role: "band", num: "01", items: [
      { id: "arm-swings", name: "Arm Circles + Shoulder Rolls", sets: "10 each", rest: "No rest" },
      { id: "band-pull-apart", name: "Band Pull-Apart", sets: "15 reps", rest: "No rest" },
    ] },
    { section: "Chest · Triceps · Front Delts", badge: "22 min", role: "split", num: "02", items: [
      { id: "band-chest-press", name: "Standing Band Chest Press", sets: "3 × 10–12", rest: "60s between sets" },
      { id: "band-chest-fly", name: "Standing Band Chest Fly", sets: "3 × 10–12", rest: "60s between sets" },
      { id: "band-front-raise", name: "Band Front Raise", sets: "3 × 10–12", rest: "45s between sets" },
      { id: "band-tricep", name: "Band Tricep Pushdown", sets: "3 × 10–12", rest: "45s between sets" },
      { id: "band-overhead-tricep", name: "Band Overhead Tricep Extension", sets: "3 × 10–12", rest: "45s between sets" },
    ] },
    { section: "Core (disc-safe)", badge: "6 min", role: "safe", num: "03", items: [
      { id: "pallof-press", name: "Pallof Press", sets: "3 × 10 each side", rest: "45s between sets" },
      { id: "dead-bug", name: "Dead Bug", sets: "3 × 10 each side", rest: "45s between sets" },
    ] },
    { section: "Cool-Down", badge: "3 min", role: "mil", num: "04", items: [
      { id: "chest-stretch", name: "Doorway Chest Stretch", sets: "30s × 2 sides", rest: "15s to switch" },
      { id: "box-breathing", name: "Box Breathing (4-4-4-4)", sets: "4–6 cycles", rest: "End of session" },
    ] },
  ];

  var splitDay2 = [
    { section: "Warm-Up", badge: "4 min", role: "band", num: "01", items: [
      { id: "cat-cow", name: "Cat-Cow Stretch", sets: "10 reps", rest: "No rest" },
      { id: "band-pull-apart", name: "Band Pull-Apart", sets: "15 reps", rest: "No rest" },
    ] },
    { section: "Back · Biceps · Rear Delts", badge: "22 min", role: "split", num: "02", items: [
      { id: "band-lat-pulldown", name: "Band Lat Pulldown", sets: "3 × 10–12", rest: "60s between sets" },
      { id: "band-row", name: "Band Seated Row", sets: "3 × 10–12", rest: "60s between sets" },
      { id: "band-rear-delt-fly", name: "Standing Band Rear Delt Fly", sets: "3 × 10–12", rest: "45s between sets" },
      { id: "band-curl", name: "Band Bicep Curl", sets: "3 × 10–12", rest: "45s between sets" },
      { id: "band-hammer-curl", name: "Band Hammer Curl", sets: "3 × 10–12", rest: "45s between sets" },
    ] },
    { section: "Core (disc-safe)", badge: "6 min", role: "safe", num: "03", items: [
      { id: "pallof-press", name: "Pallof Press", sets: "3 × 10 each side", rest: "45s between sets" },
      { id: "dead-bug", name: "Dead Bug", sets: "3 × 10 each side", rest: "45s between sets" },
    ] },
    { section: "Cool-Down", badge: "3 min", role: "mil", num: "04", items: [
      { id: "box-breathing", name: "Box Breathing (4-4-4-4)", sets: "4–6 cycles", rest: "End of session" },
    ] },
  ];

  var splitDay3 = [
    { section: "Warm-Up", badge: "4 min", role: "band", num: "01", items: [
      { id: "leg-swings", name: "Leg Swings (Front/Back + Side)", sets: "10 each", rest: "No rest" },
      { id: "glute-bridge", name: "Glute Bridge Warm-Up (No Band)", sets: "15 reps", rest: "No rest" },
    ] },
    { section: "Legs", badge: "24 min", role: "split", num: "02", items: [
      { id: "band-squat", name: "Band Assisted Squat", sets: "3 × 10–12", rest: "60s between sets" },
      { id: "band-leg-curl", name: "Standing Band Hamstring Curl", sets: "3 × 10–12 each", rest: "45s between sets" },
      { id: "band-glute-bridge", name: "Band Glute Bridge", sets: "3 × 10–12", rest: "45s between sets" },
      { id: "band-glute-kickback", name: "Standing Band Glute Kickback", sets: "3 × 10–12 each", rest: "45s between sets" },
      { id: "lateral-walk", name: "Band Lateral Walk", sets: "3 × 10–12 each way", rest: "45s between sets" },
      { id: "band-calf-raise", name: "Band Calf Raise", sets: "3 × 10–12", rest: "45s between sets" },
    ] },
    { section: "Cool-Down", badge: "4 min", role: "mil", num: "03", items: [
      { id: "quad-stretch", name: "Standing Quad Stretch", sets: "45s × 2 sides", rest: "15s to switch" },
      { id: "hip-90-90", name: "90/90 Hip Stretch", sets: "45s × 2 sides", rest: "15s to switch" },
    ] },
  ];

  // #318: the per-program weekly schedule. Lifted out of the panel builders in
  // strength_forge.js so the SAME data drives the on-screen strip AND the
  // printable sheet (user asked to print the schedule alongside the workouts)
  // — one source of truth, no risk of the printout drifting from the app.
  //
  // `on` lists the indices that are TRAINING days (the rest are rest days).
  // Band/Military alternate train/rest; the isolation plan has no rest slots —
  // all six are sessions you rotate through, which is why `on` is explicit per
  // program instead of the old hardcoded "days 1, 3 and 5" rule.
  var schedules = {
    band: {
      days: ["Full Body A", "Rest", "Full Body B", "Rest", "Full Body A", "Rest / Walk"],
      on: [0, 2, 4],
      note: "Never train on consecutive days — your recovery needs that full rest day.",
    },
    mil: {
      days: ["Push + Core", "Rest", "Pull + Legs", "Rest", "Full Body", "Walk / Mobility"],
      on: [0, 2, 4],
      note: "Three sessions a week with a rest day between each.",
    },
    iso: {
      days: ["Chest", "Back", "Shoulders", "Biceps", "Triceps", "Legs"],
      on: [0, 1, 2, 3, 4, 5],
      note: "Rotate through these — do any 2–3 per week. Don't train the same muscle on consecutive days.",
    },
    // #320: a repeating 4-day CYCLE, not a Mon–Sat week — after the rest day
    // you start again at Day 1, so the cycle drifts across the calendar week.
    split: {
      days: [
        "Chest · Triceps · Front Delts · Abs",
        "Back · Biceps · Rear Delts · Abs",
        "Legs",
        "Rest — then repeat from Day 1",
      ],
      on: [0, 1, 2],
      note: "A repeating 4-day cycle, not a fixed week: Day 1 → 2 → 3 → Rest → back to Day 1. Give legs extra recovery — never run Day 3 back-to-back with the next Day 1 if your legs are still sore.",
    },
  };

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
    isoChest: isoChest,
    isoBack: isoBack,
    isoShoulders: isoShoulders,
    isoBiceps: isoBiceps,
    isoTriceps: isoTriceps,
    isoLegs: isoLegs,
    splitDay1: splitDay1,
    splitDay2: splitDay2,
    splitDay3: splitDay3,
    flarePhases: flarePhases,
    schedules: schedules,
    avoidList: avoidList,
    warnSigns: warnSigns,
    SAFE_LABELS: SAFE_LABELS,
    SAFE_CLASS: SAFE_CLASS,
    googleLink: googleLink,
  };
})();
