"use strict";

const WELCOME_KEY = "onmc_welcome_dismissed_v1";
const WELCOME_FRESH_THRESHOLD = 20;

const state = { data: null, view: "overview", search: "", kind: "" };
const palette = ["#237a50", "#356f91", "#a65e18", "#6b5b95", "#a23d3d", "#55766a"];

const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
const formatKind = (value) => String(value).replaceAll("_", " ");
const formatNumber = (value) => new Intl.NumberFormat().format(Number(value || 0));

async function renderDashboard() {
  setLoading(true);
  try {
    const embedded = byId("onmc-dashboard-data");
    if (embedded) {
      state.data = JSON.parse(embedded.textContent);
      hydrateDashboard();
      setLoading(false);
      return;
    }
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) throw new Error(`Dashboard request failed (${response.status})`);
    state.data = await response.json();
    hydrateDashboard();
    setLoading(false);
  } catch (error) {
    showError(error instanceof Error ? error.message : "Unknown error");
  }
}

function hydrateDashboard() {
  const data = state.data;
  document.title = `${data.repo.name} | ONMC`;
  byId("repo-name").textContent = data.repo.name;
  byId("repo-path").textContent = data.repo.root;
  byId("last-ingest").textContent = `Ingested ${formatDate(data.repo.last_ingest_at)}`;
  renderOverview();
  renderMemoryFilters();
  renderMemories();
  renderTasks();
  renderCodegraphLists();
  renderHealth();
  switchView(state.view);
  renderWelcome();
}

function renderWelcome() {
  const data = state.data;
  const { summary, memory_kinds: kinds, repo } = data;
  const isFresh = summary.memories <= WELCOME_FRESH_THRESHOLD;
  const dismissed = localStorage.getItem(WELCOME_KEY) === "1";

  // Populate stats
  const hotspotCount = data.codegraph.files.filter((file) => file.churn > 0).length;
  const decisionCount = (kinds.find((item) => item.kind === "decision") || {}).count || 0;
  const invariantCount = (kinds.find((item) => item.kind === "invariant") || {}).count || 0;
  byId("welcome-sub").textContent =
    `${escapeHtml(repo.name)} has been indexed. Here's a snapshot of what ONMC knows so far.`;
  byId("welcome-stats").innerHTML = [
    [formatNumber(summary.memories), "memories"],
    [formatNumber(hotspotCount), "hotspots"],
    [formatNumber(decisionCount + invariantCount), "decisions & invariants"],
  ].map(([value, label]) =>
    `<div class="welcome-stat"><strong class="welcome-stat-value">${value}</strong><span class="welcome-stat-label">${escapeHtml(label)}</span></div>`
  ).join("");

  // Show/hide the overlay and re-open affordance
  const shouldShow = !dismissed || isFresh && !dismissed;
  byId("welcome-overlay").hidden = !shouldShow;
  byId("welcome-open").hidden = !dismissed;
}

function dismissWelcome() {
  localStorage.setItem(WELCOME_KEY, "1");
  const overlay = byId("welcome-overlay");
  overlay.style.opacity = "0";
  overlay.style.transition = "opacity .18s ease";
  setTimeout(() => { overlay.hidden = true; }, 200);
  byId("welcome-open").hidden = false;
}

function openWelcome() {
  const overlay = byId("welcome-overlay");
  overlay.style.opacity = "";
  overlay.style.transition = "";
  overlay.hidden = false;
  byId("welcome-open").hidden = true;
}

function renderOverview() {
  const { summary, health, memory_kinds: kinds, tasks, codegraph } = state.data;
  const metrics = [
    ["Memories", summary.memories, `${kinds.length} kinds`],
    ["Indexed files", summary.files, `${codegraph.directories.length} directories`],
    ["Tasks", summary.tasks, `${summary.active_tasks} active`],
    ["Attempts", summary.attempts, "task evidence"],
    ["Artifacts", summary.artifacts, "durable outcomes"],
    ["Readiness", health.errors.length ? health.errors.length : health.warnings.length, health.errors.length ? "errors" : "warnings"],
  ];
  byId("metric-grid").innerHTML = metrics.map(([label, value, detail]) => `
    <div class="metric"><span class="metric-label">${escapeHtml(label)}</span><strong class="metric-value">${formatNumber(value)}</strong><span class="metric-detail">${escapeHtml(detail)}</span></div>
  `).join("");

  const readiness = health.readiness === "ready";
  const chip = byId("readiness-chip");
  chip.className = `status-chip ${readiness ? "ready" : "needs-attention"}`;
  chip.textContent = readiness ? "Ready" : "Needs attention";
  byId("memory-total").textContent = `${summary.memories} records`;
  const maxKind = Math.max(...kinds.map((item) => item.count), 1);
  byId("memory-distribution").innerHTML = kinds.slice(0, 7).map((item, index) => `
    <div class="distribution-row"><span class="distribution-label">${escapeHtml(formatKind(item.kind))}</span><span class="distribution-track"><i class="distribution-fill" style="width:${Math.max(6, item.count / maxKind * 100)}%;background:${palette[index % palette.length]}"></i></span><span class="distribution-count">${item.count}</span></div>
  `).join("");

  const active = tasks.filter((task) => task.status === "active" || task.status === "blocked");
  byId("active-count").textContent = `${active.length} open`;
  byId("active-tasks").innerHTML = active.length ? `<div class="activity-list">${active.slice(0, 4).map((task) => `
    <div class="activity-item"><div class="activity-title">${escapeHtml(task.title)}</div><div class="activity-meta"><span>${escapeHtml(task.status)}</span><span>${task.attempt_count} attempts</span><span>${task.artifact_count} artifacts</span></div></div>
  `).join("")}</div>` : '<div class="empty-state">No active tasks.</div>';

  byId("hot-files-overview").innerHTML = codegraph.files.slice(0, 4).map((file) => `
    <div class="hot-file"><span class="hot-file-path" title="${escapeHtml(file.path)}">${escapeHtml(file.path)}</span><div class="hot-file-meta"><span>churn ${file.churn}</span><span>${formatBytes(file.bytes)}</span></div></div>
  `).join("");
}

function renderMemoryFilters() {
  const select = byId("memory-kind-filter");
  select.innerHTML = '<option value="">All kinds</option>' + state.data.memory_kinds.map((item) => `<option value="${escapeHtml(item.kind)}">${escapeHtml(formatKind(item.kind))} (${item.count})</option>`).join("");
  select.value = state.kind;
}

function renderMemories() {
  const query = state.search.trim().toLowerCase();
  const rows = state.data.memories.filter((memory) => {
    if (state.kind && memory.kind !== state.kind) return false;
    if (!query) return true;
    return [memory.title, memory.summary, memory.source_ref, memory.kind].join(" ").toLowerCase().includes(query);
  });
  byId("memory-visible-count").textContent = `${rows.length} of ${state.data.memories.length}`;
  byId("memory-table-body").innerHTML = rows.map((memory) => `
    <tr><td><span class="kind-badge">${escapeHtml(formatKind(memory.kind))}</span></td><td><span class="memory-title">${escapeHtml(memory.title)}</span><span class="memory-summary">${escapeHtml(memory.summary)}</span></td><td><span>${escapeHtml(memory.source_type)}</span><span class="source-ref" title="${escapeHtml(memory.source_ref)}">${escapeHtml(memory.source_ref)}</span></td><td><span class="confidence"><span class="confidence-bar"><i style="width:${Math.round(memory.confidence * 100)}%"></i></span>${Math.round(memory.confidence * 100)}%</span></td></tr>
  `).join("");
  byId("memory-empty").hidden = rows.length !== 0;
  document.querySelector("#view-memory .table-shell").hidden = rows.length === 0;
}

function renderTasks() {
  const tasks = state.data.tasks;
  byId("task-total").textContent = `${tasks.length} tasks`;
  byId("task-board").innerHTML = tasks.length ? tasks.map((task) => `
    <article class="task-row"><div><span class="task-status ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span></div><div><div class="task-title">${escapeHtml(task.title)}</div><span class="task-description">${escapeHtml(task.description || "No description")}</span></div><div class="task-labels">${(task.labels || []).map((label) => `<span class="task-label">${escapeHtml(label)}</span>`).join("") || '<span class="task-label">unlabelled</span>'}</div><div class="task-counts"><span class="task-count"><strong>${task.attempt_count}</strong>Attempts</span><span class="task-count"><strong>${task.artifact_count}</strong>Artifacts</span><span class="task-count"><strong>${task.output_count}</strong>Outputs</span></div></article>
  `).join("") : '<div class="empty-state">No task records.</div>';
}

function renderCodegraphLists() {
  const graph = state.data.codegraph;
  byId("directory-count").textContent = `${graph.directories.length} total`;
  byId("graph-file-count").textContent = `${graph.files.length} indexed`;
  byId("directory-list").innerHTML = graph.directories.slice(0, 8).map((item, index) => `<div class="rank-row directory-rank-row"><span class="rank-index">${String(index + 1).padStart(2, "0")}</span><span class="rank-name">${escapeHtml(item.path)}</span><span class="rank-meta">${item.files} files · ${item.churn} churn</span></div>`).join("");
  byId("graph-file-list").innerHTML = graph.files.slice(0, 8).map((item) => `<div class="rank-row"><span class="rank-name" title="${escapeHtml(item.path)}">${escapeHtml(item.path)}</span><span class="rank-meta">${item.churn} churn · ${formatBytes(item.bytes)}</span></div>`).join("");
}

function drawCodegraph() {
  if (!state.data || state.view !== "codegraph") return;
  const canvas = byId("codegraph-canvas");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const graph = state.data.codegraph;
  const directories = graph.directories.slice(0, 7);
  const files = graph.files.slice(0, 28);
  if (!directories.length) return;
  const compact = rect.width < 600;
  const padding = 34;
  const usableWidth = Math.max(1, rect.width - padding * 2);
  const columnWidth = usableWidth / directories.length;
  const dirPositions = new Map();
  directories.forEach((directory, index) => {
    dirPositions.set(directory.path, { x: padding + columnWidth * (index + .5), y: 44 });
  });

  ctx.lineWidth = 1;
  files.forEach((file, index) => {
    const parent = dirPositions.get(file.directory) || dirPositions.get(directories[index % directories.length].path);
    const laneIndex = directories.findIndex((item) => item.path === file.directory);
    const lane = laneIndex >= 0 ? laneIndex : index % directories.length;
    const sameLaneIndex = files.slice(0, index).filter((item) => item.directory === file.directory).length;
    const x = padding + columnWidth * (lane + .5) + ((sameLaneIndex % 3) - 1) * Math.min(24, columnWidth * .18);
    const y = 108 + Math.floor(sameLaneIndex / 3) * 62 + (sameLaneIndex % 2) * 12;
    const boundedY = Math.min(rect.height - 28, y);
    ctx.strokeStyle = "rgba(128, 155, 140, .25)";
    ctx.beginPath(); ctx.moveTo(parent.x, parent.y + 10); ctx.lineTo(x, boundedY - 7); ctx.stroke();
    const radius = Math.max(3.5, Math.min(8, 3.5 + file.score / 12));
    ctx.fillStyle = file.is_test ? "#65a9cf" : "#d9f26a";
    ctx.beginPath(); ctx.arc(x, boundedY, radius, 0, Math.PI * 2); ctx.fill();
  });

  directories.forEach((directory, index) => {
    const position = dirPositions.get(directory.path);
    ctx.fillStyle = palette[index % palette.length];
    ctx.beginPath(); ctx.arc(position.x, position.y, 11, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = compact ? "#17231d" : "#eaf1ed";
    ctx.font = `${compact ? "bold 9px" : "10px"} ui-monospace, SFMono-Regular, Menlo, monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(compact ? String(index + 1) : truncate(directory.path, 14), position.x, compact ? position.y + .5 : 72);
  });
}

function renderHealth() {
  const { health, report } = state.data;
  const ready = health.readiness === "ready";
  const summary = byId("health-summary");
  summary.className = `health-summary ${ready ? "" : "attention"}`;
  summary.innerHTML = `<div><strong>${ready ? "Agent-ready" : "Attention required"}</strong><span> ${health.errors.length} errors · ${health.warnings.length} warnings</span></div><span>${state.data.summary.memories} memories · ${state.data.summary.files} files indexed</span>`;
  const entries = Object.entries(health.sections).filter(([, items]) => Array.isArray(items) && items.length);
  byId("health-sections").innerHTML = entries.map(([name, items]) => `<section class="health-section ${name === "warnings" ? "warning" : name === "errors" ? "error" : ""}"><h3>${escapeHtml(name)}</h3><ul class="health-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>`).join("");
  byId("report-content").textContent = report;
}

function switchView(view) {
  state.view = view;
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    const active = panel.dataset.viewPanel === view;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  if (view === "codegraph") requestAnimationFrame(drawCodegraph);
}

function setLoading(loading) {
  byId("loading-state").hidden = !loading;
  byId("error-state").hidden = true;
  byId("dashboard").hidden = loading;
  byId("refresh-button").disabled = loading;
}

function showError(message) {
  byId("loading-state").hidden = true;
  byId("dashboard").hidden = true;
  byId("error-state").hidden = false;
  byId("error-message").textContent = message;
  byId("refresh-button").disabled = false;
}

function formatDate(value) {
  if (!value || value === "never") return "never";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}
function formatBytes(value) { const bytes = Number(value || 0); return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`; }
function truncate(value, max) { const text = String(value); return text.length > max ? `${text.slice(0, max - 1)}…` : text; }
function showToast(message) { const toast = byId("toast"); toast.textContent = message; toast.hidden = false; clearTimeout(showToast.timer); showToast.timer = setTimeout(() => { toast.hidden = true; }, 1800); }

document.addEventListener("click", (event) => {
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) switchView(viewButton.dataset.view);
  const goButton = event.target.closest("[data-go-view]");
  if (goButton) switchView(goButton.dataset.goView);
});
byId("welcome-close").addEventListener("click", dismissWelcome);
byId("welcome-got-it").addEventListener("click", dismissWelcome);
byId("welcome-explore").addEventListener("click", dismissWelcome);
byId("welcome-open").addEventListener("click", openWelcome);
byId("refresh-button").addEventListener("click", renderDashboard);
byId("retry-button").addEventListener("click", renderDashboard);
byId("memory-search").addEventListener("input", (event) => { state.search = event.target.value; renderMemories(); });
byId("memory-kind-filter").addEventListener("change", (event) => { state.kind = event.target.value; renderMemories(); });
byId("copy-report").addEventListener("click", async () => { try { await navigator.clipboard.writeText(state.data.report); showToast("Report copied"); } catch { showToast("Copy unavailable"); } });
window.addEventListener("resize", () => { if (state.view === "codegraph") requestAnimationFrame(drawCodegraph); });

renderDashboard();
