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
    renderQueue(); // refresh per-card default profile
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

/* ---- session preview (decorative colour-language legend) ----
   A tasteful static showcase of the session the app builds: colour-coded lanes
   with tiny faux-waveforms, groups + nested sub-groups. Reacts to the Vox/Drums/
   Music sub-group toggles so the tree visibly changes. No backend — pure legend. */
const PREVIEW_LANES = [
  { name: "Kick",     color: "var(--cat-drums)",  seed: 7  },
  { name: "Drums",    color: "var(--cat-drums)",  seed: 3,  grp: "GRP", cat: "drums",
    subs: [ { name: "Kit",  seed: 11 }, { name: "Perc", seed: 5 } ] },
  { name: "Bass",     color: "var(--cat-bass)",   seed: 9  },
  { name: "Music",    color: "var(--cat-music)",  seed: 4,  grp: "GRP", cat: "music",
    subs: [ { name: "Synth", seed: 6 }, { name: "Keys", seed: 13 } ] },
  { name: "Vox",      color: "var(--cat-vocals)", seed: 8,  grp: "GRP", cat: "vocals",
    subs: [ { name: "Lauren", seed: 2 }, { name: "Sarah", seed: 15 } ] },
  { name: "FX",       color: "var(--cat-fx)",     seed: 12 },
  { name: "Flat Ref", color: "var(--cat-ref)",    seed: 10 },
];

/* Deterministic faux-waveform bars (stable per lane, no RNG churn on re-render). */
function waveBars(seed, count) {
  let out = "";
  let x = (seed * 9301 + 49297) % 233280;
  for (let i = 0; i < count; i++) {
    x = (x * 9301 + 49297) % 233280;
    const h = 3 + Math.round((x / 233280) * 15); // 3..18px
    out += `<i style="height:${h}px"></i>`;
  }
  return out;
}

function laneEl({ name, color, seed, grp, arrow }) {
  const el = document.createElement("div");
  el.className = "lane" + (arrow ? " sub" : "");
  el.style.color = color;
  el.innerHTML =
    `<span class="tag" style="background:${color}"></span>` +
    `<span class="lane-name">${arrow ? '<span class="arrow">↳</span>' : ""}${escapeHtml(name)}</span>` +
    (grp ? `<span class="grp">${grp}</span>` : "") +
    `<span class="wave">${waveBars(seed, 26)}</span>`;
  return el;
}

function renderPreview() {
  const host = $("previewLanes");
  if (!host) return;
  host.innerHTML = "";
  const enabled = State.settings.subgroups || [];
  PREVIEW_LANES.forEach((lane) => {
    host.appendChild(laneEl(lane));
    if (lane.subs && lane.cat && enabled.includes(lane.cat)) {
      lane.subs.forEach((s) =>
        host.appendChild(laneEl({ name: s.name, color: lane.color, seed: s.seed, arrow: true })));
    }
  });
}

function wireGlobalButtons() {
  $("addProjectBtn").onclick = addProject;
  $("coloursBtn").onclick = openColours;
  $("updateBtn").onclick = checkForUpdate;
  $("closeColours").onclick = () => $("coloursModal").classList.add("hidden");
  $("changeFolderBtn").onclick = changeFolder;
  $("goBtn").onclick = runBatch;
  $("saveProfileBtn").onclick = saveProfile;
  $("newProfileBtn").onclick = newProfile;
  $("deleteProfileBtn").onclick = deleteProfile;
  $("closeProgress").onclick = () => $("progressOverlay").classList.add("hidden");
}

async function checkForUpdate() {
  const a = api();
  if (!a) { alert("Updates run in the app window."); return; }
  const btn = $("updateBtn");
  const old = btn.textContent;
  btn.textContent = "⟳ Checking…"; btn.disabled = true;
  try {
    const r = await a.update_app();
    if (!r.ok) {
      alert("Update: " + (r.error || "failed"));
    } else if (r.needsApply) {
      // Packaged app: a newer EXE is available — confirm, then self-swap.
      const msg = "Version " + r.latest + " is available (you have v" + r.version + ")."
        + (r.notes ? "\n\n" + r.notes : "") + "\n\nDownload and install now? The app will relaunch.";
      if (confirm(msg)) {
        btn.textContent = "⟳ Installing…";
        const ar = await a.apply_update(r.download_url);
        if (!ar.ok) alert("Install failed: " + (ar.error || "unknown"));
        else alert("Downloading and installing v" + r.latest + ".\nThe app will close and reopen.");
      }
    } else if (r.changed) {
      // Dev/source checkout: git pull happened.
      alert("Updated to v" + r.version + ".\nClose and relaunch to apply.");
    } else {
      alert("You're already on the latest version (v" + (r.version || State.version) + ").");
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
  const card = document.createElement("div");
  card.className = "card";

  // dropzone
  const dz = document.createElement("div");
  dz.className = "dropzone" + (proj.paths.length ? " filled" : "");
  dz.innerHTML = proj.paths.length
    ? `<div class="dz-icon">✓</div>
       <div class="dz-main">${proj.paths.length} item${proj.paths.length > 1 ? "s" : ""} ready</div>
       <div class="dz-sub">${shortPaths(proj.paths)}</div>
       <div class="dz-sub">click to change</div>`
    : `<div class="dz-icon">⬇</div>
       <div class="dz-main">Drop stems here</div>
       <div class="dz-sub">folder, WAV / AIFF, or .zip — click to browse</div>`;
  dz.onclick = () => choosePaths(proj.id);
  wireDrop(dz, proj.id);

  // fields
  const fields = document.createElement("div");
  fields.className = "card-fields";
  const title = document.createElement("input");
  title.className = "input title";
  title.type = "text";
  title.placeholder = "Artist - Title [Label]";
  title.value = proj.title;
  title.oninput = () => { proj.title = title.value; updateSummary(); };

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
  fields.append(title, row);

  // side
  const side = document.createElement("div");
  side.className = "card-side";
  const rm = document.createElement("button");
  rm.className = "remove-btn";
  rm.textContent = "✕";
  rm.title = "Remove project";
  rm.onclick = () => removeProject(proj.id);
  side.appendChild(rm);

  card.append(dz, fields, side);
  return card;
}

function shortPaths(paths) {
  const names = paths.map((p) => p.replace(/[\\/]+$/, "").split(/[\\/]/).pop());
  return names.length <= 2 ? names.join(", ") : names.slice(0, 2).join(", ") + ` +${names.length - 2}`;
}

async function choosePaths(id) {
  const a = api();
  const proj = State.projects.find((p) => p.id === id);
  if (!a) { alert("Folder picking works in the app window."); return; }
  // Default to a folder pick (most packs are a folder); fall back to files.
  const r = await a.pick_paths("folder");
  if (r && r.ok && r.paths.length) {
    proj.paths = r.paths;
  } else {
    const rf = await a.pick_paths("files");
    if (rf && rf.ok && rf.paths.length) proj.paths = rf.paths;
  }
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
function applyDroppedPaths(id, paths) {
  const proj = State.projects.find((p) => p.id === id);
  if (!proj || !paths || !paths.length) return;
  proj.paths = paths;
  clearDragHighlights();
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
  const ready = State.projects.filter((p) => p.paths.length && p.title.trim());
  const s = $("summary");
  if (ready.length === 0) {
    s.innerHTML = "No projects ready — drop stems and add a title";
  } else {
    s.innerHTML = `<b>${ready.length}</b> project${ready.length > 1 ? "s" : ""} ready to build`;
  }
  $("goBtn").disabled = ready.length === 0;
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
}

/* ---- batch build ---- */
async function runBatch() {
  const a = api();
  const ready = State.projects.filter((p) => p.paths.length && p.title.trim());
  if (!ready.length) return;
  const payload = ready.map((p) => ({
    paths: p.paths, title: p.title.trim(), profile: p.profile, bpm: p.bpm || null,
  }));
  if (!a) { alert("Building runs in the app window."); return; }

  $("progressOverlay").classList.remove("hidden");
  $("closeProgress").classList.add("hidden");
  $("progressNote").textContent = "Working… you can leave this running. ☕";
  const r = await a.run_batch(payload);
  if (r && !r.ok) { $("progressNote").textContent = r.error; return; }
  pollStatus();
}

function pollStatus() {
  const a = api();
  clearInterval(State.polling);
  State.polling = setInterval(async () => {
    const s = await a.get_status();
    renderProgress(s.projects);
    if (!s.running) {
      clearInterval(State.polling);
      const done = s.projects.filter((p) => p.state === "done").length;
      const failed = s.projects.filter((p) => p.state === "failed").length;
      const warn = s.projects.filter((p) => p.state === "warn").length;
      $("progressNote").textContent =
        `Finished — ${done} built` + (warn ? `, ${warn} to check` : "") + (failed ? `, ${failed} failed` : "") + ". Open your output folder.";
      $("closeProgress").classList.remove("hidden");
    }
  }, 700);
}

function renderProgress(projects) {
  const list = $("progressList");
  list.innerHTML = "";
  projects.forEach((p) => {
    const item = document.createElement("div");
    item.className = "progress-item";
    const left = p.state === "running"
      ? `<div class="spinner"></div>`
      : `<span class="chip ${p.state}">${p.state}</span>`;
    item.innerHTML = `${left}
      <div class="pi-title">${escapeHtml(p.title)}</div>
      <div class="pi-msg">${escapeHtml(p.message || "")}</div>`;
    list.appendChild(item);
  });
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
