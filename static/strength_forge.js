/* ============================================================
 * Strength Forge — renderer + interactions (#282, Phase A)
 * ------------------------------------------------------------
 * Vanilla port of the prototype's React rendering (StrengthForge.jsx +
 * components.jsx). Renders client-side from window.SFData, the same way
 * the board (renderBoard) / goals / calendar render from data. Built
 * entirely with createElement/textContent — NO innerHTML (security hook
 * + XSS hygiene). Class-driven; all color/theme lives in style.css under
 * Soft Concrete tokens.
 *
 * Phase A = static reference (read-only). The 30 inline SVG diagrams
 * (Phase A.1) and interactive tracking (Phase B) are follow-ups; the
 * modal's Google-Images link covers photo reference meanwhile.
 * ============================================================ */
(function () {
  "use strict";

  var SF = window.SFData;
  var root = document.getElementById("sf-root");
  if (!SF || !root) return; // page-specific; bail elsewhere

  // -- tiny DOM helper (hook-safe; no innerHTML) -----------------
  function el(tag, opts, kids) {
    var n = document.createElement(tag);
    opts = opts || {};
    if (opts.cls) n.className = opts.cls;
    if (opts.text != null) n.textContent = opts.text;
    if (opts.attrs) Object.keys(opts.attrs).forEach(function (k) { n.setAttribute(k, opts.attrs[k]); });
    if (opts.on) Object.keys(opts.on).forEach(function (k) { n.addEventListener(k, opts.on[k]); });
    (kids || []).forEach(function (k) {
      if (k == null) return;
      n.appendChild(typeof k === "string" ? document.createTextNode(k) : k);
    });
    return n;
  }

  // ============================================================
  // MODAL
  // ============================================================
  var modalOverlay, modalTitle, modalBody;

  function buildModal() {
    modalTitle = el("div", { cls: "sf-modal-title" });
    var closeBtn = el("button", {
      cls: "sf-modal-close", text: "✕",
      attrs: { type: "button", "aria-label": "Close" },
      on: { click: closeModal },
    });
    modalBody = el("div", { cls: "sf-modal-body" });
    var card = el("div", { cls: "sf-modal", on: { click: function (e) { e.stopPropagation(); } } }, [
      el("div", { cls: "sf-modal-head" }, [modalTitle, closeBtn]),
      modalBody,
    ]);
    modalOverlay = el("div", {
      cls: "sf-modal-overlay", attrs: { hidden: "hidden" },
      on: { click: closeModal },
    }, [card]);
    document.body.appendChild(modalOverlay);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !modalOverlay.hasAttribute("hidden")) closeModal();
    });
  }

  function closeModal() { modalOverlay.setAttribute("hidden", "hidden"); }

  // data: { title, search, sets, rest, desc, safe, tip }
  function openModal(data) {
    modalTitle.textContent = data.title || "";
    while (modalBody.firstChild) modalBody.removeChild(modalBody.firstChild);

    // SVG diagram — clone the matching server-rendered one (hook-safe;
    // cloneNode, never innerHTML). #282 Phase A.1.
    if (data.diagramKey) {
      var src = document.querySelector('#sf-diagrams .sf-diagram[data-diagram="' + data.diagramKey + '"]');
      if (src && src.firstElementChild) {
        var dWrap = el("div", { cls: "sf-modal-diagram" });
        dWrap.appendChild(src.firstElementChild.cloneNode(true));
        modalBody.appendChild(dWrap);
      }
    }

    // Google Images link (real photos / GIFs)
    var googleWrap = el("div", { cls: "sf-modal-google" }, [
      el("a", {
        cls: "sf-modal-google-link",
        attrs: { href: SF.googleLink(data.search || data.title || ""), target: "_blank", rel: "noopener noreferrer" },
      }, [
        el("span", { text: "🔍" }),
        el("span", { text: "See Real Photos — Google Images" }),
        el("span", { cls: "sf-modal-google-arrow", text: "↗" }),
      ]),
      el("div", { cls: "sf-modal-google-note", text: "opens in browser · real photos & GIFs" }),
    ]);
    modalBody.appendChild(googleWrap);

    var info = el("div", { cls: "sf-modal-info" });
    if (data.safe && SF.SAFE_LABELS[data.safe]) {
      info.appendChild(el("div", {
        cls: "sf-modal-safe " + (SF.SAFE_CLASS[data.safe] || ""),
        text: SF.SAFE_LABELS[data.safe],
      }));
    }
    if (data.sets) info.appendChild(el("div", { cls: "sf-modal-meta sf-meta-sets", text: "📊 " + data.sets }));
    if (data.rest) info.appendChild(el("div", { cls: "sf-modal-meta sf-meta-rest", text: "⏱ " + data.rest }));
    info.appendChild(el("div", { cls: "sf-modal-how-label", text: "How to do it" }));
    info.appendChild(el("div", { cls: "sf-modal-how", text: data.desc || "" }));
    if (data.tip) info.appendChild(el("div", { cls: "sf-modal-tip", text: "💡 " + data.tip }));
    if (data.safe === "monitor") {
      info.appendChild(el("div", { cls: "sf-modal-warn-monitor", text: "⚠ Stop immediately and replace with Glute Bridge if any lower back or disc pain occurs." }));
    }
    if (data.safe === "therapeutic") {
      info.appendChild(el("div", { cls: "sf-modal-warn-therapeutic", text: "✓ Specifically recommended for L4/L5 and L5/S1 herniated discs. Do not skip this exercise." }));
    }
    modalBody.appendChild(info);
    modalOverlay.removeAttribute("hidden");
  }

  function openExerciseModal(id) {
    var ex = SF.exercises[id];
    if (!ex) return;
    openModal({ title: ex.title, search: ex.search, sets: ex.sets, rest: ex.rest, desc: ex.desc, safe: ex.safe, diagramKey: id });
  }

  function openFlareModal(fx) {
    openModal({ title: fx.name, search: fx.search, sets: fx.duration, rest: fx.rest, desc: fx.how, tip: fx.tip, diagramKey: fx.diagramId });
  }

  // ============================================================
  // SHARED RENDER PIECES
  // ============================================================
  function exRow(item, role) {
    var info = SF.exercises[item.id] || {};
    var infoBtn = el("button", {
      cls: "sf-exrow-info", text: "ℹ️",
      attrs: { type: "button", title: "Instructions + photos", "aria-label": "Instructions for " + item.name },
      on: { click: function () { openExerciseModal(item.id); } },
    });
    var nameCol = el("div", { cls: "sf-exrow-main" }, [
      el("div", { cls: "sf-exrow-name", text: item.name }),
      info.safe ? el("div", { cls: "sf-exrow-safe " + (SF.SAFE_CLASS[info.safe] || ""), text: SF.SAFE_LABELS[info.safe] }) : null,
    ]);
    var sets = el("div", { cls: "sf-exrow-sets sf-role-" + role, text: item.sets });
    return el("div", { cls: "sf-exrow" }, [infoBtn, nameCol, sets]);
  }

  function workSec(sec, role) {
    var head = el("div", { cls: "sf-worksec-head" }, [
      el("div", { cls: "sf-worksec-num", text: sec.num }),
      el("div", { cls: "sf-worksec-title", text: sec.section }),
      el("div", { cls: "sf-worksec-badge sf-role-" + sec.role, text: sec.badge }),
    ]);
    var list = el("div", { cls: "sf-worksec-list" });
    sec.items.forEach(function (item, i) {
      list.appendChild(exRow(item, role));
      if (i < sec.items.length - 1) {
        list.appendChild(el("div", { cls: "sf-restdiv" }, [
          el("span", { cls: "sf-restdiv-rule" }),
          el("span", { cls: "sf-restdiv-text", text: "⏱ " + item.rest }),
          el("span", { cls: "sf-restdiv-rule" }),
        ]));
      }
    });
    return el("div", { cls: "sf-worksec" }, [head, list]);
  }

  function sched(days, role) {
    var grid = el("div", { cls: "sf-sched" });
    days.forEach(function (day, i) {
      var on = i === 0 || i === 2 || i === 4;
      grid.appendChild(el("div", { cls: "sf-sched-day" + (on ? " on sf-role-" + role : "") }, [
        el("div", { cls: "sf-sched-num", text: "Day " + (i + 1) }),
        el("div", { cls: "sf-sched-label", text: day }),
      ]));
    });
    return grid;
  }

  function notesBox(notes, role) {
    var box = el("div", { cls: "sf-notes" }, [el("div", { cls: "sf-notes-title", text: "KEY RULES" })]);
    notes.forEach(function (n) {
      box.appendChild(el("div", { cls: "sf-note" }, [
        el("span", { cls: "sf-note-dash sf-role-" + role, text: "—" }),
        el("span", { cls: "sf-note-text", text: n }),
      ]));
    });
    return box;
  }

  function intro(role, title, body) {
    return el("div", { cls: "sf-intro sf-intro--" + role }, [
      el("div", { cls: "sf-intro-title sf-role-" + role, text: title }),
      el("div", { cls: "sf-intro-body", text: body }),
    ]);
  }

  function sectionLabel(text) {
    return el("div", { cls: "sf-section-label" }, [
      el("span", { text: text }),
      el("span", { cls: "sf-section-rule" }),
    ]);
  }

  // ============================================================
  // PANELS
  // ============================================================
  function buildBandPanel() {
    var panel = el("div", { cls: "sf-panel", attrs: { "data-tab": "band" } });
    panel.appendChild(intro("band", "Resistance Band Training",
      "Full-body strength and fat-loss using resistance bands only. Every exercise protects your L4/L5 and L5/S1 discs. Tap ℹ️ for a real photo link and full instructions."));
    panel.appendChild(sched(["Full Body A", "Rest", "Full Body B", "Rest", "Full Body A", "Rest / Walk"], "band"));

    var planMount = el("div", { cls: "sf-plan-mount" });
    var notesMount = el("div");
    var bw = "A";
    function renderPlan() {
      while (planMount.firstChild) planMount.removeChild(planMount.firstChild);
      var plan = bw === "A" ? SF.bandPlanA : SF.bandPlanB;
      plan.forEach(function (sec) { planMount.appendChild(workSec(sec, "band")); });
    }
    var toggle = el("div", { cls: "sf-toggle-row" }, ["A", "B"].map(function (w) {
      return el("button", {
        cls: "sf-toggle-btn sf-role-band" + (w === bw ? " active" : ""),
        text: "Workout " + w, attrs: { type: "button" },
        on: { click: function () {
          bw = w; renderPlan();
          toggle.querySelectorAll(".sf-toggle-btn").forEach(function (b, i) {
            b.classList.toggle("active", (i === 0 ? "A" : "B") === bw);
          });
        } },
      });
    }));
    panel.appendChild(toggle);
    panel.appendChild(planMount);
    renderPlan();
    notesMount.appendChild(notesBox([
      "Never train on consecutive days — your recovery needs that full rest day.",
      "If your lower back flares during any exercise, stop immediately. Switch to the Flare-Up tab.",
      "Start with light bands for the first 2 weeks. Let connective tissue adapt.",
      "Tempo matters more than resistance. Slow, controlled reps build more muscle.",
      "The Pallof Press and Dead Bug are non-negotiable — they protect your discs long-term.",
      "Progress every 2–3 weeks by moving to a heavier band, not rushing more reps.",
      "A 15–20 min walk on rest days improves fat loss and spinal health.",
    ], "band"));
    panel.appendChild(notesMount);
    return panel;
  }

  function buildMilPanel() {
    var panel = el("div", { cls: "sf-panel", attrs: { "data-tab": "mil", hidden: "hidden" } });
    panel.appendChild(intro("mil", "Military Calisthenics",
      "Adapted from military PT — fully modified for L4/L5 and L5/S1 disc protection. No sit-ups, no burpees, no jumping. Tap ℹ️ for a real photo link and full instructions."));
    panel.appendChild(sched(["Push + Core", "Rest", "Pull + Legs", "Rest", "Full Body", "Walk / Mobility"], "mil"));

    var sessions = [
      { key: "1", label: "Session 1 — Push+Core" },
      { key: "2", label: "Session 2 — Pull+Legs" },
      { key: "3", label: "Session 3 — Circuit" },
    ];
    var ms = "1";
    var circuitMount = el("div");
    var planMount = el("div", { cls: "sf-plan-mount" });
    function renderPlan() {
      while (planMount.firstChild) planMount.removeChild(planMount.firstChild);
      while (circuitMount.firstChild) circuitMount.removeChild(circuitMount.firstChild);
      if (ms === "3") {
        circuitMount.appendChild(el("div", { cls: "sf-circuit" }, [
          el("div", { cls: "sf-circuit-title sf-role-mil", text: "Circuit Format" }),
          el("div", { cls: "sf-circuit-body" }, [
            "All 5 exercises back-to-back with ",
            el("strong", { text: "20 sec rest" }), " between each. Rest ",
            el("strong", { text: "90 sec" }), " after the full circuit. Complete ",
            el("strong", { text: "3 rounds" }), " total.",
          ]),
        ]));
      }
      var plan = ms === "1" ? SF.milS1 : ms === "2" ? SF.milS2 : SF.milS3;
      plan.forEach(function (sec) { planMount.appendChild(workSec(sec, "mil")); });
    }
    var toggle = el("div", { cls: "sf-toggle-row" }, sessions.map(function (s) {
      return el("button", {
        cls: "sf-toggle-btn sf-role-mil" + (s.key === ms ? " active" : ""),
        text: s.label, attrs: { type: "button" },
        on: { click: function () {
          ms = s.key; renderPlan();
          toggle.querySelectorAll(".sf-toggle-btn").forEach(function (b, i) {
            b.classList.toggle("active", sessions[i].key === ms);
          });
        } },
      });
    }));
    panel.appendChild(toggle);
    panel.appendChild(circuitMount);
    panel.appendChild(planMount);
    renderPlan();
    panel.appendChild(notesBox([
      "Sit-ups and crunches are permanently removed — contraindicated for herniated lumbar discs.",
      "Burpees, jump squats, and any plyometric jumping are excluded.",
      "Three sessions done right beats five done sloppy.",
      "The Session 3 circuit is the fat-loss engine of this plan.",
      "Over weeks 5–8, add push-up variations (wide grip, decline) to increase difficulty.",
      "A doorframe pull-up bar unlocks the most powerful back exercise in calisthenics.",
      "Box breathing at the end of every session is part of the recovery protocol — not optional.",
    ], "mil"));
    return panel;
  }

  function buildFlarePanel() {
    var panel = el("div", { cls: "sf-panel", attrs: { "data-tab": "flare", hidden: "hidden" } });
    panel.appendChild(el("div", { cls: "sf-flare-alert" }, [
      el("span", { cls: "sf-flare-alert-icon", text: "⚠️" }),
      el("div", { cls: "sf-flare-alert-text" }, [
        el("strong", { text: "Stop all normal training immediately during a flare." }),
        " Use this protocol instead. Moving gently is better than rest — but loading the spine will extend your flare significantly.",
      ]),
    ]));

    var fp = SF.flarePhases[0].id;
    var contentMount = el("div");
    function renderPhase() {
      while (contentMount.firstChild) contentMount.removeChild(contentMount.firstChild);
      var phase = SF.flarePhases.filter(function (p) { return p.id === fp; })[0];
      if (!phase) return;
      contentMount.appendChild(el("div", { cls: "sf-intro sf-intro--" + phase.role }, [
        el("div", { cls: "sf-intro-title sf-role-" + phase.role, text: phase.icon + " " + phase.title + " — " + phase.subtitle }),
        el("div", { cls: "sf-intro-body", text: phase.desc }),
      ]));
      var list = el("div", { cls: "sf-flare-list" });
      phase.exercises.forEach(function (fx) {
        list.appendChild(el("div", { cls: "sf-flare-ex" }, [
          el("div", { cls: "sf-flare-ex-head" }, [
            el("div", { cls: "sf-flare-ex-name", text: fx.name }),
            el("button", {
              cls: "sf-flare-ex-how sf-role-" + phase.role, text: "ℹ️ How-to",
              attrs: { type: "button" },
              on: { click: function () { openFlareModal(fx); } },
            }),
          ]),
          el("div", { cls: "sf-flare-ex-meta" }, [
            el("div", { cls: "sf-flare-meta-dur", text: "📊 " + fx.duration }),
            el("div", { cls: "sf-flare-meta-rest", text: "⏱ " + fx.rest }),
          ]),
        ]));
      });
      contentMount.appendChild(list);
    }
    var sel = el("div", { cls: "sf-phase-sel" }, SF.flarePhases.map(function (p) {
      return el("button", {
        cls: "sf-phase-btn sf-role-" + p.role + (p.id === fp ? " active" : ""),
        attrs: { type: "button" },
        on: { click: function () {
          fp = p.id; renderPhase();
          sel.querySelectorAll(".sf-phase-btn").forEach(function (b, i) {
            b.classList.toggle("active", SF.flarePhases[i].id === fp);
          });
        } },
      }, [
        el("div", { cls: "sf-phase-icon", text: p.icon }),
        el("div", { cls: "sf-phase-label", text: p.label }),
        el("div", { cls: "sf-phase-title", text: p.title }),
      ]);
    }));
    panel.appendChild(sel);
    panel.appendChild(contentMount);
    renderPhase();

    // Avoid list
    var avoid = el("div", { cls: "sf-avoid" }, [sectionLabel("🚫 Avoid During Any Flare")]);
    SF.avoidList.forEach(function (a) {
      avoid.appendChild(el("div", { cls: "sf-avoid-item" }, [
        el("div", { cls: "sf-avoid-head", text: "✗ " + a.item }),
        el("div", { cls: "sf-avoid-reason", text: a.reason }),
      ]));
    });
    panel.appendChild(avoid);

    // Warning signs
    var warnWrap = el("div", { cls: "sf-warn-wrap" }, [sectionLabel("🚨 Seek Help If")]);
    var warnBox = el("div", { cls: "sf-warn" });
    SF.warnSigns.forEach(function (w) {
      warnBox.appendChild(el("div", { cls: "sf-warn-item" }, [
        el("span", { cls: "sf-warn-bang", text: "!" }),
        el("span", { cls: "sf-warn-text", text: w }),
      ]));
    });
    warnWrap.appendChild(warnBox);
    panel.appendChild(warnWrap);

    // Recovery mindset
    panel.appendChild(el("div", { cls: "sf-mindset" }, [
      el("div", { cls: "sf-mindset-title", text: "✓ The Recovery Mindset" }),
      el("div", { cls: "sf-mindset-body", text: "Most flare-ups resolve in 3–7 days with this protocol. Your HRT support means your tissue repairs faster than average. The McKenzie Press-Up and Glute Bridge are your two most powerful recovery tools — do them every day until you're back to full training. A flare is not a setback, it's a signal to temporarily shift strategy." }),
    ]));
    return panel;
  }

  // ============================================================
  // HEADER + TABS + ASSEMBLY
  // ============================================================
  function buildHeader() {
    var pills = [
      { label: "Beginner", t: "n" },
      { label: "2–3 Days/Week", t: "n" },
      { label: "Under 30 Min", t: "n" },
      { label: "L4/L5 · L5/S1 Herniation", t: "w" },
      { label: "HRT Active", t: "g" },
      { label: "Testosterone · Anastrozole · DHEA", t: "n" },
      { label: "Weight Loss + Strength", t: "g" },
    ];
    var pillRow = el("div", { cls: "sf-pills" }, pills.map(function (p) {
      return el("span", { cls: "sf-pill" + (p.t === "w" ? " sf-pill-warn" : p.t === "g" ? " sf-pill-good" : ""), text: p.label });
    }));
    return el("div", { cls: "sf-header" }, [
      el("div", { cls: "sf-eyebrow", text: "Personalized Training Program" }),
      el("div", { cls: "sf-title", text: "STRENGTH FORGE" }),
      el("div", { cls: "sf-subtitle", text: "Age 48+ · HRT-Supported · Back-Safe Protocol" }),
      pillRow,
    ]);
  }

  function render() {
    buildModal();
    root.appendChild(buildHeader());

    var panels = {
      band: buildBandPanel(),
      mil: buildMilPanel(),
      flare: buildFlarePanel(),
    };
    var tabsDef = [
      { key: "band", label: "⚡ Bands" },
      { key: "mil", label: "🎖 Military" },
      { key: "flare", label: "🔴 Flare-Up" },
    ];
    var current = "band";
    var tabBar = el("div", { cls: "sf-tabs" }, tabsDef.map(function (t) {
      return el("button", {
        cls: "sf-tab sf-role-" + t.key + (t.key === current ? " active" : ""),
        text: t.label, attrs: { type: "button" },
        on: { click: function () {
          current = t.key;
          tabBar.querySelectorAll(".sf-tab").forEach(function (b, i) {
            b.classList.toggle("active", tabsDef[i].key === current);
          });
          Object.keys(panels).forEach(function (k) {
            if (k === current) panels[k].removeAttribute("hidden");
            else panels[k].setAttribute("hidden", "hidden");
          });
        } },
      });
    }));
    root.appendChild(tabBar);
    root.appendChild(panels.band);
    root.appendChild(panels.mil);
    root.appendChild(panels.flare);
  }

  render();
})();
