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
      node.addEventListener("input", function () {
        state[p.key] = parseFloat(node.value);
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
    var unit = p.unit ? " " + p.unit : "";
    node.textContent = fmt(state[p.key], p.decimals) + unit;
  }

  function syncAllLabels() { schema.params.forEach(syncLabel); }

  function setValue(key, value) {
    var p = schema.params.find(function (q) { return q.key === key; });
    if (!p) return;
    var clamped = Math.min(Math.max(value, p.min), p.max);
    state[key] = clamped;
    var node = el("in-" + key);
    if (node) node.value = clamped;
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

  function renderStats(r) {
    var html = "";
    html += statTile("heat", "Heating design capacity", kW(r.heating_design), "kW",
      "hold " + kW(r.heating_hold) + " + ramp " + kW(r.power_mass) + " + margin",
      "What the air-handling coil and fan must deliver to the room: the steady-state hold at the coldest boundary, plus the power to charge the room's mass through the ramp, plus your safety margin.");
    html += statTile("cool", "Cooling design capacity", kW(r.cooling_design), "kW",
      "hold " + kW(r.cooling_hold) + " + ramp " + kW(r.power_mass) + " + margin",
      "Same as heating, at the hottest boundary and including solar gain through the glazing.");
    html += statTile("neutral", "Design supply airflow", fmt(r.design_flow_ls, 0), "L/s",
      fmt(r.design_flow_m3h, 0) + " m³/h · set by " + (r.flow_set_by_ventilation ? "ventilation minimum" : "capacity"),
      "The larger of the airflow needed to deliver the design capacity within your max supply ΔT, and the ventilation minimum from the air-change rate.");
    html += statTile("neutral", "Dehumidification", kW(r.latent_design), "kW",
      "dew point at setpoint " + fmt(r.dew_point_c, 1) + " °C",
      "Ventilation moisture plus occupant moisture, from ASHRAE psychrometrics on both air states. Sized at the cold setpoint, which is the harder case.");
    html += statTile(r.film_ok ? "neutral" : "alert", "Air-to-surface ΔT needed", fmt(r.required_air_surface_dt, 1), "K",
      r.film_ok ? "within your allowance" : "exceeds your allowance — ramp unreachable",
      "To charge the mass this fast, the room air has to run this far from the surfaces. It is set by the surface film coefficient and the interior area, and no amount of coil capacity changes it.");
    html += statTile("heat", "Dedicated heat pump, heating", kW(r.plant_heating), "kW",
      "hold " + kW(r.heating_hold) + " + buffer assist " + kW(r.plant_extra) + " + margin",
      "The room's own heat pump, sized with the hot Pufferspeicher absorbing the ramp surge, so it covers the steady hold plus whatever the buffer cannot.");
    html += statTile("cool", "Dedicated heat pump, cooling", kW(r.plant_cooling), "kW",
      "hold " + kW(r.cooling_hold) + " + buffer assist " + kW(r.plant_extra) + " + margin",
      "Same logic as the heating heat pump, using the cold Pufferspeicher.");
    html += statTile("neutral", "Fastest reachable ramp", fmt(r.min_feasible_ramp_minutes, 0), "min",
      "at " + fmt(state.max_air_surface_dt, 0) + " K air-to-surface allowance",
      "The shortest ramp the surface film physically permits for this much mass. Asking for less than this cannot work regardless of equipment.");
    el("stat-grid").innerHTML = html;
  }

  function ratioPhrase(ramp, hold) {
    if (ramp <= 0) return "adds nothing on top of the steady-state hold.";
    if (hold < 30) return "— the steady-state hold is nearly negligible, so the ramp is the whole story.";
    var ratio = ramp / hold;
    if (ratio >= 10) return "— roughly " + Math.round(ratio) + "× the steady-state hold.";
    if (ratio >= 1.15) return "— about " + fmt(ratio, 1) + "× the steady-state hold.";
    return "— comparable in size to the steady-state hold.";
  }

  function renderInsights(data) {
    var r = data.results;
    var html = "";
    html += '<div class="insight heat">Ramping ' + fmt(r.ramp_delta_t, 0) + "°C in " + fmt(r.ramp_minutes, 0) +
      " min adds <b>" + kW(r.power_mass) + " kW</b> on top of the <b>" + kW(r.heating_hold) +
      " kW</b> needed just to hold " + fmt(r.setpoint_max, 0) + "°C against the winter boundary " +
      ratioPhrase(r.power_mass, r.heating_hold) + "</div>";
    html += '<div class="insight cool">The same ramp adds <b>' + kW(r.power_mass) + " kW</b> on top of the <b>" +
      kW(r.cooling_hold) + " kW</b> needed just to hold " + fmt(r.setpoint_min, 0) +
      "°C against the summer boundary " + ratioPhrase(r.power_mass, r.cooling_hold) + "</div>";

    if (state.added_mass_area > 0) {
      var overstate = data.lumped.power_mass / (r.power_mass || 1);
      html += '<div class="insight accent span-2">Heat reaches <b>' + fmt(r.added_penetration_mm, 0) +
        " mm</b> into the added mass during a " + fmt(r.ramp_minutes, 0) + "-minute ramp, so <b>" +
        fmt(100 * r.added_participating_fraction, 0) + "%</b> of the " + fmt(1000 * state.added_mass_thickness, 0) +
        " mm layer takes part. Crediting the whole layer would put the ramp requirement at " +
        kW(data.lumped.power_mass) + " kW instead of " + kW(r.power_mass) + " kW, overstating it by " +
        fmt(overstate, 1) + "×." +
        infoIcon("Diffusion depth for a linear surface ramp is 4/(3&radic;&pi;)&middot;&radic;(&alpha;t), with &alpha; = k/&rho;c. Deep mass cannot be charged in a short ramp at any power.") +
        "</div>";
    }

    if (!r.film_ok) {
      html += '<div class="insight crit span-2">To charge the mass in ' + fmt(r.ramp_minutes, 0) +
        " minutes, the air would have to sit <b>" + fmt(r.required_air_surface_dt, 0) +
        " K</b> away from the surfaces, against your <b>" + fmt(state.max_air_surface_dt, 0) +
        " K</b> allowance. This ramp is not reachable by adding capacity. The shortest ramp the film permits here is <b>" +
        fmt(r.min_feasible_ramp_minutes, 0) + " minutes</b>; reducing mass or relaxing the setpoint range are the other levers." +
        infoIcon("Mass-charging power is capped at h &times; interior area &times; the air-to-surface &Delta;T you allow. With h &asymp; 8 W/m&sup2;K this ceiling binds long before the coil does.") +
        "</div>";
    }

    var bufText;
    if (r.buffer_covers_ramp) {
      bufText = "Your " + fmt(state.buffer_volume_l, 0) + " L buffer stores about <b>" + fmt(r.buffer_energy_kwh, 1) +
        " kWh</b>, enough to cover this ramp's <b>" + fmt(r.energy_mass_kwh, 1) +
        " kWh</b> mass-charge surge entirely. The dedicated heat pump then only needs <b>" + kW(r.plant_extra) +
        " kW</b> continuously to refill it inside the " + fmt(state.recharge_minutes, 0) + "-minute window.";
    } else {
      bufText = "Your " + fmt(state.buffer_volume_l, 0) + " L buffer stores about <b>" + fmt(r.buffer_energy_kwh, 1) +
        " kWh</b>, only " + fmt(r.buffer_coverage_pct, 0) + "% of this ramp's <b>" + fmt(r.energy_mass_kwh, 1) +
        " kWh</b> surge. The heat pump still has to supply <b>" + kW(r.plant_extra) +
        " kW</b> on top of the steady hold. A bigger tank or a slower ramp brings that down.";
    }
    html += '<div class="insight accent span-2">' + bufText +
      infoIcon("Buffer coverage compares stored energy (volume &times; usable &Delta;T) with the ramp's mass-charge energy. When it covers the ramp, the heat pump only tracks steady state and its own recharge.") + "</div>";

    var agg = "If " + fmt(state.n_chambers, 0) + " chamber(s) peak together at " + fmt(state.diversity_pct, 0) +
      "% simultaneity, the aggregate anergy-grid tie-in needs roughly <b>" + kW(r.aggregate_heating) +
      " kW</b> heating and <b>" + kW(r.aggregate_cooling) + " kW</b> cooling across all dedicated plants.";
    if (state.n_chambers <= 1) agg += " With one chamber this equals its own dedicated plant.";
    html += '<div class="insight muted span-2">' + agg +
      infoIcon("Each chamber's own heat pump is still sized to its own number above. This figure is only what the shared grid connection has to supply.") + "</div>";

    el("insight-row").innerHTML = html;
  }

  function renderSensitivity(data) {
    var r = data.results, sweep = data.sweep;
    var w = 520, h = 220, padL = 46, padR = 12, padT = 12, padB = 28;
    var plotW = w - padL - padR, plotH = h - padT - padB;

    var maxT = sweep.ramp_minutes[sweep.ramp_minutes.length - 1];
    var maxY = 0;
    sweep.heating_design.forEach(function (v, i) {
      maxY = Math.max(maxY, v / 1000, sweep.cooling_design[i] / 1000);
    });
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
    var limit = Math.min(sweep.min_feasible_ramp_minutes, maxT);
    if (limit > sweep.ramp_minutes[0]) {
      unreachable = '<rect x="' + padL + '" y="' + padT + '" width="' + Math.max(x(limit) - padL, 0).toFixed(1) +
        '" height="' + plotH + '" fill="var(--crit)" opacity="0.13"/>' +
        '<line x1="' + x(limit).toFixed(1) + '" y1="' + padT + '" x2="' + x(limit).toFixed(1) + '" y2="' + (padT + plotH) +
        '" stroke="var(--crit)" stroke-width="1.5" stroke-dasharray="4,3"/>';
    }

    var curX = x(Math.min(Math.max(r.ramp_minutes, sweep.ramp_minutes[0]), maxT));

    var svg = '<svg viewBox="0 0 ' + w + " " + h + '" width="100%" role="img" aria-label="Design capacity versus ramp time">' +
      grid + unreachable +
      '<line x1="' + padL + '" y1="' + padT + '" x2="' + padL + '" y2="' + (padT + plotH) + '" class="axis-line"/>' +
      '<line x1="' + padL + '" y1="' + (padT + plotH) + '" x2="' + (w - padR) + '" y2="' + (padT + plotH) + '" class="axis-line"/>' +
      xTicks +
      '<path d="' + pathFor("heating_design") + '" fill="none" stroke="var(--heat)" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round"/>' +
      '<path d="' + pathFor("cooling_design") + '" fill="none" stroke="var(--cool)" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round"/>' +
      '<line x1="' + curX.toFixed(1) + '" y1="' + padT + '" x2="' + curX.toFixed(1) + '" y2="' + (padT + plotH) + '" stroke="var(--text)" stroke-width="1" opacity="0.35"/>' +
      '<circle cx="' + curX.toFixed(1) + '" cy="' + y(r.heating_design / 1000).toFixed(1) + '" r="4" fill="var(--heat)"/>' +
      '<circle cx="' + curX.toFixed(1) + '" cy="' + y(r.cooling_design / 1000).toFixed(1) + '" r="4" fill="var(--cool)"/>' +
      '<text x="' + (w - padR) + '" y="' + (padT + 10) + '" text-anchor="end" font-size="9">kW</text>' +
      '<text x="' + (padL + plotW / 2) + '" y="' + (h - 0) + '" text-anchor="middle" font-size="9">ramp time, min</text>' +
      "</svg>";
    el("sensitivity-chart").innerHTML = svg;
  }

  function renderBreakdown(r) {
    var w = 420, rowH = 46, gap = 18, padL = 90, padR = 62, padT = 10;
    var h = padT * 2 + rowH * 2 + gap;
    var plotW = w - padL - padR;
    var maxTotal = Math.max(r.heating_design, r.cooling_design) || 1;

    function row(yPos, label, hold, ramp, marginAmt) {
      var scale = plotW / maxTotal, gapPx = 2;
      var wHold = hold * scale, wRamp = ramp * scale, wMarg = marginAmt * scale;
      var out = '<text x="' + (padL - 10) + '" y="' + (yPos + rowH / 2 + 4) + '" text-anchor="end" font-size="10" font-weight="600">' + label + "</text>";
      out += '<rect x="' + padL + '" y="' + yPos + '" width="' + Math.max(wHold - gapPx, 0) + '" height="' + rowH + '" rx="4" fill="var(--surface-2)" stroke="var(--line)"/>';
      out += '<rect x="' + (padL + wHold + gapPx) + '" y="' + yPos + '" width="' + Math.max(wRamp - gapPx, 0) + '" height="' + rowH + '" rx="4" fill="color-mix(in srgb, var(--text) 55%, var(--surface))"/>';
      out += '<rect x="' + (padL + wHold + wRamp + gapPx * 2) + '" y="' + yPos + '" width="' + Math.max(wMarg - gapPx, 0) + '" height="' + rowH + '" rx="4" fill="var(--accent)"/>';
      out += '<text x="' + (padL + wHold + wRamp + wMarg + 8) + '" y="' + (yPos + rowH / 2 + 4) + '" font-size="11" font-weight="600" class="mono">' + kW(hold + ramp + marginAmt) + " kW</text>";
      return out;
    }

    var mf = r.margin_frac;
    var svg = '<svg viewBox="0 0 ' + w + " " + h + '" width="100%" role="img" aria-label="Load breakdown">' +
      row(padT, "Heating", r.heating_hold, r.power_mass, r.heating_design * mf / (1 + mf)) +
      row(padT + rowH + gap, "Cooling", r.cooling_hold, r.power_mass, r.cooling_design * mf / (1 + mf)) +
      "</svg>";
    el("breakdown-chart").innerHTML = svg;
  }

  function checkCard(label, req, limit, ok, unit, note, tooltip) {
    var scaleMax = Math.max(limit * 1.4, req * 1.08, 1);
    var fillPct = Math.min((req / scaleMax) * 100, 100);
    var limitPct = Math.min((limit / scaleMax) * 100, 100);
    return '<div class="check-card">' +
      '<div class="check-head"><h3>' + label + infoIcon(tooltip) + "</h3>" +
      '<span class="badge ' + (ok ? "good" : "crit") + '">' + (ok ? "within limit" : "exceeds limit") + "</span></div>" +
      '<div class="flux-bar-track"><div class="flux-bar-fill" style="width:' + fillPct + "%;background:" + (ok ? "var(--good)" : "var(--crit)") + '"></div>' +
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
    html += checkCard("Radiant heating flux", r.radiant_flux_heat, state.radiant_heat_limit, r.radiant_heat_ok, "W/m²",
      r.radiant_heat_ok ? "" : "Radiant alone cannot hold this steady load. The air system carries about <b class=\"mono\">" + kW(r.air_steady_heating) + " kW</b> of it continuously, on top of its ramp duty.",
      "Steady-state heating hold divided by the active radiant area, against the panel's W/m&sup2; limit. Checks the hold only — radiant is not sized for the ramp.");
    html += checkCard("Radiant cooling flux", r.radiant_flux_cool, state.radiant_cool_limit, r.radiant_cool_ok, "W/m²",
      (r.radiant_cool_ok ? "" : "Radiant alone cannot hold this steady load. The air system carries about <b class=\"mono\">" + kW(r.air_steady_cooling) + " kW</b> of it continuously. ") +
      "Surfaces must stay above the <b>" + fmt(r.dew_point_c, 1) + " °C</b> dew point at your target RH.",
      "Steady-state cooling hold divided by the active radiant area, against the condensation-limited W/m&sup2; limit.");
    html += checkCard("Mass charging vs. surface film", r.required_air_surface_dt, state.max_air_surface_dt, r.film_ok, "K",
      "At h = " + fmt(state.surface_film_h, 1) + " W/m²K over " + fmt(r.exchange_area, 0) +
      " m², the most that can enter the mass is <b class=\"mono\">" + kW(r.max_mass_power) +
      " kW</b>, giving a fastest ramp of <b>" + fmt(r.min_feasible_ramp_minutes, 0) + " min</b>.",
      "Mass charging is capped by convection and radiation from the air to the surfaces. This is independent of coil capacity and is usually the binding constraint.");
    html += checkCard("Buffer coverage of the ramp", r.energy_mass_kwh, r.buffer_energy_kwh, r.buffer_covers_ramp, "kWh",
      "Stored energy only. The tank's own discharge and flow-rate limits still need checking against its spec.",
      "Ramp mass-charge energy against the Pufferspeicher's stored energy (volume &times; usable &Delta;T).");
    el("check-grid").innerHTML = html;
  }

  function render(data) {
    hideTip();
    renderStats(data.results);
    renderInsights(data);
    renderSensitivity(data);
    renderBreakdown(data.results);
    renderEnvelope(data.results);
    renderChecks(data.results);
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
      "Heating design (AHU): " + kW(r.heating_design) + " kW (hold " + kW(r.heating_hold) + " + ramp " + kW(r.power_mass) + ", incl. " + fmt(state.margin_pct, 0) + "% margin)",
      "Cooling design (AHU): " + kW(r.cooling_design) + " kW (hold " + kW(r.cooling_hold) + " + ramp " + kW(r.power_mass) + ")",
      "Dehumidification: " + kW(r.latent_design) + " kW; dew point at setpoint " + fmt(r.dew_point_c, 1) + " C",
      "Supply airflow: " + fmt(r.design_flow_ls, 0) + " L/s (" + fmt(r.design_flow_m3h, 0) + " m3/h), set by " + (r.flow_set_by_ventilation ? "ventilation minimum" : "capacity"),
      "Air-to-surface dT needed: " + fmt(r.required_air_surface_dt, 1) + " K vs " + fmt(state.max_air_surface_dt, 0) + " K allowed -> " + (r.film_ok ? "REACHABLE" : "NOT REACHABLE"),
      "Fastest ramp the surface film permits: " + fmt(r.min_feasible_ramp_minutes, 0) + " min",
      "Added mass participating: " + fmt(100 * r.added_participating_fraction, 0) + "% (" + fmt(r.added_penetration_mm, 0) + " mm of " + fmt(1000 * state.added_mass_thickness, 0) + " mm)",
      "Dedicated heat pump: heating " + kW(r.plant_heating) + " kW, cooling " + kW(r.plant_cooling) + " kW, with " + fmt(state.buffer_volume_l, 0) + " L buffer at " + fmt(state.buffer_dt, 0) + " K swing",
      "Buffer covers " + fmt(r.buffer_coverage_pct, 0) + "% of the ramp's " + fmt(r.energy_mass_kwh, 1) + " kWh surge",
      "Aggregate grid tie-in (" + fmt(state.n_chambers, 0) + " chambers at " + fmt(state.diversity_pct, 0) + "%): heating " + kW(r.aggregate_heating) + " kW, cooling " + kW(r.aggregate_cooling) + " kW",
      "Radiant heating " + fmt(r.radiant_flux_heat, 0) + " W/m2 (limit " + fmt(state.radiant_heat_limit, 0) + ") - " + (r.radiant_heat_ok ? "OK" : "EXCEEDS"),
      "Radiant cooling " + fmt(r.radiant_flux_cool, 0) + " W/m2 (limit " + fmt(state.radiant_cool_limit, 0) + ") - " + (r.radiant_cool_ok ? "OK" : "EXCEEDS"),
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
          var payload = JSON.parse(reader.result);
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
        } catch (err) {
          setStatus("Could not read that file: " + err.message, true);
        }
      };
      reader.readAsText(file);
      event.target.value = "";
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
