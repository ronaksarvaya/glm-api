/* ============================================================
   OCR REVIEW DASHBOARD
   Local only. No external services.
   ============================================================ */

const STORAGE_KEY = "ocr-review-session";

const state = {
  images: [],
  results: {},      // filename -> ocr result from backend
  values: {},       // filename -> { field: reviewValue }
  flags: {},        // filename -> { field: "added" | "modified" | null }
  reviewed: {},     // filename -> bool
  selected: null,
  zoom: 1,
  fitScale: 1,
  processing: false,
  processingFiles: {}
};

/* ---------------------------------------------------------
   HELPERS
--------------------------------------------------------- */

const $ = id => document.getElementById(id);

function labelFor(key) {
  return String(key)
    .replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase());
}

function isTextInput(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

let toastTimer = null;

function toast(message, kind) {
  const el = $("toast");
  el.textContent = message;
  el.className = "toast" + (kind ? " " + kind : "");
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

/* ---------------------------------------------------------
   PERSISTENCE
--------------------------------------------------------- */

function saveState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      results: state.results,
      values: state.values,
      flags: state.flags,
      reviewed: state.reviewed,
      selected: state.selected,
      createdAt: state.createdAt || (state.createdAt = new Date().toISOString())
    }));
  } catch (e) {
    console.warn("Autosave failed", e);
  }
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    const saved = JSON.parse(raw);
    if (!saved || !saved.results || !Object.keys(saved.results).length) return false;
    state.results = saved.results || {};
    state.values = saved.values || {};
    state.flags = saved.flags || {};
    state.reviewed = saved.reviewed || {};
    state.createdAt = saved.createdAt;
    state.selected = saved.selected || null;
    return true;
  } catch (e) {
    return false;
  }
}

function resetReview() {
  if (!confirm("Discard all corrections and reviewed marks in this browser?")) return;
  localStorage.removeItem(STORAGE_KEY);
  state.results = {};
  state.values = {};
  state.flags = {};
  state.reviewed = {};
  state.selected = null;
  state.createdAt = null;
  renderAll();
  toast("Review reset", "ok");
}

/* ---------------------------------------------------------
   DATA HELPERS
--------------------------------------------------------- */

function resultFor(name) {
  return state.results[name] || null;
}

function docFields(name) {
  const res = resultFor(name);
  const ocr = (res && res.fields) || {};
  const custom = state.values[name] || {};
  return Object.assign({}, ocr, custom);
}

function ocrFields(name) {
  const res = resultFor(name);
  return (res && res.fields) || {};
}

function reviewValue(name, field) {
  const store = state.values[name] || {};
  if (Object.prototype.hasOwnProperty.call(store, field)) return store[field];
  const ocr = ocrFields(name);
  return ocr[field] == null ? "" : ocr[field];
}

function isFieldModified(name, field) {
  const flag = (state.flags[name] || {})[field];
  if (flag === "added") return true;
  const ocr = ocrFields(name);
  const original = ocr[field] == null ? "" : ocr[field];
  return reviewValue(name, field) !== original;
}

function setFieldValue(name, field, value) {
  const ocr = ocrFields(name);
  const original = ocr[field] == null ? "" : ocr[field];
  const store = state.values[name] || (state.values[name] = {});
  const flags = state.flags[name] || (state.flags[name] = {});

  if (value === original) {
    delete store[field];
    delete flags[field];
  } else {
    store[field] = value;
    if (Object.prototype.hasOwnProperty.call(ocr, field)) {
      flags[field] = "modified";
    } else {
      flags[field] = "added";
    }
  }

  saveState();
}

function hasEdits(name) {
  const res = resultFor(name);
  if (res && res.status === "error") return false;
  return Object.keys(docFields(name)).some(f => isFieldModified(name, f));
}

/* ---------------------------------------------------------
   LOAD IMAGE LIST
--------------------------------------------------------- */

async function loadImages() {
  try {
    const res = await fetch("/api/images");
    const data = await res.json();
    state.images = data.images || [];
  } catch (e) {
    state.images = [];
  }

  $("doc-count").textContent =
    state.images.length + (state.images.length === 1 ? " image found" : " images found");
}

/* ---------------------------------------------------------
   PROCESS ALL (streamed NDJSON)
--------------------------------------------------------- */

async function processAll() {
  if (state.processing) return;
  state.processing = true;
  $("btn-process").disabled = true;
  $("btn-reprocess").disabled = true;

  // Fresh OCR run: clear previous values, keep nothing stale.
  state.results = {};
  state.values = {};
  state.flags = {};

  $("progress-strip").hidden = false;
  $("progress-fill").className = "progress-fill";
  setProgress(0, "Starting...");
  renderAll();

  try {
    const response = await fetch("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stream: true })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let total = 0;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.trim()) continue;
        const msg = JSON.parse(line);

        if (msg.type === "item") {
          total = msg.total;
          state.results[msg.result.filename] = msg.result;
          setProgress(
            msg.processed / total,
            "Processing " + msg.processed + "/" + total
          );
          renderList();
        } else if (msg.type === "end") {
          total = msg.total;
          const failed = msg.results.filter(r => r.status === "error").length;
          $("progress-fill").className = "progress-fill done";
          setProgress(1, "Complete - " + msg.total + " processed, " + failed + " failed");
          toast("Processed " + msg.total + " documents", "ok");
        }
      }
    }

    state.selected = state.selected || (state.images[0] && state.images[0].filename);
    saveState();
  } catch (e) {
    setProgress(0, "Processing failed");
    toast("Batch processing failed: " + e.message, "err");
  }

  state.processing = false;
  renderAll();
  $("btn-process").disabled = false;
  $("btn-reprocess").disabled = state.images.length === 0;
}

function setProgress(ratio, label) {
  $("progress-fill").style.width = Math.max(0, Math.min(1, ratio)) * 100 + "%";
  $("progress-label").textContent = label;
}

/* ---------------------------------------------------------
   PROCESS SINGLE
--------------------------------------------------------- */

async function processSingle(filename) {
  if (state.processing || state.processingFiles[filename]) return;
  
  state.processingFiles[filename] = true;
  renderList();
  
  try {
    const response = await fetch("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stream: false, filename: filename })
    });
    
    const data = await response.json();
    if (data.success && data.results && data.results.length > 0) {
      const msg = data.results[0];
      state.results[msg.filename] = msg;
      if (msg.status === "success") {
        toast("Processed " + filename, "ok");
      } else {
        toast("Failed to process " + filename + ": " + msg.error, "err");
      }
    } else {
      toast("No result returned for " + filename, "err");
    }
  } catch (e) {
    toast("Processing failed for " + filename + ": " + e.message, "err");
  }
  
  state.processingFiles[filename] = false;
  saveState();
  renderList();
  
  // If the processed image is currently selected, refresh viewer
  if (state.selected === filename) {
    renderViewer();
    renderFields();
  }
}

/* ---------------------------------------------------------
   RENDER: LIST
--------------------------------------------------------- */

function statusInfo(name) {
  if (state.processingFiles[name]) return { code: "prog", text: "⏳ Processing..." };
  const res = resultFor(name);
  if (!res) return { code: "none", text: "Not processed" };
  if (res.status === "error") return { code: "err", text: "✕ Processing failed" };
  if (state.reviewed[name]) return { code: "ok", text: "✓ Reviewed" };
  if (hasEdits(name)) return { code: "prog", text: "● In progress" };
  if (res.status === "success") return { code: "ok", text: "✓ Completed" };
  return { code: "none", text: "○ Not reviewed" };
}

function renderList() {
  const box = $("image-list");
  box.innerHTML = "";

  state.images.forEach(img => {
    const res = resultFor(img.filename);
    const st = statusInfo(img.filename);
    const docType = res ? res.document.type : null;

    const item = document.createElement("div");
    item.className = "list-item" + (state.selected === img.filename ? " selected" : "");

    const thumb = document.createElement("img");
    thumb.className = "list-thumb";
    thumb.src = img.thumbnail_url;
    thumb.alt = "";
    thumb.loading = "lazy";
    item.appendChild(thumb);

    const meta = document.createElement("div");
    meta.className = "list-meta";

    const name = document.createElement("div");
    name.className = "list-name";
    name.textContent = img.filename;
    name.title = img.filename;
    meta.appendChild(name);

    const sub = document.createElement("div");
    sub.className = "list-sub";
    sub.textContent = docType || "not processed";
    meta.appendChild(sub);

    const badge = document.createElement("span");
    badge.className = "badge " + st.code;
    badge.textContent = st.text;
    meta.appendChild(badge);
    
    // Add Process Button
    const actions = document.createElement("div");
    actions.className = "list-actions";
    actions.style.marginTop = "6px";
    
    const procBtn = document.createElement("button");
    procBtn.className = "btn btn-sm";
    
    // Check if currently processing
    if (state.processingFiles[img.filename]) {
      procBtn.textContent = "Processing...";
      procBtn.disabled = true;
    } else {
      // If already processed, show "Reprocess", otherwise "Process"
      procBtn.textContent = res ? "Reprocess" : "Process";
      procBtn.disabled = state.processing; // Disable if batch is running
    }
    
    procBtn.addEventListener("click", (e) => {
      e.stopPropagation(); // prevent selectImage
      processSingle(img.filename);
    });
    
    actions.appendChild(procBtn);
    meta.appendChild(actions);

    item.appendChild(meta);
    item.addEventListener("click", () => selectImage(img.filename));

    box.appendChild(item);
  });
}

/* ---------------------------------------------------------
   RENDER: VIEWER
--------------------------------------------------------- */

function selectImage(name) {
  state.selected = name;
  saveState();
  renderList();
  renderViewer();
  renderFields();
}

function renderViewer() {
  const name = state.selected;
  const stage = $("viewer-stage");
  const empty = $("viewer-empty");

  if (!name) {
    stage.hidden = true;
    empty.hidden = false;
    $("viewer-title").textContent = "No document selected";
    $("raw-text").textContent = "Not processed yet.";
    if ($("clean-text")) $("clean-text").textContent = "Not processed yet.";
    if ($("ocr-metadata")) $("ocr-metadata").hidden = true;
    return;
  }

  const img = state.images.find(i => i.filename === name);
  const res = resultFor(name);

  $("viewer-title").textContent = name;

  empty.hidden = true;
  stage.hidden = false;

  const el = $("viewer-img");
  el.onload = () => { fitImage(); };
  if (el.getAttribute("src") !== img.url) {
    el.setAttribute("src", img.url);
  } else {
    fitImage();
  }

  $("raw-text").textContent = res && res.raw_text
    ? res.raw_text
    : (res && res.error ? "ERROR: " + res.error : "Not processed yet.");

  if ($("clean-text")) {
    $("clean-text").textContent = res && res.clean_text
      ? res.clean_text
      : (res && res.error ? "ERROR: " + res.error : "Not processed yet.");
  }

  if ($("ocr-metadata")) {
    if (res && res.ocr_metadata) {
      $("ocr-metadata").hidden = false;
      let timeStr = res.ocr_metadata.processing_time;
      if (typeof timeStr === 'number') timeStr = timeStr.toFixed(2) + "s";
      $("ocr-metadata").innerHTML = 
        "<strong>OCR Engine:</strong> " + escapeHtml(res.ocr_metadata.engine) + "<br>" +
        "<strong>Model:</strong> " + escapeHtml(res.ocr_metadata.model) + "<br>" +
        "<strong>Processing Time:</strong> " + escapeHtml(timeStr);
    } else {
      $("ocr-metadata").hidden = true;
    }
  }
}

function fitImage() {
  const el = $("viewer-img");
  const body = $("viewer-body");
  if (!el.naturalWidth) return;

  const pad = 28;
  const scale = Math.min(
    (body.clientWidth - pad) / el.naturalWidth,
    (body.clientHeight - pad) / el.naturalHeight,
    1
  );

  state.fitScale = scale || 1;
  applyZoom();
}

function applyZoom() {
  const el = $("viewer-img");
  const scale = state.fitScale * state.zoom;
  el.style.transform = "scale(" + scale + ")";
  $("zoom-reset").textContent = Math.round(scale * 100) + "%";
}

function setZoom(factor) {
  state.zoom = Math.min(8, Math.max(0.1, state.zoom * factor));
  applyZoom();
}

/* ---------------------------------------------------------
   RENDER: FIELDS
--------------------------------------------------------- */

function renderFields() {
  const name = state.selected;
  const box = $("fields");
  box.innerHTML = "";

  const res = resultFor(name);
  const chip = $("doctype-chip");

  if (!name) {
    chip.hidden = true;
    $("field-count").textContent = "";
    $("fields-empty").hidden = true;
    $("btn-reviewed").disabled = true;
    return;
  }

  const docType = res ? res.document.type : "NOT PROCESSED";
  chip.hidden = false;
  chip.textContent = docType;

  if (res && res.status === "error") {
    $("field-count").textContent = "";
    $("fields-empty").hidden = false;
    $("fields-empty").innerHTML =
      "<b>Processing failed.</b><br>" + escapeHtml(res.error || "Unknown error");
    $("btn-reviewed").disabled = true;
    return;
  }

  const fields = docFields(name);
  const keys = Object.keys(fields);

  $("fields-empty").hidden = keys.length > 0;
  $("field-count").textContent = keys.length ? keys.length + " fields" : "";
  $("btn-reviewed").disabled = !res;

  keys.forEach(key => box.appendChild(buildField(name, key)));

  if (keys.length === 0) {
    const note = document.createElement("p");
    note.className = "muted empty-note";
    note.textContent = "No structured fields detected. Add fields manually with + Add Field.";
    box.appendChild(note);
  }

  const isReviewed = !!state.reviewed[name];
  const btn = $("btn-reviewed");
  btn.classList.toggle("is-reviewed", isReviewed);
  btn.textContent = isReviewed ? "✓ Reviewed" : "Mark as Reviewed";
  btn.disabled = !res;
}

function buildField(name, key) {
  const wrap = document.createElement("div");
  const modified = isFieldModified(name, key);
  const ocrRaw = ocrFields(name);
  const isAdded = !Object.prototype.hasOwnProperty.call(ocrRaw, key);

  wrap.className = "field" + (modified ? " modified" : "") + (isAdded ? " added" : "");

  const head = document.createElement("div");
  head.className = "field-head";

  const lab = document.createElement("span");
  lab.className = "field-label";
  lab.textContent = labelFor(key);
  head.appendChild(lab);

  const right = document.createElement("div");
  right.style.display = "flex";
  right.style.alignItems = "center";
  right.style.gap = "6px";

  const st = document.createElement("span");
  let cls = "unchanged";
  let txt = "○ Unchanged";
  if (isAdded) { cls = "added"; txt = "＋ Added"; }
  else if (modified) { cls = "modified"; txt = "● Modified"; }
  else if (ocrRaw[key] == null && reviewValue(name, key) === "") { cls = "missing"; txt = "⚠ Not detected"; }
  st.className = "field-state " + cls;
  st.textContent = txt;
  right.appendChild(st);

  if (isAdded) {
    const rm = document.createElement("button");
    rm.className = "field-remove";
    rm.textContent = "×";
    rm.title = "Remove added field";
    rm.addEventListener("click", () => {
      const store = state.values[name] || {};
      const flags = state.flags[name] || {};
      delete store[key];
      delete flags[key];
      saveState();
      renderFields();
      renderStats();
    });
    right.appendChild(rm);
  }

  head.appendChild(right);
  wrap.appendChild(head);

  const input = document.createElement("input");
  input.type = "text";
  input.value = reviewValue(name, key);
  input.placeholder = "not detected";
  input.addEventListener("input", () => {
    setFieldValue(name, key, input.value);
    renderFieldsSoft(name, key, input.value, wrap);
    renderStats();
    renderList();
  });
  wrap.appendChild(input);

  const ocrLine = document.createElement("div");
  ocrLine.className = "field-ocr";

  const original = ocrRaw[key];
  if (isAdded) {
    ocrLine.innerHTML = "<b>OCR:</b> <span>field added manually</span>";
  } else if (modified) {
    ocrLine.innerHTML =
      "<b>OCR:</b> <span class='was'>" + escapeHtml(original == null ? "Not detected" : original) + "</span>";
  } else {
    ocrLine.innerHTML = "<b>OCR:</b> " + escapeHtml(original == null ? "Not detected" : original);
  }

  wrap.appendChild(ocrLine);
  return wrap;
}

/* Avoid a full re-render on every keystroke: patch in place. */
function renderFieldsSoft(name, key, value, wrap) {
  const ocrRaw = ocrFields(name);
  const isAdded = !Object.prototype.hasOwnProperty.call(ocrRaw, key);
  const modified = value !== (isAdded ? "" : (ocrRaw[key] == null ? "" : ocrRaw[key]));

  wrap.className = "field" + (modified ? " modified" : "") + (isAdded ? " added" : "");

  const st = wrap.querySelector(".field-state");
  if (st) {
    let cls = "unchanged";
    let txt = "○ Unchanged";
    if (isAdded) { cls = "added"; txt = "＋ Added"; }
    else if (modified) { cls = "modified"; txt = "● Modified"; }
    else if (ocrRaw[key] == null && value === "") { cls = "missing"; txt = "⚠ Not detected"; }
    st.className = "field-state " + cls;
    st.textContent = txt;
  }

  const line = wrap.querySelector(".field-ocr");
  if (line) {
    if (isAdded) {
      line.innerHTML = "<b>OCR:</b> <span>field added manually</span>";
    } else if (modified) {
      line.innerHTML = "<b>OCR:</b> <span class='was'>" +
        escapeHtml(ocrRaw[key] == null ? "Not detected" : ocrRaw[key]) + "</span>";
    } else {
      line.innerHTML = "<b>OCR:</b> " +
        escapeHtml(ocrRaw[key] == null ? "Not detected" : ocrRaw[key]);
    }
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/* ---------------------------------------------------------
   ADD FIELD
--------------------------------------------------------- */

function addFieldUI() {
  const name = state.selected;
  if (!name) { toast("Select a document first", "err"); return; }

  const box = $("fields");
  const existing = box.querySelector(".addform");
  if (existing) { existing.remove(); return; }

  const form = document.createElement("div");
  form.className = "addform field";

  const keyInput = document.createElement("input");
  keyInput.placeholder = "field name, e.g. father_name";
  keyInput.className = "addform-key";

  const valInput = document.createElement("input");
  valInput.placeholder = "value";
  valInput.className = "addform-val";

  const row = document.createElement("div");
  row.className = "addform-row";

  const add = document.createElement("button");
  add.className = "btn btn-sm btn-primary";
  add.textContent = "Add";

  const cancel = document.createElement("button");
  cancel.className = "btn btn-sm btn-ghost";
  cancel.textContent = "Cancel";

  row.appendChild(add);
  row.appendChild(cancel);

  form.appendChild(keyInput);
  form.appendChild(valInput);
  form.appendChild(row);
  box.insertBefore(form, box.firstChild);
  keyInput.focus();

  const commit = () => {
    const key = keyInput.value.trim().toLowerCase().replace(/\s+/g, "_");
    if (!key) { toast("Field name required", "err"); return; }
    if (Object.prototype.hasOwnProperty.call(docFields(name), key)) {
      toast("Field already exists", "err");
      return;
    }
    setFieldValue(name, key, valInput.value.trim());
    renderFields();
    renderList();
    renderStats();
    toast("Field added", "ok");
  };

  add.addEventListener("click", commit);
  cancel.addEventListener("click", () => form.remove());
  keyInput.addEventListener("keydown", e => { if (e.key === "Enter") commit(); });
  valInput.addEventListener("keydown", e => { if (e.key === "Enter") commit(); });
}

/* ---------------------------------------------------------
   STATS
--------------------------------------------------------- */

function collectStats() {
  const total = state.images.length;
  let reviewed = 0, unknown = 0, errors = 0, corrected = 0, unchanged = 0, processed = 0;
  const perField = {};

  state.images.forEach(img => {
    const name = img.filename;
    const res = resultFor(name);
    if (!res) return;
    processed++;
    if (res.status === "error") { errors++; return; }
    if (res.document.type === "UNKNOWN") unknown++;
    if (state.reviewed[name]) reviewed++;

    Object.keys(docFields(name)).forEach(key => {
      if (isFieldModified(name, key)) {
        corrected++;
        perField[key] = (perField[key] || 0) + 1;
      } else {
        unchanged++;
      }
    });
  });

  return {
    total, processed, reviewed, unknown, errors, corrected, unchanged, perField
  };
}

function renderStats() {
  const s = collectStats();
  const box = $("stats");
  box.innerHTML = "";

  const add = (value, label, cls) => {
    const d = document.createElement("div");
    d.className = "stat" + (cls ? " " + cls : "");
    d.innerHTML = "<b>" + value + "</b><span>" + label + "</span>";
    box.appendChild(d);
  };

  add(s.total, "Documents");
  add(s.reviewed, "Reviewed", "ok");
  add(s.total - s.reviewed, "Remaining");
  add(s.corrected, "Corrected", "warn");
  add(s.unknown, "Unknown", s.unknown ? "warn" : "");
  if (s.errors) add(s.errors, "Errors", "err");

  $("list-filter").hidden = false;
  $("list-filter").textContent = s.reviewed + "/" + s.total + " done";

  $("navpos").textContent =
    (state.selected ? indexOf(state.selected) + 1 : 0) + " / " + state.images.length;
}

function indexOf(name) {
  return state.images.findIndex(i => i.filename === name);
}

/* ---------------------------------------------------------
   CORRECTION SUMMARY
--------------------------------------------------------- */

let correctionSummaryOpen = false;

function showSummary() {

  const s = collectStats();
  const body = $("summary-body");
  body.innerHTML = "";

  const head = document.createElement("p");
  head.className = "muted";
  head.style.margin = "0 0 12px";
  head.textContent = s.corrected + " correction" + (s.corrected === 1 ? "" : "s") +
    " across " + state.images.length + " documents. " +
    s.unchanged + " field" + (s.unchanged === 1 ? "" : "s") + " unchanged.";
  body.appendChild(head);

  const entries = Object.entries(s.perField).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "No corrections yet.";
    body.appendChild(p);
  } else {
    const max = entries[0][1];
    entries.forEach(([key, count]) => {
      const row = document.createElement("div");
      row.className = "sum-row";
      row.innerHTML = "<span>" + escapeHtml(labelFor(key)) + "</span><span>" + count + "</span>";
      body.appendChild(row);

      const bar = document.createElement("div");
      bar.className = "sum-bar";
      bar.style.width = (count / max) * 100 + "%";
      body.appendChild(bar);
    });
  }

  openSummary();
}

function openSummary() {
  correctionSummaryOpen = true;
  $("summary-modal").hidden = false;
}

function closeSummary() {
  correctionSummaryOpen = false;
  $("summary-modal").hidden = true;
}

function toggleSummary() {
  if (correctionSummaryOpen) closeSummary();
  else showSummary();
}

/* ---------------------------------------------------------
   EXPORT
--------------------------------------------------------- */

function buildExport() {
  const s = collectStats();
  const documents = [];

  state.images.forEach(img => {
    const name = img.filename;
    const res = resultFor(name);

    if (!res) return;

    const ocr = {};
    Object.keys(res.fields || {}).forEach(k => { ocr[k] = res.fields[k]; });

    const reviewed = {};
    const corrections = [];

    Object.keys(docFields(name)).forEach(key => {
      const value = reviewValue(name, key);
      reviewed[key] = value;
      if (isFieldModified(name, key)) {
        const original = Object.prototype.hasOwnProperty.call(res.fields, key)
          ? res.fields[key]
          : null;
        corrections.push({
          field: key,
          ocr_value: original,
          corrected_value: value
        });
      }
    });

    documents.push({
      filename: name,
      document_type: res.document.type,
      status: res.status,
      ocr: ocr,
      reviewed: reviewed,
      corrections: corrections,
      reviewed_flag: !!state.reviewed[name],
      error: res.error || null,
      raw_text: res.raw_text || ""
    });
  });

  return {
    schema_version: "1.0",
    review_session: {
      created_at: state.createdAt || new Date().toISOString(),
      exported_at: new Date().toISOString(),
      total_documents: state.images.length,
      processed_documents: s.processed,
      reviewed_documents: s.reviewed,
      fields_corrected: s.corrected,
      fields_unchanged: s.unchanged,
      unknown_documents: s.unknown,
      error_documents: s.errors
    },
    correction_summary: s.perField,
    documents: documents
  };
}

function exportReview() {
  const data = buildExport();

  if (!data.documents.length) {
    toast("Nothing to export - process images first", "err");
    return;
  }

  const stamp = timestamp();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = "ocr_review_" + stamp + ".json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);

  toast("Exported " + data.documents.length + " documents", "ok");
}

function timestamp() {
  const d = new Date();
  const p = n => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
    "_" + p(d.getHours()) + "-" + p(d.getMinutes()) + "-" + p(d.getSeconds());
}

/* ---------------------------------------------------------
   NAVIGATION
--------------------------------------------------------- */

function go(delta) {
  if (!state.images.length) return;
  let i = indexOf(state.selected);
  if (i < 0) i = 0;
  else i += delta;

  if (i < 0) i = 0;
  if (i >= state.images.length) i = state.images.length - 1;

  selectImage(state.images[i].filename);
}

function toggleReviewed() {
  const name = state.selected;
  if (!name || !resultFor(name)) return;
  state.reviewed[name] = !state.reviewed[name];
  saveState();
  renderList();
  renderFields();
  renderStats();
}

/* ---------------------------------------------------------
   GLOBAL RENDER
--------------------------------------------------------- */

function renderAll() {
  renderList();
  renderViewer();
  renderFields();
  renderStats();

  const hasResults = Object.keys(state.results).length > 0;
  $("btn-export").disabled = !hasResults;
  $("btn-reset").disabled = !hasResults;
  $("btn-prev").disabled = !state.selected || indexOf(state.selected) === 0;
  $("btn-next").disabled = !state.selected || indexOf(state.selected) === state.images.length - 1;
}

/* ---------------------------------------------------------
   EVENTS
--------------------------------------------------------- */

function bind() {
  $("btn-process").addEventListener("click", processAll);
  $("btn-reprocess").addEventListener("click", processAll);
  $("btn-export").addEventListener("click", exportReview);
  $("btn-reset").addEventListener("click", resetReview);
  $("btn-add-field").addEventListener("click", addFieldUI);
  $("btn-reviewed").addEventListener("click", toggleReviewed);
  $("btn-prev").addEventListener("click", () => go(-1));
  $("btn-next").addEventListener("click", () => go(1));

  $("zoom-in").addEventListener("click", () => setZoom(1.25));
  $("zoom-out").addEventListener("click", () => setZoom(0.8));
  $("zoom-reset").addEventListener("click", () => { state.zoom = 1; applyZoom(); });
  $("zoom-fit").addEventListener("click", fitImage);

  $("btn-summary").addEventListener("click", toggleSummary);
  $("summary-close").addEventListener("click", closeSummary);
  $("summary-modal").addEventListener("click", e => {
    if (e.target === $("summary-modal")) closeSummary();
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && correctionSummaryOpen) {
      e.preventDefault();
      closeSummary();
      return;
    }

    if (isTextInput(e.target)) return;

    if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); go(1); }
    else if (e.key === "r" || e.key === "R") { toggleReviewed(); }
    else if (e.key === "s" || e.key === "S") {
      if (e.ctrlKey) { e.preventDefault(); saveState(); toast("Review saved", "ok"); }
    }
  });

  window.addEventListener("resize", () => {
    if ($("viewer-stage").hidden === false) fitImage();
  });

  // Periodic autosave
  setInterval(saveState, 10000);
}

/* ---------------------------------------------------------
   BOOT
--------------------------------------------------------- */

(async function init() {
  bind();
  await loadImages();

  const restored = loadState();
  if (restored) {
    if (state.selected && indexOf(state.selected) < 0) state.selected = null;
    if (!state.selected && state.images.length) {
      state.selected = state.images[0].filename;
    }
    toast("Restored saved review session", "ok");
  } else if (state.images.length) {
    state.selected = state.images[0].filename;
  }

  renderAll();
})();
