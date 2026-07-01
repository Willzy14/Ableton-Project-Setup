/* Stem → Ableton — front-end logic. Vanilla JS, talks to engine_api.Api. */
"use strict";

const State = {
  projects: [],
  palette: [],
  colorCategories: [],
  profiles: [],
  settings: { output_folder: "", active_profile: "" },
  editProfile: null,   // working copy in the colours modal
  polling: null,
  buildOrder: null,    // ready projects in the order run_batch consumed them
  batchRunning: false, // true while a batch build is in flight
};

let nextId = 1;
const $ = (id) => document.getElementById(id);

/* ---- pywebview bridge ---- */
function api() {
  if (window.pywebview && window.pywebview.api) return window.pywebview.api;
  return null; // running in a plain browser preview
}

window.addEventListener("pywebviewready", init);
// Fallback for browser preview (no pywebview): still render the shell.
setTimeout(() => { if (!State.booted) init(); }, 400);

async function init() {
  if (State.booted) return;
  State.booted = true;
  const a = api();
  if (a) {
    const boot = await a.get_bootstrap();
    State.palette = boot.palette;
    State.colorCategories = boot.colorCategories;
    State.profiles = boot.profiles;
    State.settings = boot.settings;
    State.version = boot.version;
  } else {
    // preview-only defaults
    State.palette = Array.from({ length: 70 }, (_, i) => `hsl(${i * 5},70%,55%)`);
    State.colorCategories = ["drums", "bass", "music", "vocals", "fx", "sends"];
    State.profiles = [{ name: "Default", colors: {} }];
    State.settings = { output_folder: "(set in app)", active_profile: "Default",
                       subgroups: ["vocals", "drums", "music"] };
    State.version = "preview";
  }
  const vb = $("versionBadge"); if (vb) vb.textContent = "v" + (State.version || "—");
  hydrateTopbar();
  hydrateSubgroups();
  renderPreview();
  if (State.projects.length === 0) addProject();
  wireGlobalButtons();
}

/* ---- top bar ---- */
function hydrateTopbar() {
  const sel = $("profileSelect");
  sel.innerHTML = "";
  State.profiles.forEach((p) => sel.add(new Option(p.name, p.name)));
  sel.value = State.settings.active_profile || State.profiles[0].name;
  sel.onchange = async () => {
    State.settings.active_profile = sel.value;
    const a = api(); if (a) await a.set_setting("active_profile", sel.value);
    renderQueue();   // refresh per-card default profile
    renderPreview(); // recolour the preview to the newly-active profile
  };
  const f = $("outputFolder");
  f.textContent = State.settings.output_folder || "—";
  f.title = State.settings.output_folder || "";
}

/* ---- sub-groups toggle (global) ---- */
const SG_BOXES = { vocals: "sgVocals", drums: "sgDrums", music: "sgMusic" };

function hydrateSubgroups() {
  const enabled = State.settings.subgroups || ["vocals", "drums", "music"];
  State.settings.subgroups = enabled;
  for (const [cat, id] of Object.entries(SG_BOXES)) {
    const box = $(id);
    if (!box) continue;
    box.checked = enabled.includes(cat);
    box.onchange = persistSubgroups;
  }
}

async function persistSubgroups() {
  const enabled = Object.entries(SG_BOXES)
    .filter(([, id]) => $(id) && $(id).checked)
    .map(([cat]) => cat);
  State.settings.subgroups = enabled;
  renderPreview();
  const a = api();
  if (a) await a.set_setting("subgroups", enabled);
}

/* ---- session preview (colour-language legend) ----
   Shows the session the app builds — colour-coded lanes with tiny faux-waveforms,
   groups + nested sub-groups. The colours mirror the ACTIVE colour profile (the
   real Ableton palette indices Sam picked), and the tree reacts to the Vox/Drums/
   Music sub-group toggles. `cc` = colour category; `sg` = sub-group toggle key. */
/* Each lane carries a characteristic 9-band spectral shape (20 Hz → 16 kHz) —
   honest category fingerprints (kick low-heavy, hats airy, vox in the mids), not
   the old integer-seeded fake sine bars. `cc` = colour category; `sg` = sub-group
   toggle key. */
const PREVIEW_LANES = [
  { name: "Kick",     cc: "drums",  spec: [96, 80, 52, 28, 16, 10, 7, 5, 4] },
  { name: "Drums",    cc: "drums",  grp: "GRP", sg: "drums", spec: [70, 58, 46, 42, 48, 60, 72, 66, 50],
    subs: [ { name: "Kit", spec: [64, 55, 45, 44, 52, 66, 74, 60, 44] },
            { name: "Perc", spec: [10, 14, 22, 34, 50, 66, 80, 86, 78] } ] },
  { name: "Bass",     cc: "bass",   spec: [68, 90, 76, 46, 26, 15, 10, 7, 5] },
  { name: "Music",    cc: "music",  grp: "GRP", sg: "music", spec: [18, 34, 56, 74, 80, 78, 66, 56, 46],
    subs: [ { name: "Synth", spec: [14, 28, 52, 70, 82, 80, 68, 58, 48] },
            { name: "Keys", spec: [22, 40, 60, 72, 74, 66, 54, 42, 32] } ] },
  { name: "Vox",      cc: "vocals", grp: "GRP", sg: "vocals", spec: [12, 24, 48, 72, 86, 74, 56, 40, 28],
    subs: [ { name: "Lauren", spec: [14, 26, 50, 74, 84, 72, 54, 38, 26] },
            { name: "Sarah", spec: [10, 22, 46, 70, 88, 76, 58, 42, 30] } ] },
  { name: "FX",       cc: "fx",     spec: [8, 12, 20, 32, 45, 58, 70, 82, 88] },
  { name: "Flat Ref", cc: "ref",    spec: [58, 70, 66, 58, 54, 52, 56, 54, 48] },
];

const REF_PALETTE_INDEX = 14; // references are always red (Ableton index 14)

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/* Resolve a category's colour from the ACTIVE profile's palette index, so the
   preview shows the colours Sam actually chose. Falls back to the CSS category
   colour when a profile hasn't set that category. */
function activeProfileColor(cc) {
  if (cc === "ref") return State.palette[REF_PALETTE_INDEX] || cssVar("--cat-ref");
  const prof = State.profiles.find((p) => p.name === State.settings.active_profile)
    || State.profiles[0];
  const idx = prof && prof.colors ? prof.colors[cc] : undefined;
  if (idx != null && State.palette[idx]) return State.palette[idx];
  return cssVar("--cat-" + cc) || "#8a94a0";
}

/* Draw a spectrum as N interpolated bars from a 9-band shape. */
function specBars(spec) {
  const n = 15, m = spec.length;
  let out = "";
  for (let i = 0; i < n; i++) {
    const t = (i / (n - 1)) * (m - 1);
    const lo = Math.floor(t), hi = Math.min(m - 1, lo + 1), f = t - lo;
    const v = spec[lo] * (1 - f) + spec[hi] * f;
    out += `<i style="height:${Math.max(6, Math.round(v))}%"></i>`;
  }
  return out;
}

function laneEl({ name, color, spec, grp, arrow }) {
  const el = document.createElement("div");
  el.className = "lane" + (arrow ? " sub" : "");
  el.style.color = color;
  el.innerHTML =
    `<span class="tag" style="background:${color}"></span>` +
    `<span class="lane-name">${arrow ? '<span class="arrow">↳</span>' : ""}${escapeHtml(name)}</span>` +
    (grp ? `<span class="grp">${grp}</span>` : "") +
    `<span class="wave">${specBars(spec)}</span>`;
  return el;
}

function renderPreview() {
  const host = $("previewLanes");
  if (!host) return;
  host.innerHTML = "";
  const enabled = State.settings.subgroups || [];
  PREVIEW_LANES.forEach((lane) => {
    const color = activeProfileColor(lane.cc);
    host.appendChild(laneEl({ name: lane.name, color, spec: lane.spec, grp: lane.grp }));
    if (lane.subs && lane.sg && enabled.includes(lane.sg)) {
      lane.subs.forEach((s) =>
        host.appendChild(laneEl({ name: s.name, color, spec: s.spec, arrow: true })));
    }
  });
}

function wireGlobalButtons() {
  $("addProjectBtn").onclick = addProject;
  $("previewColoursBtn").onclick = openColours;
  $("updateBtn").onclick = checkForUpdate;
  $("closeColours").onclick = () => $("coloursModal").classList.add("hidden");
  $("changeFolderBtn").onclick = changeFolder;
  $("goBtn").onclick = runBatch;
  $("saveProfileBtn").onclick = saveProfile;
  $("newProfileBtn").onclick = newProfile;
  $("deleteProfileBtn").onclick = deleteProfile;
  // #progressOverlay is retained in the DOM but no longer used — the build
  // status + result now live inline on each queue card. Guard the wiring in
  // case the element is later removed.
  const cp = $("closeProgress");
  if (cp) cp.onclick = () => $("progressOverlay").classList.add("hidden");
}

async function checkForUpdate() {
  const a = api();
  if (!a) { toast("Updates run in the app window.", "warn"); return; }
  const btn = $("updateBtn");
  const old = btn.textContent;
  btn.textContent = "⟳ Checking…"; btn.disabled = true;
  try {
    const r = await a.update_app();
    if (!r.ok) {
      toast("Update: " + (r.error || "failed"), "bad");
    } else if (r.needsApply) {
      // Packaged app: a newer EXE is available — confirm, then self-swap.
      const msg = "Version " + r.latest + " is available (you have v" + r.version + ")."
        + (r.notes ? "\n\n" + r.notes : "") + "\n\nDownload and install now? The app will relaunch.";
      if (confirm(msg)) {
        btn.textContent = "⟳ Installing…";
        const ar = await a.apply_update(r.download_url);
        if (!ar.ok) toast("Install failed: " + (ar.error || "unknown"), "bad");
        else toast("Installing v" + r.latest + " — the app will close and reopen.", "good");
      }
    } else if (r.changed) {
      // Dev/source checkout: git pull happened.
      toast("Updated to v" + r.version + " — relaunch to apply.", "good");
    } else {
      toast("You're on the latest version (v" + (r.version || State.version) + ").", "good");
    }
  } finally {
    btn.textContent = old; btn.disabled = false;
  }
}

async function changeFolder() {
  const a = api(); if (!a) return;
  const r = await a.pick_output_folder();
  if (r && r.ok) {
    State.settings.output_folder = r.folder;
    hydrateTopbar();
  }
}

/* ---- project queue ---- */
function addProject() {
  State.projects.push({
    id: nextId++, paths: [], title: "",
    profile: State.settings.active_profile, bpm: "",
  });
  renderQueue();
}

function removeProject(id) {
  State.projects = State.projects.filter((p) => p.id !== id);
  if (State.projects.length === 0) addProject();
  renderQueue();
}

function renderQueue() {
  const q = $("queue");
  q.innerHTML = "";
  State.projects.forEach((proj) => q.appendChild(renderCard(proj)));
  updateSummary();
}

function renderCard(proj) {
  const st = proj.status || null;                 // polled status entry, if any
  const state = st ? st.state : null;             // pending|running|done|warn|failed
  const busy = state === "running" || state === "pending";
  const finished = state === "done" || state === "warn" || state === "failed";

  const card = document.createElement("div");
  card.className = "card" + (state ? " state-" + state : "");

  // dropzone
  const dz = document.createElement("div");
  dz.className = "dropzone" + (proj.paths.length ? " filled" : "");
  dz.innerHTML = proj.paths.length
    ? `<div class="dz-icon">✓</div>
       <div class="dz-main">${proj.paths.length} item${proj.paths.length > 1 ? "s" : ""} ready</div>
       <div class="dz-sub">${shortPaths(proj.paths)}</div>
       <div class="dz-sub">${busy ? "building…" : "click to change"}</div>`
    : `<div class="dz-icon">⬇</div>
       <div class="dz-main">Drop stems here</div>
       <div class="dz-sub">folder, WAV / AIFF, or .zip — click to browse</div>`;
  // Lock ingest while this card is building; otherwise wire the picker + drop.
  if (!busy) {
    dz.onclick = () => choosePaths(proj.id);
    wireDrop(dz, proj.id);
  }

  // fields
  const fields = document.createElement("div");
  fields.className = "card-fields";
  const title = document.createElement("input");
  title.className = "input title";
  title.type = "text";
  title.placeholder = "Artist - Title [Label]";
  title.value = proj.title;
  title.disabled = !!busy;
  title.oninput = () => { proj.title = title.value; updateSummary(); };
  fields.appendChild(title);

  if (finished && st.report && (state === "done" || state === "warn")) {
    // ── Result inline, in place of the profile+BPM row ──
    fields.appendChild(resultEl(st.report));
  } else if (finished && state === "failed") {
    fields.appendChild(failEl(proj, st));
  } else if (busy) {
    fields.appendChild(buildingEl(st));
  } else {
    // ── Editable controls (default, pre-build) ──
    const row = document.createElement("div");
    row.className = "card-row";

    const profWrap = document.createElement("label");
    profWrap.className = "field";
    profWrap.innerHTML = `<span class="field-label">Colour profile</span>`;
    const prof = document.createElement("select");
    prof.className = "select";
    State.profiles.forEach((p) => prof.add(new Option(p.name, p.name)));
    prof.value = proj.profile && State.profiles.some((p) => p.name === proj.profile)
      ? proj.profile : State.settings.active_profile;
    proj.profile = prof.value;
    prof.onchange = () => { proj.profile = prof.value; };
    profWrap.appendChild(prof);

    const bpmWrap = document.createElement("label");
    bpmWrap.className = "field bpm-field";
    bpmWrap.innerHTML = `<span class="field-label">BPM (blank = auto)</span>`;
    const bpm = document.createElement("input");
    bpm.className = "input";
    bpm.type = "text";
    bpm.placeholder = "auto";
    bpm.value = proj.bpm;
    bpm.oninput = () => { proj.bpm = bpm.value.trim(); };
    bpmWrap.appendChild(bpm);

    row.append(profWrap, bpmWrap);
    fields.append(row);
  }

  // side — remove button (top) + action lights (bottom)
  const side = document.createElement("div");
  side.className = "card-side";
  const rm = document.createElement("button");
  rm.className = "remove-btn";
  rm.textContent = "✕";
  rm.title = busy ? "Building…" : "Remove project";
  rm.disabled = !!busy;
  rm.onclick = () => { if (!busy) removeProject(proj.id); };
  side.appendChild(rm);

  side.appendChild(actionLights(proj, st));

  card.append(dz, fields, side);
  return card;
}

/* Live "building" state shown in the fields column while a card is mid-build. */
function buildingEl(st) {
  const el = document.createElement("div");
  el.className = "card-build";
  el.innerHTML = st && st.state === "running"
    ? `<div class="cb-line"><div class="spinner"></div><span class="cb-msg">${escapeHtml(st.message || "Building…")}</span></div>`
    : `<div class="cb-line"><span class="chip pending">pending</span><span class="cb-msg">${escapeHtml((st && st.message) || "Queued…")}</span></div>`;
  return el;
}

/* Failed state shown inline, with an expandable trace. */
function failEl(proj, st) {
  const el = document.createElement("div");
  el.className = "card-build fail";
  const trId = "tr" + proj.id;
  el.innerHTML =
    `<div class="cb-line"><span class="chip failed">failed</span>
       <span class="cb-msg">${escapeHtml(st.message || "Build failed")}</span></div>` +
    (st.trace ? `<pre class="pi-trace hidden" id="${trId}">${escapeHtml(st.trace)}</pre>` : "");
  if (st.trace) {
    const t = document.createElement("button");
    t.className = "btn tiny cb-trace";
    t.textContent = "Show details";
    t.onclick = () => { const pre = $(trId); if (pre) pre.classList.toggle("hidden"); };
    el.querySelector(".cb-line").appendChild(t);
  }
  return el;
}

/* "Open in Ableton" / "Reveal folder" action lights + a Build-again reset.
   Dim/disabled before & during a build; light up (accent .prime) once done. */
function actionLights(proj, st) {
  const wrap = document.createElement("div");
  wrap.className = "card-lights";
  const ready = st && (st.state === "done" || st.state === "warn");
  const finished = st && (st.state === "done" || st.state === "warn" || st.state === "failed");

  const open = document.createElement("button");
  open.className = "btn tiny light" + (ready && st.als ? " prime" : "");
  open.textContent = "Open in Ableton";
  open.disabled = !(ready && st.als);
  open.onclick = () => openProjectAls(st && st.als);

  const reveal = document.createElement("button");
  reveal.className = "btn tiny light";
  reveal.textContent = "Reveal folder";
  reveal.disabled = !(finished && st.folder);
  reveal.onclick = () => revealFolder(st && st.folder);

  wrap.append(open, reveal);

  if (finished) {
    const again = document.createElement("button");
    again.className = "btn tiny cb-reset";
    again.textContent = "↺ Build again";
    again.title = "Clear this result and re-queue the project";
    again.onclick = () => resetCard(proj.id);
    wrap.appendChild(again);
  }
  return wrap;
}

function shortPaths(paths) {
  const names = paths.map((p) => p.replace(/[\\/]+$/, "").split(/[\\/]/).pop());
  return names.length <= 2 ? names.join(", ") : names.slice(0, 2).join(", ") + ` +${names.length - 2}`;
}

async function choosePaths(id) {
  const a = api();
  const proj = State.projects.find((p) => p.id === id);
  if (!a) { toast("Folder picking works in the app window.", "warn"); return; }
  // Default to a folder pick (most packs are a folder); fall back to files.
  const r = await a.pick_paths("folder");
  if (r && r.ok && r.paths.length) {
    proj.paths = r.paths;
  } else {
    const rf = await a.pick_paths("files");
    if (rf && rf.ok && rf.paths.length) proj.paths = rf.paths;
  }
  await maybeAutoTitle(proj);
  renderQueue();
}

/* OS drag-drop.
   Real filesystem paths are delivered by the Python side (see app.py
   _wire_native_drop): a document-level pywebview drop handler reads each file's
   pywebviewFullPath and calls window.__wmReceiveDrop(paths). Because that fires
   on `document`, we track which card the pointer is over so the paths land on
   the right one. The JS `drop` listener here is kept only for the visual
   highlight and as a fallback for backends that expose File.path directly (or
   the plain-browser preview, where we fall back to the picker). */
let __wmActiveDropCard = null;

function wireDrop(dz, id) {
  dz.addEventListener("dragenter", (e) => { e.preventDefault(); __wmActiveDropCard = id; dz.classList.add("drag"); });
  dz.addEventListener("dragover", (e) => { e.preventDefault(); __wmActiveDropCard = id; dz.classList.add("drag"); });
  dz.addEventListener("dragleave", (e) => {
    // Only clear when actually leaving the dropzone (not entering a child).
    if (!dz.contains(e.relatedTarget)) dz.classList.remove("drag");
  });
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("drag");
    __wmActiveDropCard = id;
    // If the OS exposed real paths on the File objects, use them directly.
    // (WebView2/Chromium blanks File.path, so this is usually empty and the
    // Python bridge — __wmReceiveDrop — does the real work instead.)
    const paths = [];
    for (const f of e.dataTransfer.files) {
      if (f.path) paths.push(f.path);
    }
    if (paths.length) {
      applyDroppedPaths(id, paths);
    } else if (!api()) {
      // Plain-browser preview with no native bridge — fall back to the picker.
      choosePaths(id);
    }
    // Otherwise: running in the app window — the Python drop handler will call
    // window.__wmReceiveDrop() with the real paths in a moment.
  });
}

/* Assign dropped paths to a project card via the same model the picker uses. */
async function applyDroppedPaths(id, paths) {
  const proj = State.projects.find((p) => p.id === id);
  if (!proj || !paths || !paths.length) return;
  proj.paths = paths;
  clearDragHighlights();
  renderQueue();
  await maybeAutoTitle(proj);
  renderQueue();
}

function clearDragHighlights() {
  document.querySelectorAll(".dropzone.drag").forEach((el) => el.classList.remove("drag"));
}

/* Called from Python (app.py) with the real OS paths of dropped files/folders.
   Routes them to whichever card the pointer was last over. */
window.__wmReceiveDrop = function (paths) {
  const id = __wmActiveDropCard;
  clearDragHighlights();
  if (id == null) return;
  applyDroppedPaths(id, Array.isArray(paths) ? paths : [paths]);
  __wmActiveDropCard = null;
};

function updateSummary() {
  const s = $("summary");
  const go = $("goBtn");
  if (State.batchRunning) {
    const active = State.projects.filter(
      (p) => p.status && (p.status.state === "running" || p.status.state === "pending")).length;
    s.innerHTML = `<b>${active}</b> building… <span class="mono">leave it running ☕</span>`;
    go.disabled = true;
    return;
  }
  // Buildable = has stems + a title and isn't already showing a result.
  const ready = State.projects.filter((p) => p.paths.length && p.title.trim() && !p.status);
  const doneCount = State.projects.filter((p) => p.status &&
    (p.status.state === "done" || p.status.state === "warn")).length;
  if (ready.length === 0) {
    s.innerHTML = doneCount
      ? `<b>${doneCount}</b> built — reset a card to build again`
      : "No projects ready — drop stems and add a title";
  } else {
    s.innerHTML = `<b>${ready.length}</b> project${ready.length > 1 ? "s" : ""} ready to build`;
  }
  go.disabled = ready.length === 0;
}

/* ---- colours modal ---- */
function openColours() {
  const name = State.settings.active_profile;
  loadEditProfile(name);
  const sel = $("editProfileSelect");
  sel.innerHTML = "";
  State.profiles.forEach((p) => sel.add(new Option(p.name, p.name)));
  sel.value = name;
  sel.onchange = () => loadEditProfile(sel.value);
  $("coloursModal").classList.remove("hidden");
}

function loadEditProfile(name) {
  const p = State.profiles.find((x) => x.name === name) || State.profiles[0];
  State.editProfile = JSON.parse(JSON.stringify(p));
  $("profileNameInput").value = State.editProfile.name;
  renderColourRows();
}

function renderColourRows() {
  const wrap = $("colourRows");
  wrap.innerHTML = "";
  State.colorCategories.forEach((cat) => {
    const row = document.createElement("div");
    row.className = "colour-row";
    const label = document.createElement("div");
    label.className = "cat-name";
    label.textContent = cat;
    const grid = document.createElement("div");
    grid.className = "swatches";
    State.palette.forEach((hex, idx) => {
      const sw = document.createElement("div");
      sw.className = "swatch" + (State.editProfile.colors[cat] === idx ? " sel" : "");
      sw.style.background = hex;
      sw.title = `index ${idx}`;
      sw.onclick = () => {
        State.editProfile.colors[cat] = idx;
        renderColourRows();
      };
      grid.appendChild(sw);
    });
    row.append(label, grid);
    wrap.appendChild(row);
  });
}

async function saveProfile() {
  const a = api();
  State.editProfile.name = $("profileNameInput").value.trim() || "Profile";
  if (a) {
    const r = await a.save_profile(State.editProfile);
    if (r && r.ok) State.profiles = r.profiles;
  } else {
    const i = State.profiles.findIndex((p) => p.name === State.editProfile.name);
    if (i >= 0) State.profiles[i] = State.editProfile; else State.profiles.push(State.editProfile);
  }
  State.settings.active_profile = State.editProfile.name;
  const a2 = api(); if (a2) await a2.set_setting("active_profile", State.editProfile.name);
  $("coloursModal").classList.add("hidden");
  hydrateTopbar();
  renderQueue();
  renderPreview();
}

function newProfile() {
  State.editProfile = { name: "New profile", colors: {} };
  $("profileNameInput").value = State.editProfile.name;
  renderColourRows();
}

async function deleteProfile() {
  const a = api();
  const name = State.editProfile.name;
  if (a) {
    const r = await a.delete_profile(name);
    if (r && r.ok) State.profiles = r.profiles;
  } else {
    State.profiles = State.profiles.filter((p) => p.name !== name);
    if (!State.profiles.length) State.profiles.push({ name: "Default", colors: {} });
  }
  State.settings.active_profile = State.profiles[0].name;
  $("coloursModal").classList.add("hidden");
  hydrateTopbar();
  renderQueue();
  renderPreview();
}

/* ---- batch build ---- */
async function runBatch() {
  const a = api();
  // Only cards that are ready AND not already showing a result get re-built.
  const ready = State.projects.filter(
    (p) => p.paths.length && p.title.trim() && !p.status);
  if (!ready.length) return;
  const payload = ready.map((p) => ({
    paths: p.paths, title: p.title.trim(), profile: p.profile, bpm: p.bpm || null,
  }));
  if (!a) { toast("Building runs in the app window.", "warn"); return; }

  // run_batch consumes the READY projects in THIS order; remember it so the
  // polled status[i] maps straight back onto buildOrder[i]. Seed each card as
  // pending immediately so the UI reacts before the first poll lands.
  State.buildOrder = ready;
  ready.forEach((p) => { p.status = { state: "pending", message: "Queued…" }; });
  State.batchRunning = true;
  renderQueue();

  const r = await a.run_batch(payload);
  if (r && !r.ok) {
    State.batchRunning = false;
    State.buildOrder = null;
    ready.forEach((p) => { p.status = null; });
    renderQueue();
    toast(r.error || "Couldn't start the batch.", "bad");
    return;
  }
  pollStatus();
}

function pollStatus() {
  const a = api();
  clearInterval(State.polling);
  State.polling = setInterval(async () => {
    const s = await a.get_status();
    applyStatusToCards(s.projects);
    if (!s.running) {
      clearInterval(State.polling);
      State.batchRunning = false;
      renderQueue();
      const done = s.projects.filter((p) => p.state === "done").length;
      const failed = s.projects.filter((p) => p.state === "failed").length;
      const warn = s.projects.filter((p) => p.state === "warn").length;
      toast(`Finished — ${done} built`
        + (warn ? `, ${warn} to check` : "")
        + (failed ? `, ${failed} failed` : "") + ".",
        failed ? "bad" : warn ? "warn" : "good");
    }
  }, 700);
}

/* Map the polled status array back onto the queue cards by build order, then
   re-render so each card shows its own live state / result inline. */
function applyStatusToCards(statusList) {
  const order = State.buildOrder || [];
  statusList.forEach((st, i) => { if (order[i]) order[i].status = st; });
  renderQueue();
}

/* Engine category -> a swatch colour from the active profile (kick rides drums,
   reference is the fixed red). */
function catColorFor(cat) {
  return activeProfileColor({ kick: "drums", reference: "ref" }[cat] || cat);
}

/* The build Result Card body — the payoff, drawn from Session Report.json.
   Rendered inline inside the project card (in place of the profile+BPM row). */
function resultBody(r) {
  const cats = r.categories || {};
  const catRow = Object.keys(cats).map((c) =>
    `<span class="rc-cat"><span class="rc-dot" style="background:${catColorFor(c)}"></span>${escapeHtml(c.toUpperCase())} ${cats[c]}</span>`).join("");
  const groups = (r.groups || []).map((g) =>
    g.subgroups && g.subgroups.length
      ? `${escapeHtml(g.name)} <span class="rc-sub">› ${escapeHtml(g.subgroups.join(", "))}</span>`
      : escapeHtml(g.name)).join(" &nbsp;·&nbsp; ");
  const pills = [];
  if (r.bpm != null) {
    const conf = r.bpm_source ? `${r.bpm_inliers}/${r.bpm_onsets} on grid` : "manual";
    pills.push(`<span class="rc-pill">${Math.round(r.bpm)} BPM · ${conf}</span>`);
  }
  pills.push(`<span class="rc-pill">${r.tracks_total} tracks</span>`);
  if (r.multiversion && r.versions) pills.push(`<span class="rc-pill">${r.versions.length} versions</span>`);
  // New engine report fields — render only when non-empty.
  if (r.updated_stems && r.updated_stems.length)
    pills.push(`<span class="rc-pill amber">${r.updated_stems.length} updated (${escapeHtml(r.updated_stems.join(", "))})</span>`);
  if (r.refcompare && r.refcompare.length)
    pills.push(`<span class="rc-pill">${r.refcompare.length} ref track${r.refcompare.length > 1 ? "s" : ""}</span>`);
  if (r.buses && r.buses.length) pills.push(`<span class="rc-pill amber">${r.buses.length} bus parked</span>`);
  if (r.dry_parked && r.dry_parked.length) pills.push(`<span class="rc-pill amber">${r.dry_parked.length} dry parked</span>`);
  if (r.silent && r.silent.length) pills.push(`<span class="rc-pill amber">${r.silent.length} silent</span>`);
  if (r.skipped && r.skipped.length) pills.push(`<span class="rc-pill amber">${r.skipped.length} skipped</span>`);
  if (r.flat_ref_peak != null) pills.push(`<span class="rc-pill">ref peak ${r.flat_ref_peak}</span>`);
  const flags = r.flags || [];
  const flagsBlock = flags.length
    ? `<div class="rc-flags">
         <div class="rc-flags-head"><span class="rc-flags-icon">!</span> Needs a look before you open it</div>
         ${flags.map((f) => `<div class="rc-flag">${escapeHtml(f)}</div>`).join("")}
       </div>`
    : "";
  return `<div class="rc${flags.length ? " has-flags" : ""}">
     ${flagsBlock}
     <div class="rc-pills">${pills.join("")}</div>
     <div class="rc-cats">${catRow}</div>
     ${groups ? `<div class="rc-groups"><span class="rc-lab">Groups</span> ${groups}</div>` : ""}
   </div>`;
}

/* Wrap resultBody() as a DOM node for appending into the card. */
function resultEl(report) {
  const el = document.createElement("div");
  el.innerHTML = resultBody(report);
  return el.firstElementChild;
}

async function openProjectAls(als) {
  if (!als) return;
  const a = api();
  if (!a) { toast("That works in the app window.", "warn"); return; }
  const r = await a.open_project(als);
  if (!r || !r.ok) toast("Couldn't open: " + ((r && r.error) || "unknown"), "bad");
}

async function revealFolder(folder) {
  if (!folder) return;
  const a = api();
  if (!a) { toast("That works in the app window.", "warn"); return; }
  const r = await a.reveal_folder(folder);
  if (!r || !r.ok) toast("Couldn't open folder: " + ((r && r.error) || "unknown"), "bad");
}

/* Clear a finished/failed card back to an editable, buildable state. */
function resetCard(id) {
  const proj = State.projects.find((p) => p.id === id);
  if (!proj) return;
  proj.status = null;
  renderQueue();
}

/* Calm inline toast — replaces blocking alert()s (a raw popup in front of a
   label looks broken). kind: '' | 'good' | 'warn' | 'bad'. */
function toast(msg, kind) {
  let host = $("toastHost");
  if (!host) {
    host = document.createElement("div");
    host.id = "toastHost";
    host.className = "toast-host";
    document.body.appendChild(host);
  }
  const t = document.createElement("div");
  t.className = "toast" + (kind ? " " + kind : "");
  t.textContent = msg;
  host.appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 300); }, 3800);
}

/* Pre-fill a card's title from the dropped folder/zip name (engine guesses it).
   Never overwrites something the user already typed. */
async function maybeAutoTitle(proj) {
  if (proj.title && proj.title.trim()) return;
  const a = api();
  if (!a) return;
  try {
    const r = await a.suggest_title(proj.paths);
    if (r && r.ok && r.title && !(proj.title && proj.title.trim())) {
      proj.title = r.title;
    }
  } catch (e) { /* auto-title is a nicety — never block ingest */ }
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
