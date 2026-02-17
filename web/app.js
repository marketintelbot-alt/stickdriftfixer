const PROFILE_KEY = "driftline_web_profile_v1";

const ui = {
  connectionStatus: document.getElementById("connectionStatus"),
  gamepadSelect: document.getElementById("gamepadSelect"),
  refreshPadsBtn: document.getElementById("refreshPadsBtn"),
  useFirstBtn: document.getElementById("useFirstBtn"),
  mapAxesBtn: document.getElementById("mapAxesBtn"),
  calibrateBtn: document.getElementById("calibrateBtn"),
  mappingLabel: document.getElementById("mappingLabel"),
  profileLabel: document.getElementById("profileLabel"),
  leftRaw: document.getElementById("leftRaw"),
  leftFixed: document.getElementById("leftFixed"),
  rightRaw: document.getElementById("rightRaw"),
  rightFixed: document.getElementById("rightFixed"),
  leftMeter: document.getElementById("leftMeter"),
  rightMeter: document.getElementById("rightMeter"),
  saveLocalBtn: document.getElementById("saveLocalBtn"),
  loadLocalBtn: document.getElementById("loadLocalBtn"),
  exportBtn: document.getElementById("exportBtn"),
  importBtn: document.getElementById("importBtn"),
  importInput: document.getElementById("importInput"),
  resetBtn: document.getElementById("resetBtn"),
  profileDump: document.getElementById("profileDump"),
  log: document.getElementById("log"),
};

const state = {
  selectedGamepadIndex: null,
  mapping: { left: [0, 1], right: [2, 3] },
  profile: null,
  calibrating: false,
};

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

function fmt(value) {
  return Number.isFinite(value) ? value.toFixed(3) : "0.000";
}

function nowIso() {
  return new Date().toISOString();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function percentile(values, p) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = (sorted.length - 1) * clamp(p, 0, 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

function log(message) {
  const stamp = new Date().toLocaleTimeString();
  ui.log.textContent += `[${stamp}] ${message}\n`;
  ui.log.scrollTop = ui.log.scrollHeight;
}

function getConnectedGamepads() {
  return (navigator.getGamepads?.() || []).filter(Boolean);
}

function getSelectedGamepad() {
  const pads = navigator.getGamepads?.() || [];
  if (state.selectedGamepadIndex == null) return null;
  return pads[state.selectedGamepadIndex] || null;
}

function refreshGamepadSelect() {
  const pads = getConnectedGamepads();
  ui.gamepadSelect.innerHTML = "";

  if (!pads.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No gamepad detected";
    ui.gamepadSelect.appendChild(opt);
    state.selectedGamepadIndex = null;
    updateConnectionStatus();
    return;
  }

  for (const pad of pads) {
    const opt = document.createElement("option");
    opt.value = String(pad.index);
    opt.textContent = `#${pad.index} ${pad.id}`;
    ui.gamepadSelect.appendChild(opt);
  }

  if (state.selectedGamepadIndex == null || !pads.find((p) => p.index === state.selectedGamepadIndex)) {
    state.selectedGamepadIndex = pads[0].index;
  }

  ui.gamepadSelect.value = String(state.selectedGamepadIndex);
  updateConnectionStatus();
}

function updateConnectionStatus() {
  const gp = getSelectedGamepad();
  if (!gp) {
    ui.connectionStatus.textContent = "No gamepad connected";
    return;
  }

  ui.connectionStatus.textContent = `Connected: #${gp.index} ${gp.id}`;
}

function setProfile(profile) {
  state.profile = profile;
  ui.profileLabel.textContent = profile
    ? `Profile: calibrated ${profile.generatedAt}`
    : "Profile: not calibrated";
  ui.profileDump.textContent = profile ? JSON.stringify(profile, null, 2) : "";
}

function updateMappingLabel() {
  ui.mappingLabel.textContent = `Mapping: left=(${state.mapping.left[0]},${state.mapping.left[1]}) right=(${state.mapping.right[0]},${state.mapping.right[1]})`;
}

function getAxis(gp, index) {
  if (!gp || index == null || index < 0 || index >= gp.axes.length) return 0;
  return Number(gp.axes[index] || 0);
}

function applyAxisComp(raw, center, deadzone) {
  const centered = raw - center;
  const abs = Math.abs(centered);
  const dz = clamp(deadzone, 0.01, 0.6);
  if (abs <= dz) return 0;
  const normalized = (abs - dz) / (1 - dz);
  return Math.sign(centered) * clamp(normalized, 0, 1);
}

function liveTick() {
  const gp = getSelectedGamepad();

  if (!gp) {
    ui.leftRaw.textContent = "Raw: (0.000, 0.000)";
    ui.rightRaw.textContent = "Raw: (0.000, 0.000)";
    ui.leftFixed.textContent = "Fixed: (0.000, 0.000)";
    ui.rightFixed.textContent = "Fixed: (0.000, 0.000)";
    ui.leftMeter.style.width = "0%";
    ui.rightMeter.style.width = "0%";
    requestAnimationFrame(liveTick);
    return;
  }

  const [lxAxis, lyAxis] = state.mapping.left;
  const [rxAxis, ryAxis] = state.mapping.right;

  const lx = getAxis(gp, lxAxis);
  const ly = getAxis(gp, lyAxis);
  const rx = getAxis(gp, rxAxis);
  const ry = getAxis(gp, ryAxis);

  ui.leftRaw.textContent = `Raw: (${fmt(lx)}, ${fmt(ly)})`;
  ui.rightRaw.textContent = `Raw: (${fmt(rx)}, ${fmt(ry)})`;

  let fixLx = lx;
  let fixLy = ly;
  let fixRx = rx;
  let fixRy = ry;

  if (state.profile) {
    fixLx = applyAxisComp(lx, state.profile.left.x.center, state.profile.left.x.deadzone);
    fixLy = applyAxisComp(ly, state.profile.left.y.center, state.profile.left.y.deadzone);
    fixRx = applyAxisComp(rx, state.profile.right.x.center, state.profile.right.x.deadzone);
    fixRy = applyAxisComp(ry, state.profile.right.y.center, state.profile.right.y.deadzone);
  }

  ui.leftFixed.textContent = `Fixed: (${fmt(fixLx)}, ${fmt(fixLy)})`;
  ui.rightFixed.textContent = `Fixed: (${fmt(fixRx)}, ${fmt(fixRy)})`;

  const leftMag = Math.hypot(fixLx, fixLy);
  const rightMag = Math.hypot(fixRx, fixRy);
  ui.leftMeter.style.width = `${clamp(leftMag * 100, 0, 100)}%`;
  ui.rightMeter.style.width = `${clamp(rightMag * 100, 0, 100)}%`;

  requestAnimationFrame(liveTick);
}

async function sampleAxisSpans(durationMs) {
  const gp = getSelectedGamepad();
  if (!gp) throw new Error("No gamepad connected.");

  const axisCount = gp.axes.length;
  const mins = Array(axisCount).fill(1);
  const maxs = Array(axisCount).fill(-1);

  const end = performance.now() + durationMs;
  while (performance.now() < end) {
    const current = getSelectedGamepad();
    if (!current) break;

    for (let axis = 0; axis < axisCount; axis += 1) {
      const value = Number(current.axes[axis] || 0);
      mins[axis] = Math.min(mins[axis], value);
      maxs[axis] = Math.max(maxs[axis], value);
    }

    await sleep(1000 / 220);
  }

  return maxs.map((max, idx) => max - mins[idx]);
}

function pickTopAxis(spans, excluded) {
  const excludedSet = new Set(excluded);
  const candidates = spans
    .map((span, idx) => ({ idx, span }))
    .filter((item) => !excludedSet.has(item.idx))
    .sort((a, b) => b.span - a.span);

  if (!candidates.length) {
    throw new Error("No available axis candidates.");
  }

  return candidates[0];
}

async function runMappingWizard() {
  const gp = getSelectedGamepad();
  if (!gp) {
    alert("Connect a gamepad first.");
    return;
  }
  if (gp.axes.length < 4) {
    alert(`Controller reports only ${gp.axes.length} axes; at least 4 are required.`);
    return;
  }

  const prompts = [
    "Move ONLY LEFT stick in full circles for 2.5 seconds, then click OK.",
    "Keep moving ONLY LEFT stick in full circles for another 2.5 seconds, then click OK.",
    "Move ONLY RIGHT stick in full circles for 2.5 seconds, then click OK.",
    "Keep moving ONLY RIGHT stick in full circles for another 2.5 seconds, then click OK.",
  ];

  const detected = [];
  const spans = [];

  for (const instruction of prompts) {
    alert(instruction);
    const sample = await sampleAxisSpans(2500);
    const top = pickTopAxis(sample, detected);
    detected.push(top.idx);
    spans.push(top.span);
    log(`Mapping detected axis ${top.idx} span=${top.span.toFixed(3)}`);
  }

  let left = [detected[0], detected[1]];
  let right = [detected[2], detected[3]];

  if (Math.min(...spans) < 0.18) {
    left = [0, 1];
    right = [2, 3];
    log("Low mapping confidence. Falling back to left=(0,1), right=(2,3).");
  }

  state.mapping.left = left;
  state.mapping.right = right;
  updateMappingLabel();
}

async function collectAxisSamples(durationMs) {
  const gp = getSelectedGamepad();
  if (!gp) throw new Error("No gamepad connected.");

  const axisSet = [
    state.mapping.left[0],
    state.mapping.left[1],
    state.mapping.right[0],
    state.mapping.right[1],
  ];

  const samples = new Map(axisSet.map((axis) => [axis, []]));
  const end = performance.now() + durationMs;

  while (performance.now() < end) {
    const current = getSelectedGamepad();
    if (!current) break;

    for (const axis of axisSet) {
      const value = Number(current.axes[axis] || 0);
      samples.get(axis).push(value);
    }

    await sleep(1000 / 220);
  }

  return samples;
}

function buildAxisCalibration(values, axisIndex) {
  if (!values.length) {
    return { axis: axisIndex, center: 0, deadzone: 0.08 };
  }

  const mean = values.reduce((sum, n) => sum + n, 0) / values.length;
  const deltas = values.map((v) => Math.abs(v - mean));
  const p95 = percentile(deltas, 0.95);
  const deadzone = clamp(Math.max(p95 * 1.1, 0.04), 0.01, 0.6);

  return {
    axis: axisIndex,
    center: Number(mean.toFixed(6)),
    deadzone: Number(deadzone.toFixed(6)),
  };
}

function profileScore(profile) {
  return (
    profile.left.x.deadzone +
    profile.left.y.deadzone +
    profile.right.x.deadzone +
    profile.right.y.deadzone +
    Math.abs(profile.left.x.center) +
    Math.abs(profile.left.y.center) +
    Math.abs(profile.right.x.center) +
    Math.abs(profile.right.y.center)
  );
}

async function calibrateProfile() {
  if (state.calibrating) return;

  const gp = getSelectedGamepad();
  if (!gp) {
    alert("Connect a gamepad first.");
    return;
  }

  state.calibrating = true;
  try {
    alert("Leave sticks untouched for each pass. Calibration will run 3 passes of 3.5 seconds.");

    let best = null;
    let bestScore = Number.POSITIVE_INFINITY;

    for (let pass = 1; pass <= 3; pass += 1) {
      log(`Calibration pass ${pass}/3 started.`);
      const sampleMap = await collectAxisSamples(3500);

      const [lxAxis, lyAxis] = state.mapping.left;
      const [rxAxis, ryAxis] = state.mapping.right;

      const candidate = {
        controllerName: gp.id,
        generatedAt: nowIso(),
        mapping: {
          left: [...state.mapping.left],
          right: [...state.mapping.right],
        },
        left: {
          x: buildAxisCalibration(sampleMap.get(lxAxis) || [], lxAxis),
          y: buildAxisCalibration(sampleMap.get(lyAxis) || [], lyAxis),
        },
        right: {
          x: buildAxisCalibration(sampleMap.get(rxAxis) || [], rxAxis),
          y: buildAxisCalibration(sampleMap.get(ryAxis) || [], ryAxis),
        },
      };

      const score = profileScore(candidate);
      log(`Pass ${pass} score=${score.toFixed(4)}`);
      if (score < bestScore) {
        best = candidate;
        bestScore = score;
      }
    }

    if (!best) {
      throw new Error("Calibration failed.");
    }

    setProfile(best);
    log("Calibration complete.");
  } catch (err) {
    alert(err.message || "Calibration failed.");
    log(`Calibration error: ${err.message || String(err)}`);
  } finally {
    state.calibrating = false;
  }
}

function saveLocalProfile() {
  if (!state.profile) {
    alert("No profile to save.");
    return;
  }
  localStorage.setItem(PROFILE_KEY, JSON.stringify(state.profile));
  log("Saved profile to browser storage.");
}

function loadLocalProfile() {
  const raw = localStorage.getItem(PROFILE_KEY);
  if (!raw) {
    alert("No saved profile in browser storage.");
    return;
  }

  try {
    const profile = JSON.parse(raw);
    setProfile(profile);
    if (profile.mapping?.left && profile.mapping?.right) {
      state.mapping.left = [...profile.mapping.left];
      state.mapping.right = [...profile.mapping.right];
      updateMappingLabel();
    }
    log("Loaded profile from browser storage.");
  } catch {
    alert("Saved profile is invalid JSON.");
  }
}

function exportProfile() {
  if (!state.profile) {
    alert("No profile to export.");
    return;
  }

  const blob = new Blob([JSON.stringify(state.profile, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `driftline-web-profile-${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
  log("Exported profile JSON.");
}

function resetProfile() {
  setProfile(null);
  localStorage.removeItem(PROFILE_KEY);
  log("Profile reset.");
}

function importProfileFile(file) {
  if (!file) return;

  const reader = new FileReader();
  reader.onload = () => {
    try {
      const profile = JSON.parse(String(reader.result));
      setProfile(profile);
      if (profile.mapping?.left && profile.mapping?.right) {
        state.mapping.left = [...profile.mapping.left];
        state.mapping.right = [...profile.mapping.right];
        updateMappingLabel();
      }
      log("Imported profile from file.");
    } catch {
      alert("Invalid profile JSON file.");
    }
  };

  reader.readAsText(file);
}

function wireEvents() {
  ui.refreshPadsBtn.addEventListener("click", refreshGamepadSelect);
  ui.useFirstBtn.addEventListener("click", () => {
    const pads = getConnectedGamepads();
    if (!pads.length) {
      alert("No gamepad connected.");
      return;
    }
    state.selectedGamepadIndex = pads[0].index;
    ui.gamepadSelect.value = String(state.selectedGamepadIndex);
    updateConnectionStatus();
    log(`Selected gamepad #${state.selectedGamepadIndex}.`);
  });

  ui.gamepadSelect.addEventListener("change", (event) => {
    const value = event.target.value;
    state.selectedGamepadIndex = value === "" ? null : Number(value);
    updateConnectionStatus();
  });

  ui.mapAxesBtn.addEventListener("click", runMappingWizard);
  ui.calibrateBtn.addEventListener("click", calibrateProfile);

  ui.saveLocalBtn.addEventListener("click", saveLocalProfile);
  ui.loadLocalBtn.addEventListener("click", loadLocalProfile);
  ui.exportBtn.addEventListener("click", exportProfile);
  ui.importBtn.addEventListener("click", () => ui.importInput.click());
  ui.importInput.addEventListener("change", (event) => {
    importProfileFile(event.target.files?.[0]);
    ui.importInput.value = "";
  });
  ui.resetBtn.addEventListener("click", resetProfile);

  window.addEventListener("gamepadconnected", () => {
    refreshGamepadSelect();
    log("Gamepad connected.");
  });

  window.addEventListener("gamepaddisconnected", () => {
    refreshGamepadSelect();
    updateConnectionStatus();
    log("Gamepad disconnected.");
  });
}

function init() {
  updateMappingLabel();
  wireEvents();
  refreshGamepadSelect();
  loadLocalProfile();
  liveTick();
  log("Driftline Web ready.");
}

init();
