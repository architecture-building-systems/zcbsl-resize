/* Control panel and rendering. No physics lives here: every number on the page
   comes back from POST /api/compute. */
(function () {
  "use strict";

  var schema = null;
  var state = {};
  var latest = null;
  var pending = null;
  var inFlight = false;

  function el(id) { return document.getElementById(id); }
  function fmt(n, d) {
    if (n === null || n === undefined || !isFinite(n)) return "–";
    return Number(n).toFixed(d === undefined ? 1 : d);
  }
  function kW(w) { var v = w / 1000; return fmt(v, Math.abs(v) < 10 ? 2 : 1); }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  var infoSeq = 0;
  function infoIcon(tooltip) {
    if (!tooltip) return "";
    var id = "tip-src-" + (++infoSeq);
    return ' <button type="button" class="info-icon" aria-label="What this means"' +
      ' aria-expanded="false" aria-describedby="' + id + '">' +
      '<span aria-hidden="true">i</span>' +
      '<span class="info-tooltip" id="' + id + '" role="tooltip">' + tooltip + "</span></button>";
  }

  // ------------------------------------------------------------- info tooltip
  // One floating bubble parented to <body>. The cards set overflow:hidden and
  // every section is replaced wholesale on each compute, so neither the
  // placement nor the dismissal of these can be left to CSS :hover inside a card.

  var TIP_GAP = 8;
  var tipLayer = null;
  var tipIcon = null;
  var tipPinned = false;

  function closestIcon(node) {
    return node && node.closest ? node.closest(".info-icon") : null;
  }

  function hideTip() {
    tipPinned = false;
    if (tipIcon) {
      tipIcon.setAttribute("aria-expanded", "false");
      tipIcon = null;
    }
    if (tipLayer) tipLayer.classList.remove("is-visible");
  }

  function positionTip() {
    if (!tipIcon || !tipIcon.isConnected) { hideTip(); return; }
    var r = tipIcon.getBoundingClientRect();
    var w = tipLayer.offsetWidth, h = tipLayer.offsetHeight;
    var below = r.top - h - TIP_GAP < TIP_GAP;
    var top = below ? r.bottom + TIP_GAP : r.top - h - TIP_GAP;
    var left = r.left + r.width / 2 - w / 2;
    left = Math.max(TIP_GAP, Math.min(left, window.innerWidth - w - TIP_GAP));
    var arrow = Math.min(Math.max(r.left + r.width / 2 - left, 12), Math.max(w - 12, 12));
    tipLayer.classList.toggle("below", below);
    tipLayer.style.top = Math.round(top) + "px";
    tipLayer.style.left = Math.round(left) + "px";
    tipLayer.style.setProperty("--tip-arrow", Math.round(arrow) + "px");
  }

  function showTip(icon) {
    if (!tipLayer || !icon || !icon.isConnected) return false;
    var source = icon.querySelector(".info-tooltip");
    var text = source ? source.textContent : "";
    if (!text) return false;
    if (tipIcon && tipIcon !== icon) tipIcon.setAttribute("aria-expanded", "false");
    tipIcon = icon;
    tipLayer.textContent = text;
    tipLayer.classList.add("is-visible");
    positionTip();
    return true;
  }

  function wireTooltips() {
    tipLayer = el("tip-layer");
    if (!tipLayer) return;

    document.addEventListener("pointerover", function (event) {
      if (tipPinned) return;
      var icon = closestIcon(event.target);
      if (icon) showTip(icon);
    });

    document.addEventListener("pointerout", function (event) {
      if (tipPinned) return;
      var icon = closestIcon(event.target);
      if (icon && icon === tipIcon && !icon.contains(event.relatedTarget)) hideTip();
    });

    document.addEventListener("click", function (event) {
      var icon = closestIcon(event.target);
      if (!icon) return;
      if (tipPinned && icon === tipIcon) { hideTip(); return; }
      if (!showTip(icon)) return;
      tipPinned = true;
      icon.setAttribute("aria-expanded", "true");
    });

    // Tapping or clicking anywhere else always lets go, including on touch,
    // where there is no pointerout to rely on.
    document.addEventListener("pointerdown", function (event) {
      if (!closestIcon(event.target)) hideTip();
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && tipIcon) hideTip();
    });

    document.addEventListener("focusin", function (event) {
      var icon = closestIcon(event.target);
      if (!icon) { if (!tipPinned) hideTip(); return; }
      // Only keyboard focus shows it; a mouse click is handled as a pin above.
      if (icon.matches(":focus-visible")) showTip(icon);
    });

    document.addEventListener("focusout", function (event) {
      if (tipPinned) return;
      var icon = closestIcon(event.target);
      if (icon && icon === tipIcon) hideTip();
    });

    // Fixed coordinates go stale the moment either of these fires.
    window.addEventListener("scroll", hideTip, true);
    window.addEventListener("resize", hideTip);
  }

  // ---------------------------------------------------------------- controls

  function fieldHtml(p) {
    var valueId = "val-" + p.key;
    if (p.kind === "toggle") {
      return '<div class="field field-toggle" data-key="' + p.key + '">' +
        '<label class="toggle-row"><input type="checkbox" id="in-' + p.key + '"' + (p.default >= 0.5 ? " checked" : "") + ">" +
        '<span class="field-label">' + esc(p.label) + "</span>" +
        '<span class="field-value" id="' + valueId + '"></span></label>' +
        (p.hint ? '<div class="field-hint">' + esc(p.hint) + "</div>" : "") +
        "</div>";
    }
    return '<div class="field" data-key="' + p.key + '">' +
      '<div class="field-row"><span class="field-label">' + esc(p.label) + "</span>" +
      '<span class="field-value" id="' + valueId + '"></span></div>' +
      '<input type="range" id="in-' + p.key + '" min="' + p.min + '" max="' + p.max +
      '" step="' + p.step + '" value="' + p.default + '">' +
      (p.hint ? '<div class="field-hint">' + esc(p.hint) + "</div>" : "") +
      "</div>";
  }

  function shellPresetHtml() {
    var options = Object.keys(schema.shell_presets || {}).map(function (key) {
      var m = schema.shell_presets[key];
      return '<option value="' + key + '">' + esc(m.label) + " \u2014 " + m.capacity + " kJ/m\u00b2K</option>";
    }).join("");
    if (!options) return "";
    return '<div class="field">' +
      '<div class="field-row"><span class="field-label">Shell lining preset</span></div>' +
      '<select id="shell-preset"><option value="">Custom\u2026</option>' + options + "</select>" +
      '<div class="field-hint" id="shell-note">All of these are thermally thin, so the whole layer participates.</div>' +
      "</div>";
  }

  function presetHtml() {
    var options = Object.keys(schema.presets).map(function (key) {
      return '<option value="' + key + '">' + esc(schema.presets[key].label) + "</option>";
    }).join("");
    return '<div class="field">' +
      '<div class="field-row"><span class="field-label">Material preset</span></div>' +
      '<select id="mass-preset"><option value="">Custom…</option>' + options + "</select>" +
      '<div class="field-hint" id="preset-note">Sets ρc and conductivity together. Thickness and area stay yours.</div>' +
      "</div>";
  }

  function buildControls() {
    var bySection = {};
    schema.params.forEach(function (p) {
      (bySection[p.section] = bySection[p.section] || []).push(p);
    });

    var html = schema.sections.map(function (section, index) {
      var params = bySection[section.key] || [];
      var body = (section.blurb ? '<p class="pill-blurb">' + esc(section.blurb) + "</p>" : "") +
        (section.key === "mass" ? shellPresetHtml() + presetHtml() : "") +
        params.map(fieldHtml).join("");
      return '<details class="pill" data-section="' + section.key + '"' + (index === 0 ? " open" : "") + ">" +
        '<summary><span class="pill-title">' + esc(section.title) + "</span>" +
        '<span class="pill-summary-mark">' + (index === 0 ? "−" : "+") + "</span></summary>" +
        '<div class="pill-body">' + body + "</div></details>";
    }).join("");

    el("pill-sections").innerHTML = html;
    el("param-count").textContent = schema.params.length + " inputs";

    schema.params.forEach(function (p) {
      var node = el("in-" + p.key);
      node.addEventListener(p.kind === "toggle" ? "change" : "input", function () {
        state[p.key] = p.kind === "toggle" ? (node.checked ? 1 : 0) : parseFloat(node.value);
        if (p.section === "mass") syncPresetSelect();
        syncLabel(p);
        requestCompute();
      });
    });

    document.querySelectorAll(".pill").forEach(function (pill) {
      pill.addEventListener("toggle", function () {
        pill.querySelector(".pill-summary-mark").textContent = pill.open ? "−" : "+";
      });
    });

    var shell = el("shell-preset");
    if (shell) {
      shell.addEventListener("change", function () {
        var chosen = (schema.shell_presets || {})[shell.value];
        if (!chosen) return;
        setValue("base_shell_capacity", chosen.capacity);
        el("shell-note").textContent = chosen.note;
        requestCompute();
      });
    }

    var preset = el("mass-preset");
    preset.addEventListener("change", function () {
      var chosen = schema.presets[preset.value];
      if (!chosen) return;
      setValue("added_mass_rho_c", chosen.rho_c);
      setValue("added_mass_k", chosen.k);
      el("preset-note").textContent = chosen.note;
      requestCompute();
    });
  }

  function syncLabel(p) {
    var node = el("val-" + p.key);
    if (!node) return;
    if (p.kind === "toggle") { node.textContent = state[p.key] >= 0.5 ? "On" : "Off"; return; }
    var unit = p.unit ? " " + p.unit : "";
    node.textContent = fmt(state[p.key], p.decimals) + unit;
  }

  function renderAddedMassReadout(r) {
    // added_mass_coverage is the settable input (% of interior surface); the
    // room-specific area it actually works out to only exists once the
    // server has computed it, so this is filled in after render() rather
    // than by the generic per-field slider label.
    var node = el("val-added_mass_coverage");
    if (!node) return;
    node.textContent = fmt(state.added_mass_coverage, 0) + " % \u2192 " + fmt(r.added_mass_area, 1) + " m\u00b2";
  }

  function syncAllLabels() { schema.params.forEach(syncLabel); }

  function setValue(key, value) {
    var p = schema.params.find(function (q) { return q.key === key; });
    if (!p) return;
    var clamped = Math.min(Math.max(value, p.min), p.max);
    state[key] = clamped;
    var node = el("in-" + key);
    if (node) {
      if (p.kind === "toggle") node.checked = clamped >= 0.5;
      else node.value = clamped;
    }
    syncLabel(p);
  }

  function syncPresetSelect() {
    var preset = el("mass-preset");
    if (!preset) return;
    var match = Object.keys(schema.presets).find(function (key) {
      var m = schema.presets[key];
      return Math.abs(m.rho_c - state.added_mass_rho_c) < 1 && Math.abs(m.k - state.added_mass_k) < 0.01;
    });
    preset.value = match || "";
  }

  // ---------------------------------------------------------------- transport

  function requestCompute() {
    pending = Object.assign({}, state);
    if (inFlight) return;
    flush();
  }

  function flush() {
    if (!pending) return;
    var payload = pending;
    pending = null;
    inFlight = true;
    fetch("/api/compute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params: payload })
    })
      .then(function (res) {
        if (!res.ok) throw new Error("server returned " + res.status);
        return res.json();
      })
      .then(function (data) {
        latest = data;
        setStatus(data.problems && data.problems.length ? data.problems.join(" · ") : "", !!(data.problems && data.problems.length));
        render(data);
      })
      .catch(function (err) { setStatus("Compute failed: " + err.message, true); })
      .finally(function () { inFlight = false; flush(); });
  }

  function setStatus(text, isError) {
    var node = el("status-line");
    node.textContent = text;
    node.classList.toggle("error", !!isError);
  }

  // ---------------------------------------------------------------- rendering

  function statTile(kind, label, value, unit, sub, tooltip) {
    return '<div class="stat-tile ' + kind + '">' +
      '<div class="stat-label">' + label + infoIcon(tooltip) + "</div>" +
      '<div class="stat-value mono">' + value + "<small>" + unit + "</small></div>" +
      '<div class="stat-sub">' + sub + "</div></div>";
  }

  function modeWord(byRamp) { return byRamp ? "ramp" : "operating"; }

  function sourceWord(r) { return r.tank_on ? "tank" : "outdoor air"; }

  function renderStats(r) {
    var html = "";
    html += statTile("heat", "Heating design capacity", kW(r.heating_design), "kW",
      "set by " + modeWord(r.heating_set_by_ramp) + " · operating " + kW(r.heating_operating) + " / ramp " + kW(r.heating_ramp),
      "The larger of the two modes, never their sum. Operating is the steady hold during an experiment; ramp is charging the mass plus the hold at the far setpoint with the Sun off and nobody inside. Both include the margin. Radiant panels and the air coil share it; see the table below.");
    html += statTile("cool", "Cooling design capacity", kW(r.cooling_design), "kW",
      "set by " + modeWord(r.cooling_set_by_ramp) + " · operating " + kW(r.cooling_operating) + " / ramp " + kW(r.cooling_ramp),
      "Same as heating, at the hottest boundary and including solar gain through the glazing. The Artificial Sun counts in the operating mode only.");
    var flowSetBy = r.flow_set_by_ventilation ? "ventilation minimum" : modeWord(r.flow_set_by_ramp);
    html += statTile("neutral", "Design supply airflow", fmt(r.design_flow_ls, 0), "L/s",
      "set by " + flowSetBy + " · operating " + fmt(r.flow_operating_ls, 0) + " / ramp " + fmt(r.flow_ramp_ls, 0),
      "Air-side load (what the radiant panels cannot carry) over your max supply ΔT, for each mode, floored by the ventilation minimum. The larger mode sets the fan.");
    html += statTile("neutral", "Dehumidification", kW(r.latent_design), "kW",
      "dew point at setpoint " + fmt(r.dew_point_c, 1) + " °C",
      "Ventilation moisture plus occupant moisture, from ASHRAE psychrometrics on both air states. Sized at the cold setpoint, which is the harder case. Not included in the cooling capacity above.");
    html += statTile(r.film_ok ? "neutral" : "alert", "Air-to-surface ΔT needed", fmt(r.required_air_surface_dt, 1), "K",
      r.film_ok ? "within your allowance" : "exceeds your allowance — ramp unreachable",
      "To charge the mass this fast, the room air has to run this far from the surfaces. It is set by the surface film coefficient and the interior area, and no amount of coil capacity changes it. The hung radiant panels charge no mass directly, so they do not relax it.");
    html += statTile("heat", "Heating COP", fmt(r.cop_heating, 1), "",
      r.free_heating ? "no compressor needed — direct from the " + sourceWord(r)
                     : "lift " + fmt(r.lift_heating, 0) + " K from " + sourceWord(r) + " · " + kW(r.electric_heating) + " kW electric",
      "Carnot across the lift from the source (hot tank, or winter outdoor air with the tanks off) up to the supply temperature, times the efficiency factor. An estimate, not a manufacturer curve — at very small lifts a real machine will not reach this.");
    html += statTile("cool", "Cooling COP", fmt(r.cop_cooling, 1), "",
      r.free_cooling ? "no compressor needed — direct to the " + sourceWord(r)
                     : "lift " + fmt(r.lift_cooling, 0) + " K to " + sourceWord(r) + " · " + kW(r.electric_cooling) + " kW electric",
      "Same calculation for the cooling duty, lifting from the supply temperature up to the sink: the cold tank, or summer outdoor air with the tanks off.");
    html += statTile("neutral", "Fastest reachable ramp", fmt(r.fastest_ramp_minutes, 0), "min",
      "at " + fmt(state.max_air_surface_dt, 0) + " K air-to-surface allowance",
      "The shortest ramp the surface film physically permits, solved self-consistently: a longer ramp lets heat reach deeper into the mass, so the answer has to be the ramp time that equals its own minimum. Asking for less than this cannot work regardless of equipment.");
    el("stat-grid").innerHTML = html;
  }

  // ------------------------------------------------------- mode breakdown table
  // Operating and ramp side by side, and the design value that is the larger
  // of the two. The design column is never a sum: the room does one or the
  // other.

  function modeCell(value, isGov, fmtFn, sub) {
    return '<td class="mono num' + (isGov ? " gov" : "") + '">' + fmtFn(value) +
      (sub ? '<div class="cell-sub">' + sub + "</div>" : "") + "</td>";
  }

  function modeRow(label, op, ramp, design, fmtFn, opts) {
    opts = opts || {};
    var tol = 1e-6 * Math.max(Math.abs(op), Math.abs(ramp), 1);
    var rampGov = ramp > op + tol, opGov = op > ramp + tol;
    if (opts.floorGov) { rampGov = false; opGov = false; }
    return '<tr class="' + (opts.cls || "") + '"><th scope="row">' + label + "</th>" +
      modeCell(op, opGov, fmtFn) +
      modeCell(ramp, rampGov, fmtFn, opts.rampSub) +
      '<td class="mono num design">' + fmtFn(design) + (opts.tag ? '<span class="mode-tag">' + opts.tag + "</span>" : "") + "</td></tr>";
  }

  function crossoverText(duty, minutes, r) {
    if (minutes === null || minutes === undefined) {
      return "the ramp sets the " + duty + " size at every ramp time up to 480 min";
    }
    if (minutes <= 1) return "the operating mode sets the " + duty + " size at any ramp time";
    var now = r.ramp_minutes >= minutes ? " (you are past it)" : "";
    return "the operating mode takes over the " + duty + " size from a <b>" + fmt(minutes, 0) + " min</b> ramp" + now;
  }

  function renderModeTable(r) {
    var m = 1 + r.margin_frac;
    var kWf = function (w) { return kW(w); };
    var ls = function (v) { return fmt(v * 1000, 0); };
    var src = r.tank_on ? "tanks" : "outdoor air";
    var html = "";
    html += '<div class="chart-title">Operating vs. ramp, for this scenario' +
      infoIcon("Operating: holding an experiment at the extreme boundary, with its internal gains. Ramp: moving the full setpoint range in the target time, at the same boundary, with the Sun off and nobody inside. The room is always in one mode or the other, so the design value is the larger of the two, never the sum. Highlighted cells are the mode that sets each design value. Every capacity includes the margin.") +
      "</div>";
    html += '<div class="table-scroll"><table class="mode-table"><thead><tr><th></th>' +
      '<th scope="col" class="num">Operating<div class="cell-sub">holding</div></th>' +
      '<th scope="col" class="num">Ramp<div class="cell-sub">' + fmt(r.ramp_minutes, 0) + " min, Sun off</div></th>" +
      '<th scope="col" class="num">Design<div class="cell-sub">larger of the two</div></th></tr></thead><tbody>';

    html += '<tr class="group heat"><th colspan="4">Heating, kW</th></tr>';
    html += modeRow("Room total", r.heating_operating, r.heating_ramp, r.heating_design, kWf, {
      rampSub: "mass " + kW(r.power_mass * m) + " + hold " + kW(r.heating_hold_ramp * m),
      tag: modeWord(r.heating_set_by_ramp)
    });
    html += modeRow(" radiant panels", r.radiant_heating_operating, r.radiant_heating_ramp, r.radiant_heating_design, kWf, { cls: "sub" });
    html += modeRow(" air coil", r.air_heating_operating, r.air_heating_ramp, r.air_heating_design, kWf, { cls: "sub" });

    html += '<tr class="group cool"><th colspan="4">Cooling, kW</th></tr>';
    html += modeRow("Room total", r.cooling_operating, r.cooling_ramp, r.cooling_design, kWf, {
      rampSub: "mass " + kW(r.power_mass * m) + " + hold " + kW(r.cooling_hold_ramp * m),
      tag: modeWord(r.cooling_set_by_ramp)
    });
    html += modeRow(" radiant panels", r.radiant_cooling_operating, r.radiant_cooling_ramp, r.radiant_cooling_design, kWf, { cls: "sub" });
    html += modeRow(" air coil", r.air_cooling_operating, r.air_cooling_ramp, r.air_cooling_design, kWf, { cls: "sub" });

    html += '<tr class="group"><th colspan="4">Supply airflow, L/s</th></tr>';
    var flowTag = r.flow_set_by_ventilation ? "ventilation" : modeWord(r.flow_set_by_ramp);
    html += modeRow("Air coil, either duty", r.flow_operating_ls / 1000, r.flow_ramp_ls / 1000, r.design_flow_m3s, ls, {
      tag: flowTag, floorGov: r.flow_set_by_ventilation
    });
    html += modeRow(" ventilation minimum", r.flow_from_ach, r.flow_from_ach, r.flow_from_ach, ls, { cls: "sub", floorGov: true });

    html += '<tr class="group"><th colspan="4">Heat pump, electric kW</th></tr>';
    html += modeRow("Heating", r.electric_heating_operating, r.electric_heating_ramp, r.electric_heating, kWf, { cls: "sub" });
    html += modeRow("Cooling", r.electric_cooling_operating, r.electric_cooling_ramp, r.electric_cooling, kWf, { cls: "sub" });

    html += '<tr class="group"><th colspan="4">Source side (' + src + "), kW</th></tr>";
    html += modeRow("Heating, extracted", r.source_extract_heating_operating, r.source_extract_heating_ramp, r.source_extract_heating, kWf, { cls: "sub" });
    html += modeRow("Cooling, rejected", r.source_reject_cooling_operating, r.source_reject_cooling_ramp, r.source_reject_cooling, kWf, { cls: "sub" });

    html += "</tbody></table></div>";
    html += '<div class="chart-legend"><span>Includes ' + fmt(state.margin_pct, 0) + "% margin. Radiant panels carry up to " +
      kW(r.radiant_capacity_heat) + " kW heating / " + kW(r.radiant_capacity_cool) + " kW cooling in either mode; the air coil carries the rest.</span>" +
      "<span>Across ramp times, " + crossoverText("heating", r.heating_crossover_minutes, r) + "; " +
      crossoverText("cooling", r.cooling_crossover_minutes, r) + ".</span></div>";
    el("mode-card").innerHTML = html;
  }

  function renderInsights(data) {
    // Only the two notes the table cannot carry. Everything else that used to
    // live here is in the operating-vs-ramp table or the checks below.
    var r = data.results;
    var html = "";

    if (!r.film_ok) {
      html += '<div class="insight crit span-2">To charge the mass in ' + fmt(r.ramp_minutes, 0) +
        " minutes, the air would have to sit <b>" + fmt(r.required_air_surface_dt, 0) +
        " K</b> away from the surfaces, against your <b>" + fmt(state.max_air_surface_dt, 0) +
        " K</b> allowance. This ramp is not reachable by adding capacity. The shortest ramp the film permits here is <b>" +
        fmt(r.fastest_ramp_minutes, 0) + " minutes</b>; reducing mass or relaxing the setpoint range are the other levers." +
        infoIcon("Mass-charging power is capped at h &times; interior area &times; the air-to-surface &Delta;T you allow. With h &asymp; 8 W/m&sup2;K this ceiling binds long before the coil does.") +
        "</div>";
    }

    if (state.added_mass_coverage > 0) {
      var overstate = data.lumped.power_mass / (r.power_mass || 1);
      html += '<div class="insight accent span-2">Heat reaches <b>' + fmt(r.added_penetration_mm, 0) +
        " mm</b> into the added mass during a " + fmt(r.ramp_minutes, 0) + "-minute ramp, so <b>" +
        fmt(100 * r.added_participating_fraction, 0) + "%</b> of the " + fmt(1000 * state.added_mass_thickness, 0) +
        " mm layer takes part." +
        (overstate > 1.05
          ? " Crediting the whole layer would put the mass-charging power at " + kW(data.lumped.power_mass) +
            " kW instead of " + kW(r.power_mass) + " kW, overstating it by " + fmt(overstate, 1) + "×."
          : " The whole layer is charged within this ramp, so the full-layer shortcut would give the same answer here.") +
        infoIcon("Diffusion depth for a linear surface ramp is 4/(3&radic;&pi;)&middot;&radic;(&alpha;t), with &alpha; = k/&rho;c. Deep mass cannot be charged in a short ramp at any power.") +
        "</div>";
    }

    el("insight-row").innerHTML = html;
    el("insight-row").hidden = !html;
  }

  function renderSensitivity(data) {
    var r = data.results, sweep = data.sweep;
    var w = 520, h = 220, padL = 46, padR = 12, padT = 12, padB = 28;
    var plotW = w - padL - padR, plotH = h - padT - padB;

    var maxT = sweep.ramp_minutes[sweep.ramp_minutes.length - 1];
    // Scale to the reachable part of the sweep. Below the fastest ramp the
    // requirement runs off to hundreds of kW, which is unreachable anyway and
    // would flatten everything that matters; those lines are clipped instead.
    var maxY = 0, reachFrom = Math.min(sweep.fastest_ramp_minutes || 0, sweep.ramp_minutes[sweep.ramp_minutes.length - 1]);
    ["heating_design", "cooling_design", "heating_ramp", "cooling_ramp", "heating_operating", "cooling_operating"].forEach(function (key) {
      sweep[key].forEach(function (v, i) {
        if (sweep.ramp_minutes[i] >= reachFrom) maxY = Math.max(maxY, v / 1000);
      });
    });
    maxY = Math.max(maxY, r.heating_design / 1000, r.cooling_design / 1000);
    maxY = maxY * 1.12;
    if (!isFinite(maxY) || maxY <= 0) maxY = 1;

    function x(t) { return padL + (t / maxT) * plotW; }
    function y(v) { return padT + plotH - (v / maxY) * plotH; }

    function pathFor(key) {
      return sweep.ramp_minutes.map(function (t, i) {
        return (i === 0 ? "M" : "L") + x(t).toFixed(1) + "," + y(sweep[key][i] / 1000).toFixed(1);
      }).join(" ");
    }

    var grid = "";
    for (var i = 0; i <= 4; i++) {
      var val = (maxY / 4) * i, yy = y(val);
      grid += '<line x1="' + padL + '" y1="' + yy.toFixed(1) + '" x2="' + (w - padR) + '" y2="' + yy.toFixed(1) + '" class="axis-line"/>';
      grid += '<text x="' + (padL - 8) + '" y="' + (yy + 3).toFixed(1) + '" text-anchor="end" font-size="9">' + fmt(val, 0) + "</text>";
    }
    var xTicks = "";
    [0, 60, 120, 180, 240, 300, 360, 420, 480].filter(function (t) { return t <= maxT; }).forEach(function (t) {
      xTicks += '<text x="' + x(t).toFixed(1) + '" y="' + (h - 8) + '" text-anchor="middle" font-size="9">' + t + "</text>";
    });

    var unreachable = "";
    var limit = Math.min(sweep.fastest_ramp_minutes, maxT);
    if (limit > sweep.ramp_minutes[0]) {
      unreachable = '<rect x="' + padL + '" y="' + padT + '" width="' + Math.max(x(limit) - padL, 0).toFixed(1) +
        '" height="' + plotH + '" fill="var(--crit)" opacity="0.13"/>' +
        '<line x1="' + x(limit).toFixed(1) + '" y1="' + padT + '" x2="' + x(limit).toFixed(1) + '" y2="' + (padT + plotH) +
        '" stroke="var(--crit)" stroke-width="1.5" stroke-dasharray="4,3"/>';
    }

    var curX = x(Math.min(Math.max(r.ramp_minutes, sweep.ramp_minutes[0]), maxT));

    var clipId = "plot-clip";
    var svg = '<svg viewBox="0 0 ' + w + " " + h + '" width="100%" role="img" aria-label="Operating and ramp capacity versus ramp time">' +
      '<defs><clipPath id="' + clipId + '"><rect x="' + padL + '" y="' + padT + '" width="' + plotW + '" height="' + plotH + '"/></clipPath></defs>' +
      grid + unreachable +
      '<line x1="' + padL + '" y1="' + padT + '" x2="' + padL + '" y2="' + (padT + plotH) + '" class="axis-line"/>' +
      '<line x1="' + padL + '" y1="' + (padT + plotH) + '" x2="' + (w - padR) + '" y2="' + (padT + plotH) + '" class="axis-line"/>' +
      xTicks +
      '<g clip-path="url(#' + clipId + ')">' +
      '<path d="' + pathFor("heating_design") + '" fill="none" stroke="var(--heat)" stroke-width="7" opacity="0.16" stroke-linecap="round" stroke-linejoin="round"/>' +
      '<path d="' + pathFor("cooling_design") + '" fill="none" stroke="var(--cool)" stroke-width="7" opacity="0.16" stroke-linecap="round" stroke-linejoin="round"/>' +
      '<path d="' + pathFor("heating_operating") + '" fill="none" stroke="var(--heat)" stroke-width="1.5" stroke-dasharray="5,4"/>' +
      '<path d="' + pathFor("cooling_operating") + '" fill="none" stroke="var(--cool)" stroke-width="1.5" stroke-dasharray="5,4"/>' +
      '<path d="' + pathFor("heating_ramp") + '" fill="none" stroke="var(--heat)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
      '<path d="' + pathFor("cooling_ramp") + '" fill="none" stroke="var(--cool)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
      "</g>" +
      '<line x1="' + curX.toFixed(1) + '" y1="' + padT + '" x2="' + curX.toFixed(1) + '" y2="' + (padT + plotH) + '" stroke="var(--text)" stroke-width="1" opacity="0.35"/>' +
      '<circle cx="' + curX.toFixed(1) + '" cy="' + y(r.heating_design / 1000).toFixed(1) + '" r="4" fill="var(--heat)"/>' +
      '<circle cx="' + curX.toFixed(1) + '" cy="' + y(r.cooling_design / 1000).toFixed(1) + '" r="4" fill="var(--cool)"/>' +
      '<text x="' + (w - padR) + '" y="' + (padT + 10) + '" text-anchor="end" font-size="9">kW</text>' +
      '<text x="' + (padL + plotW / 2) + '" y="' + (h - 0) + '" text-anchor="middle" font-size="9">ramp time, min</text>' +
      "</svg>";
    el("sensitivity-chart").innerHTML = svg;
  }

  function renderBreakdown(r) {
    var w = 380, rowH = 26, gap = 8, groupGap = 18, padL = 124, padR = 64, padT = 8;
    var h = padT * 2 + rowH * 4 + gap * 2 + groupGap;
    var plotW = w - padL - padR;
    var mf = r.margin_frac;
    var maxTotal = Math.max(r.heating_design, r.cooling_design) || 1;
    var scale = plotW / maxTotal, gapPx = 2;

    function seg(x, y, width, fill, stroke) {
      return '<rect x="' + x.toFixed(1) + '" y="' + y + '" width="' + Math.max(width - gapPx, 0).toFixed(1) +
        '" height="' + rowH + '" rx="3" fill="' + fill + '"' + (stroke ? ' stroke="' + stroke + '"' : "") + "/>";
    }

    function bar(yPos, label, hold, mass, governs) {
      var marginAmt = (hold + mass) * mf;
      var wHold = hold * scale, wMass = mass * scale, wMarg = marginAmt * scale;
      var x0 = padL;
      var out = '<text x="' + (padL - 8) + '" y="' + (yPos + rowH / 2 + 4) + '" text-anchor="end" font-size="10"' +
        (governs ? ' font-weight="700"' : "") + ">" + label + "</text>";
      var g = '<g opacity="' + (governs ? 1 : 0.45) + '">';
      g += seg(x0, yPos, wHold, "var(--surface-2)", "var(--line)");
      g += seg(x0 + wHold, yPos, wMass, "color-mix(in srgb, var(--text) 55%, var(--surface))");
      g += seg(x0 + wHold + wMass, yPos, wMarg, "var(--accent)");
      g += "</g>";
      out += g;
      out += '<text x="' + (x0 + wHold + wMass + wMarg + 6).toFixed(1) + '" y="' + (yPos + rowH / 2 + 4) +
        '" font-size="10.5"' + (governs ? ' font-weight="700"' : "") + ' class="mono">' + kW(hold + mass + marginAmt) +
        (governs ? " ◀" : "") + "</text>";
      return out;
    }

    var y1 = padT, y2 = y1 + rowH + gap, y3 = y2 + rowH + groupGap, y4 = y3 + rowH + gap;
    var svg = '<svg viewBox="0 0 ' + w + " " + h + '" width="100%" role="img" aria-label="Operating and ramp capacity, by component">' +
      bar(y1, "Heating, operating", r.heating_hold, 0, !r.heating_set_by_ramp) +
      bar(y2, "Heating, ramp", r.heating_hold_ramp, r.power_mass, !!r.heating_set_by_ramp) +
      bar(y3, "Cooling, operating", r.cooling_hold, 0, !r.cooling_set_by_ramp) +
      bar(y4, "Cooling, ramp", r.cooling_hold_ramp, r.power_mass, !!r.cooling_set_by_ramp) +
      "</svg>";
    el("breakdown-chart").innerHTML = svg;
  }

  function checkCard(label, req, limit, ok, unit, note, tooltip, badges) {
    badges = badges || { good: ["good", "within limit"], bad: ["crit", "exceeds limit"] };
    var badge = ok ? badges.good : badges.bad;
    var scaleMax = Math.max(limit * 1.4, req * 1.08, 1);
    var fillPct = Math.min((req / scaleMax) * 100, 100);
    var limitPct = Math.min((limit / scaleMax) * 100, 100);
    return '<div class="check-card">' +
      '<div class="check-head"><h3>' + label + infoIcon(tooltip) + "</h3>" +
      '<span class="badge ' + badge[0] + '">' + badge[1] + "</span></div>" +
      '<div class="flux-bar-track"><div class="flux-bar-fill" style="width:' + fillPct + "%;background:var(--" + badge[0] + ')"></div>' +
      '<div class="flux-limit-mark" style="left:' + limitPct + '%"></div></div>' +
      '<div class="check-nums"><span>' + fmt(req, 0) + " " + unit + " required</span><span>limit " + fmt(limit, 0) + " " + unit + "</span></div>" +
      (note ? '<div class="check-note">' + note + "</div>" : "") +
      "</div>";
  }

  function renderEnvelope(r) {
    var rows = (schema.surfaces || []).map(function (s2) {
      var area = r["area_" + s2.key], ua = r["conductance_" + s2.key];
      var exposure = state[s2.key + "_exposure"];
      var glazed = r["glazed_area_" + s2.key];
      var share = r.envelope_conductance > 0 ? (ua / r.envelope_conductance) * 100 : 0;
      return '<tr>' +
        '<td style="padding:0.2rem 0.5rem 0.2rem 0;font-weight:600">' + esc(s2.label) + "</td>" +
        '<td class="mono" style="text-align:right;padding:0.2rem 0.5rem">' + fmt(area, 1) + "</td>" +
        '<td class="mono" style="text-align:right;padding:0.2rem 0.5rem">' + fmt(glazed, 1) + "</td>" +
        '<td class="mono" style="text-align:right;padding:0.2rem 0.5rem">' + fmt(exposure, 2) + "</td>" +
        '<td class="mono" style="text-align:right;padding:0.2rem 0.5rem">' + fmt(ua, 1) + "</td>" +
        '<td style="padding:0.2rem 0 0.2rem 0.5rem;width:70px">' +
          '<div style="height:6px;border-radius:3px;background:var(--surface-2);overflow:hidden">' +
          '<div style="height:100%;width:' + Math.min(share, 100).toFixed(0) + '%;background:var(--accent)"></div></div></td>' +
        "</tr>";
    }).join("");
    el("envelope-card").innerHTML =
      '<div class="chart-title">Envelope by surface' +
      infoIcon("Areas come from the geometry. Exposure is 1 for a surface facing outdoors and 0 for one facing the lab. The bar is each surface\u2019s share of the total conductance.") +
      "</div>" +
      '<table style="width:100%;border-collapse:collapse;font-size:0.76rem">' +
      '<thead><tr style="color:var(--muted);font-size:0.68rem;text-transform:uppercase;letter-spacing:0.03em">' +
      '<th style="text-align:left;padding-bottom:0.3rem">Surface</th>' +
      '<th style="text-align:right;padding-bottom:0.3rem">m\u00b2</th>' +
      '<th style="text-align:right;padding-bottom:0.3rem">glazed</th>' +
      '<th style="text-align:right;padding-bottom:0.3rem">exp.</th>' +
      '<th style="text-align:right;padding-bottom:0.3rem">W/K</th>' +
      '<th style="padding-bottom:0.3rem"></th></tr></thead><tbody>' + rows + "</tbody></table>" +
      '<div class="chart-legend"><span>Total ' + fmt(r.envelope_conductance, 1) +
      " W/K \u00b7 interior surface " + fmt(r.interior_area, 0) + " m\u00b2</span></div>";
  }

  function renderChecks(r) {
    var html = "";
    var panels = fmt(r.radiant_area_actual, 1) + " m\u00b2 of panels";
    // Panels running full is the design intent now, not a failure: the air coil
    // takes the rest. So this is a warning at most, never red.
    var panelBadges = { good: ["good", "panels suffice"], bad: ["warn", "panels full"] };
    html += checkCard("Radiant panels alone: heating hold", r.radiant_flux_heat, state.radiant_heat_limit, r.radiant_heat_ok, "W/m²",
      panels + " carry <b class=\"mono\">" + kW(r.radiant_heating_operating) + " kW</b> while holding and <b class=\"mono\">" +
      kW(r.radiant_heating_ramp) + " kW</b> while ramping; the air coil carries the rest.",
      "Could the panels hold the experiment on their own? Steady-state heating hold over the active radiant area, against the panel limit. Either way the panels run up to their limit in both modes and the air coil takes the remainder.", panelBadges);
    html += checkCard("Radiant panels alone: cooling hold", r.radiant_flux_cool, state.radiant_cool_limit, r.radiant_cool_ok, "W/m²",
      panels + " carry <b class=\"mono\">" + kW(r.radiant_cooling_operating) + " kW</b> while holding and <b class=\"mono\">" +
      kW(r.radiant_cooling_ramp) + " kW</b> while ramping. Surfaces must stay above the <b>" + fmt(r.dew_point_c, 1) + " °C</b> dew point at your target RH.",
      "Steady-state cooling hold over the active radiant area, against the condensation-limited W/m&sup2; limit. The panels run up to that limit in both modes.", panelBadges);
    html += checkCard("Mass charging vs. surface film", r.required_air_surface_dt, state.max_air_surface_dt, r.film_ok, "K",
      "At h = " + fmt(state.surface_film_h, 1) + " W/m²K over " + fmt(r.exchange_area, 0) +
      " m², the most that can enter the mass is <b class=\"mono\">" + kW(r.max_mass_power) +
      " kW</b>, giving a fastest ramp of <b>" + fmt(r.fastest_ramp_minutes, 0) + " min</b>.",
      "Mass charging is capped by convection and radiation from the air to the surfaces. This is independent of coil capacity and is usually the binding constraint.");
    var needed = state.setpoint_min - state.supply_dt;
    var sinkApproach = r.tank_on ? state.exchanger_approach : state.outdoor_coil_approach;
    var reachable = r.sink_temp_cooling + sinkApproach;
    html += '<div class="check-card">' +
      '<div class="check-head"><h3>Free cooling from ' + (r.tank_on ? "the cold tank" : "outdoor air") +
      infoIcon("Can the sink feed the coil directly, with no compressor? It needs to be colder than the supply temperature by at least its approach. With the tanks off the sink is the summer design air, so this is never available at design conditions.") +
      '</h3><span class="badge ' + (r.free_cooling ? "good" : "warn") + '">' +
      (r.free_cooling ? "available" : "chiller needed") + "</span></div>" +
      '<div class="check-nums"><span>coil needs ' + fmt(needed, 1) + " \u00b0C</span><span>tank can reach " +
      fmt(reachable, 1) + " \u00b0C</span></div>" +
      '<div class="check-note">Cooling lift <b class="mono">' + fmt(r.lift_cooling, 0) +
      " K</b>, heating lift <b class=\"mono\">" + fmt(r.lift_heating, 0) +
      " K</b>. " + (r.tank_on ? "The machine exchanges with the tanks." : "Tanks off: the machine works against outdoor air, and the tanks see nothing.") + "</div></div>";
    el("check-grid").innerHTML = html;
  }

  function render(data) {
    hideTip();
    renderStats(data.results);
    renderModeTable(data.results);
    renderInsights(data);
    renderSensitivity(data);
    renderBreakdown(data.results);
    renderEnvelope(data.results);
    renderChecks(data.results);
    renderAddedMassReadout(data.results);
  }

  // ---------------------------------------------------------------- scenarios

  function summaryText() {
    if (!latest) return "";
    var r = latest.results;
    return [
      "Chamber ramp & hold sizing",
      "Room: " + fmt(state.width, 2) + " w x " + fmt(state.depth, 2) + " d x " + fmt(state.height, 2) +
        " m; interior " + fmt(r.interior_area, 0) + " m2, glazed " + fmt(r.glazed_area, 1) + " m2",
      "Envelope: " + fmt(r.envelope_conductance, 1) + " W/K over " +
        (schema.surfaces || []).map(function (s2) {
          return s2.key + " " + fmt(r["conductance_" + s2.key], 1);
        }).join(", "),
      "Setpoints " + fmt(r.setpoint_min, 1) + " to " + fmt(r.setpoint_max, 1) + " C, ramp " + fmt(r.ramp_minutes, 0) + " min",
      "Design = larger of operating and ramp, never the sum; all incl. " + fmt(state.margin_pct, 0) + "% margin. Ramp runs with the Sun off and nobody inside.",
      "Heating: " + kW(r.heating_design) + " kW, set by " + modeWord(r.heating_set_by_ramp) +
        " (operating " + kW(r.heating_operating) + ", ramp " + kW(r.heating_ramp) + " = mass " + kW(r.power_mass * (1 + r.margin_frac)) + " + hold " + kW(r.heating_hold_ramp * (1 + r.margin_frac)) + ")",
      "  radiant " + kW(r.radiant_heating_design) + " kW + air coil " + kW(r.air_heating_design) + " kW",
      "Cooling: " + kW(r.cooling_design) + " kW, set by " + modeWord(r.cooling_set_by_ramp) +
        " (operating " + kW(r.cooling_operating) + ", ramp " + kW(r.cooling_ramp) + " = mass " + kW(r.power_mass * (1 + r.margin_frac)) + " + hold " + kW(r.cooling_hold_ramp * (1 + r.margin_frac)) + ")",
      "  radiant " + kW(r.radiant_cooling_design) + " kW + air coil " + kW(r.air_cooling_design) + " kW",
      "Operating mode takes over past: heating " + (r.heating_crossover_minutes === null ? "never (<= 480 min)" : fmt(r.heating_crossover_minutes, 0) + " min") +
        ", cooling " + (r.cooling_crossover_minutes === null ? "never (<= 480 min)" : fmt(r.cooling_crossover_minutes, 0) + " min"),
      "Dehumidification: " + kW(r.latent_design) + " kW; dew point at setpoint " + fmt(r.dew_point_c, 1) + " C",
      "Supply airflow: " + fmt(r.design_flow_ls, 0) + " L/s (" + fmt(r.design_flow_m3h, 0) + " m3/h), set by " +
        (r.flow_set_by_ventilation ? "ventilation minimum" : modeWord(r.flow_set_by_ramp)) +
        " (operating " + fmt(r.flow_operating_ls, 0) + ", ramp " + fmt(r.flow_ramp_ls, 0) + " L/s)",
      "Air-to-surface dT needed: " + fmt(r.required_air_surface_dt, 1) + " K vs " + fmt(state.max_air_surface_dt, 0) + " K allowed -> " + (r.film_ok ? "REACHABLE" : "NOT REACHABLE"),
      "Fastest ramp the surface film permits: " + fmt(r.fastest_ramp_minutes, 0) + " min (self-consistent; "
        + fmt(r.min_feasible_ramp_minutes, 0) + " min is the figure conditional on the ramp asked for)",
      "Added mass participating: " + fmt(100 * r.added_participating_fraction, 0) + "% (" + fmt(r.added_penetration_mm, 0) + " mm of " + fmt(1000 * state.added_mass_thickness, 0) + " mm)",
      (r.tank_on
        ? "Dedicated heat pump (tanks at " + fmt(state.tank_temp_hot, 0) + " / " + fmt(state.tank_temp_cold, 0) + " C, unlimited source):"
        : "Dedicated heat pump (tanks OFF: outdoor air at " + fmt(state.boundary_temp_winter, 0) + " / " + fmt(state.boundary_temp_summer, 0) + " C, " + fmt(state.outdoor_coil_approach, 1) + " K coil approach):"),
      "  heating " + kW(r.hp_heating) + " kW thermal, lift " + fmt(r.lift_heating, 0) + " K, COP " + fmt(r.cop_heating, 1) + ", " + kW(r.electric_heating) + " kW electric (operating " + kW(r.electric_heating_operating) + ", ramp " + kW(r.electric_heating_ramp) + ")",
      "  cooling " + kW(r.hp_cooling) + " kW thermal, lift " + fmt(r.lift_cooling, 0) + " K, COP " + fmt(r.cop_cooling, 1) + ", " + kW(r.electric_cooling) + " kW electric (operating " + kW(r.electric_cooling_operating) + ", ramp " + kW(r.electric_cooling_ramp) + ")",
      "  free cooling from the " + sourceWord(r) + ": " + (r.free_cooling ? "AVAILABLE" : "not available, compressor needed"),
      "  " + sourceWord(r) + " sees " + kW(r.source_extract_heating) + " kW extracted (heating) / " + kW(r.source_reject_cooling) + " kW rejected (cooling)",
      "Radiant panels " + fmt(r.radiant_area_actual, 1) + " m2: up to " + kW(r.radiant_capacity_heat) + " kW heating / " + kW(r.radiant_capacity_cool) + " kW cooling in either mode",
      "  alone vs operating hold: heating " + fmt(r.radiant_flux_heat, 0) + " W/m2 (limit " + fmt(state.radiant_heat_limit, 0) + ") - " + (r.radiant_heat_ok ? "OK" : "EXCEEDS") +
        ", cooling " + fmt(r.radiant_flux_cool, 0) + " W/m2 (limit " + fmt(state.radiant_cool_limit, 0) + ") - " + (r.radiant_cool_ok ? "OK" : "EXCEEDS"),
      "First-pass sizing envelope, not a substitute for a full mechanical load calculation."
    ].join("\n");
  }

  function download(name, text) {
    var blob = new Blob([text], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function applyScenario(payload) {
    var loaded = payload.params || payload;
    var applied = 0, skipped = [];
    Object.keys(loaded).forEach(function (key) {
      if (schema.params.some(function (p) { return p.key === key; })) {
        setValue(key, Number(loaded[key])); applied++;
      } else { skipped.push(key); }
    });
    syncPresetSelect();
    requestCompute();
    setStatus("Loaded " + applied + " parameters" + (skipped.length ? "; ignored " + skipped.join(", ") : ""), skipped.length > 0);
  }

  function wireActions() {
    el("copy-summary").addEventListener("click", function () {
      var btn = el("copy-summary"), old = btn.textContent;
      function done(msg) { btn.textContent = msg; setTimeout(function () { btn.textContent = old; }, 1600); }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(summaryText()).then(function () { done("Copied"); }).catch(function () { done("Copy failed"); });
      } else { done("Clipboard unavailable"); }
    });

    el("btn-reset").addEventListener("click", function () {
      schema.params.forEach(function (p) { setValue(p.key, p.default); });
      syncPresetSelect();
      requestCompute();
      setStatus("Reset to defaults", false);
    });

    el("btn-save").addEventListener("click", function () {
      var stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
      download("chamber-scenario-" + stamp + ".json", JSON.stringify({
        format: 1,
        name: "",
        notes: "Saved from the chamber sizing tool",
        params: state
      }, null, 2) + "\n");
      setStatus("Scenario saved", false);
    });

    el("btn-load").addEventListener("click", function () { el("file-load").click(); });

    el("file-load").addEventListener("change", function (event) {
      var file = event.target.files && event.target.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function () {
        try {
          applyScenario(JSON.parse(reader.result));
        } catch (err) {
          setStatus("Could not read that file: " + err.message, true);
        }
      };
      reader.readAsText(file);
      event.target.value = "";
    });

    document.querySelectorAll("[data-default-scenario]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var path = btn.getAttribute("data-default-scenario");
        fetch(path)
          .then(function (res) {
            if (!res.ok) throw new Error(res.status + " " + res.statusText);
            return res.json();
          })
          .then(function (payload) { applyScenario(payload); })
          .catch(function (err) { setStatus("Could not load " + btn.textContent + ": " + err.message, true); });
      });
    });

    var toggle = el("mobile-sheet-toggle"), stack = el("right-stack");
    toggle.addEventListener("click", function () {
      var expanded = stack.classList.toggle("expanded");
      toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
      toggle.querySelector("span").firstChild.textContent = expanded ? "Hide inputs " : "Adjust inputs ";
    });
  }

  // ---------------------------------------------------------------- start

  wireTooltips();

  fetch("/api/schema")
    .then(function (res) { return res.json(); })
    .then(function (data) {
      schema = data;
      schema.params.forEach(function (p) { state[p.key] = p.default; });
      buildControls();
      syncAllLabels();
      syncPresetSelect();
      wireActions();
      requestCompute();
    })
    .catch(function (err) {
      document.getElementById("stat-grid").innerHTML =
        '<div class="insight crit">Could not load the parameter schema: ' + esc(err.message) + "</div>";
    });
})();
