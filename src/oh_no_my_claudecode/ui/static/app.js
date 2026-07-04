"use strict";

const WELCOME_KEY = "onmc_welcome_dismissed_v1";
const WELCOME_FRESH_THRESHOLD = 20;

const state = { data: null, view: "overview", search: "", kind: "", swarmFilter: "all", swarmSearch: "", autoRefresh: true, lastUpdated: null };
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
    state.lastUpdated = Date.now();
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
  renderSwarms();
  renderPerformance();
  renderScorecard();
  renderMemoryFilters();
  renderMemories();
  renderTasks();
  renderCodegraphLists();
  renderHealth();
  renderMission();
  renderLiveStatus();
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

const SWARM_STATE_ORDER = ["running", "queued", "pending", "done", "failed", "aborted"];

function swarmStatePill(stateName, count) {
  return `<span class="swarm-pill state-${escapeHtml(stateName)}">${escapeHtml(stateName)} ${formatNumber(count)}</span>`;
}

function unitVerifiedGlyph(unit) {
  if (unit.verified === true) return '<span class="unit-glyph ok" title="verified">✓</span>';
  if (unit.state === "failed") return '<span class="unit-glyph bad" title="failed">✕</span>';
  if (unit.state === "running") return '<span class="unit-glyph run" title="running">◐</span>';
  return '<span class="unit-glyph pending" title="not yet verified">•</span>';
}

function renderSwarmCard(sc, swarmIndex) {
  const counts = sc.state_counts || {};
  const pills = SWARM_STATE_ORDER.filter((st) => counts[st]).map((st) => swarmStatePill(st, counts[st])).join("");
  const units = (sc.units || []).map((u, unitIndex) => `
    <li class="unit-row state-${escapeHtml(u.state)}" data-swarm-index="${swarmIndex}" data-unit-index="${unitIndex}" tabindex="0" role="button" aria-label="Open ${escapeHtml(u.unit_id || "unit")} details">
      ${unitVerifiedGlyph(u)}
      <span class="unit-state">${escapeHtml(u.state)}</span>
      <span class="unit-goal" title="${escapeHtml(u.goal)}">${escapeHtml(truncate(u.goal || "unit", 76))}</span>
      ${Number(u.tokens) ? `<span class="unit-tokens">${formatNumber(u.tokens)} tok</span>` : ""}
      ${u.diff_sha ? `<code class="unit-sha" title="diff ${escapeHtml(u.diff_sha)}">${escapeHtml(String(u.diff_sha).slice(0, 8))}</code>` : ""}
      <span class="unit-chevron" aria-hidden="true">›</span>
    </li>`).join("");
  const cost = Number(sc.cost_usd || 0);
  return `<article class="swarm-card ${sc.live ? "is-live" : ""}">
    <header class="swarm-card-head">
      <div class="swarm-title">
        ${sc.live ? '<span class="live-badge"><span class="live-dot"></span>LIVE</span>' : ""}
        <span class="swarm-label" title="${escapeHtml(sc.label || "")}">${escapeHtml(truncate(sc.label || "swarm", 66))}</span>
      </div>
      <div class="swarm-meta">
        <code title="${escapeHtml(sc.swarm_id)}">${escapeHtml(String(sc.swarm_id).slice(0, 10))}</code>
        <span>${escapeHtml(sc.agent || "agent")}</span>
        ${sc.started_at ? `<span>${escapeHtml(formatDate(sc.started_at))}</span>` : ""}
        ${sc.aborted ? '<span class="swarm-aborted">ABORTED</span>' : ""}
      </div>
    </header>
    <div class="swarm-stats">
      ${pills}
      <span class="swarm-verified">${formatNumber(sc.verified_count || 0)}/${formatNumber(sc.total || 0)} verified</span>
      ${cost ? `<span class="swarm-cost">$${cost.toFixed(2)}</span>` : ""}
    </div>
    <ul class="unit-list">${units}</ul>
  </article>`;
}

function visibleSwarms() {
  const all = (state.data && state.data.swarms && state.data.swarms.swarms) || [];
  const q = state.swarmSearch.trim().toLowerCase();
  return all.filter((sc) => {
    if (state.swarmFilter === "live" && !sc.live) return false;
    if (!q) return true;
    return String(sc.label || "").toLowerCase().includes(q) || String(sc.swarm_id || "").toLowerCase().includes(q);
  });
}

function renderSwarms() {
  const sw = (state.data && state.data.swarms) || { summary: {}, swarms: [] };
  const s = sw.summary || {};
  const liveN = s.live || 0;
  const metrics = [
    ["Live swarms", String(liveN), `${formatNumber(s.swarms || 0)} total`],
    ["Running agents", String(s.running_units || 0), "in flight now"],
    ["Verified units", String(s.verified_units || 0), `of ${formatNumber(s.total_units || 0)}`],
    ["Fleet cost", `$${Number(s.total_cost_usd || 0).toFixed(2)}`, "recorded"],
  ];
  byId("swarm-metric-grid").innerHTML = metrics.map(([label, value, detail]) => `
    <div class="metric ${label === "Running agents" && liveN ? "metric-live" : ""}"><span class="metric-label">${escapeHtml(label)}</span><strong class="metric-value">${escapeHtml(value)}</strong><span class="metric-detail">${escapeHtml(detail)}</span></div>
  `).join("");

  const chip = byId("swarms-live-chip");
  chip.className = `status-chip ${liveN ? "live" : "ready"}`;
  chip.textContent = liveN ? `${liveN} live` : "All idle";
  const dot = byId("nav-live-dot");
  if (dot) dot.hidden = !liveN;

  const shown = visibleSwarms();
  byId("swarm-empty").hidden = shown.length > 0;
  // Map filtered rows back to their index in the full list for drilldown lookup.
  const all = sw.swarms || [];
  byId("swarm-list").innerHTML = shown.map((sc) => renderSwarmCard(sc, all.indexOf(sc))).join("");
}

function openUnitDrawer(swarmIndex, unitIndex) {
  const swarms = (state.data && state.data.swarms && state.data.swarms.swarms) || [];
  const sc = swarms[swarmIndex];
  if (!sc) return;
  const u = (sc.units || [])[unitIndex];
  if (!u) return;
  byId("drawer-eyebrow").textContent = `${sc.swarm_id.slice(0, 10)} · ${sc.agent || "agent"}`;
  byId("drawer-title").textContent = u.unit_id || "unit";
  const rows = [
    ["State", u.state],
    ["Verified", u.verified === true ? "yes" : u.verified === false ? "no" : "—"],
    ["Cost", Number(u.cost_usd) ? `$${Number(u.cost_usd).toFixed(4)}` : "—"],
    ["Tokens", Number(u.tokens) ? formatNumber(u.tokens) : "—"],
    ["Iterations", Number(u.iterations) ? formatNumber(u.iterations) : "—"],
    ["Wall time", Number(u.wall_seconds) ? `${Number(u.wall_seconds).toFixed(1)}s` : "—"],
    ["Verifier exit", u.verifier_exit === null || u.verifier_exit === undefined ? "—" : String(u.verifier_exit)],
    ["Diff SHA", u.diff_sha ? String(u.diff_sha).slice(0, 16) : "—"],
    ["Tree SHA", u.git_tree_sha || "—"],
    ["Receipt", u.receipt_hash || "—"],
    ["Started", u.started_at ? formatDate(u.started_at) : "—"],
    ["Ended", u.ended_at ? formatDate(u.ended_at) : "—"],
  ];
  const detail = rows.map(([k, v]) => `<div class="drawer-row"><span class="drawer-key">${escapeHtml(k)}</span><span class="drawer-val">${escapeHtml(String(v))}</span></div>`).join("");
  const errBlock = u.error ? `<div class="drawer-error"><span class="drawer-key">Error</span><pre>${escapeHtml(u.error)}</pre></div>` : "";
  byId("drawer-body").innerHTML = `
    <div class="drawer-goal"><span class="unit-state state-${escapeHtml(u.state)}">${escapeHtml(u.state)}</span><p>${escapeHtml(u.goal || "")}</p></div>
    <div class="drawer-grid">${detail}</div>
    ${errBlock}`;
  byId("drawer-backdrop").hidden = false;
  byId("unit-drawer").hidden = false;
  requestAnimationFrame(() => byId("unit-drawer").classList.add("is-open"));
  byId("drawer-close").focus();
}

function closeDrawer() {
  const drawer = byId("unit-drawer");
  drawer.classList.remove("is-open");
  byId("drawer-backdrop").hidden = true;
  setTimeout(() => { drawer.hidden = true; }, 200);
}

function renderLiveStatus() {
  const el = byId("live-status");
  const text = byId("live-status-text");
  if (!el || !text) return;
  if (byId("onmc-dashboard-data")) { el.hidden = true; return; }
  el.hidden = false;
  const ago = state.lastUpdated ? Math.max(0, Math.round((Date.now() - state.lastUpdated) / 1000)) : null;
  const stale = ago !== null && ago > 12;
  el.classList.toggle("is-stale", stale || !state.autoRefresh);
  if (!state.autoRefresh) { text.textContent = "paused"; return; }
  text.textContent = ago === null ? "connecting…" : ago < 2 ? "updated now" : `updated ${ago}s ago`;
}

function renderPerformance() {
  const perf = (state.data && state.data.performance) || {};
  const fw = perf.flywheel;
  const led = perf.ledger;
  const hasData = !!(fw && fw.total > 0);
  byId("perf-empty").hidden = hasData;
  const rate = fw ? Math.round((fw.verified_rate || 0) * 100) : 0;
  const successRate = led ? Math.round((led.success_rate || 0) * 100) : 0;
  const cost = led ? Number(led.total_cost_usd || 0) : 0;
  const costUnknown = led ? (led.cost_unknown_count || 0) : 0;
  const metrics = [
    ["Runs", fw ? String(fw.total) : "0", led ? `${successRate}% success` : ""],
    ["Verified rate", `${rate}%`, fw ? `${fw.verified_total}/${fw.total} verified` : ""],
    ["Fleet cost", costUnknown && !cost ? "n/a" : `$${cost.toFixed(2)}`, costUnknown ? `${costUnknown} cost unknown` : "recorded"],
    ["Models", fw ? String(fw.by_model.length) : "0", fw && fw.best ? `best: ${fw.best.model}` : ""],
  ];
  byId("perf-metric-grid").innerHTML = metrics.map(([l, v, d]) => `
    <div class="metric"><span class="metric-label">${escapeHtml(l)}</span><strong class="metric-value">${escapeHtml(v)}</strong><span class="metric-detail">${escapeHtml(d)}</span></div>
  `).join("");

  const chip = byId("perf-chip");
  chip.className = `status-chip ${rate >= 70 ? "ready" : "needs-attention"}`;
  chip.textContent = hasData ? `${rate}% verified` : "no data";

  const models = fw ? fw.by_model : [];
  byId("perf-model-count").textContent = `${models.length} model${models.length === 1 ? "" : "s"}`;
  byId("perf-model-body").innerHTML = models.map((m) => {
    const mrate = Math.round((m.verified_rate || 0) * 100);
    return `<tr>
      <td><code>${escapeHtml(m.model)}</code></td>
      <td class="num">${formatNumber(m.runs)}</td>
      <td><div class="rate-cell"><span class="rate-bar"><i style="width:${mrate}%"></i></span><span class="rate-num">${formatNumber(m.verified)}/${formatNumber(m.runs)}</span></div></td>
      <td class="num">${m.avg_cost == null ? "n/a" : "$" + Number(m.avg_cost).toFixed(3)}</td>
      <td class="num">${Number(m.avg_wall || 0).toFixed(0)}s</td>
    </tr>`;
  }).join("");

  const recs = (fw && fw.recommendations) || [];
  byId("perf-recs").innerHTML = recs.length
    ? recs.map((r) => `<li>${escapeHtml(r)}</li>`).join("")
    : '<li class="recs-muted">Not enough verified runs yet.</li>';
}

function renderScorecard() {
  const sc = (state.data && state.data.scorecard) || {};
  const readiness = sc.readiness;
  const num = byId("score-num");
  const ring = byId("score-ring");
  num.textContent = readiness == null ? "–" : String(readiness);
  const pct = readiness == null ? 0 : Math.max(0, Math.min(100, readiness));
  const col = readiness == null ? "#c3ccc7" : readiness >= 80 ? "#237a50" : readiness >= 60 ? "#a65e18" : "#a23d3d";
  ring.style.background = `conic-gradient(${col} ${pct * 3.6}deg, #e8ecea 0deg)`;
  const trust = sc.top_agent_trust != null ? `trust ${Math.round(sc.top_agent_trust * 100)}%` : "no attestations yet";
  const tiles = [
    ["Top agent", sc.top_agent || "n/a", trust],
    ["Best model", sc.best_model || "n/a", "by verified rate"],
    ["Memory graph", sc.memory_entities != null ? `${formatNumber(sc.memory_entities)}` : "n/a", sc.memory_edges != null ? `${formatNumber(sc.memory_edges)} edges` : "entities"],
  ];
  byId("scorecard-tiles").innerHTML = tiles.map(([l, v, d]) => `
    <div class="metric"><span class="metric-label">${escapeHtml(l)}</span><strong class="metric-value">${escapeHtml(String(v))}</strong><span class="metric-detail">${escapeHtml(d)}</span></div>
  `).join("");
  const notes = sc.notes || [];
  byId("scorecard-notes-panel").hidden = notes.length === 0;
  byId("scorecard-notes").innerHTML = notes.map((n) => `<li>${escapeHtml(n)}</li>`).join("");
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

function renderMission() {
  const loops = state.data.loops || { evolution: null, recent_runs: [] };
  const { evolution, recent_runs: runs } = loops;
  const runCount = runs.length;

  byId("mission-run-count").textContent = runCount ? `${runCount} recent run${runCount === 1 ? "" : "s"}` : "";

  // Mark loop stages as "active" when runs exist
  document.querySelectorAll(".loop-stage").forEach((stage) => {
    stage.classList.toggle("is-active", runCount > 0);
  });

  // Evolution trend panel
  const evoEl = byId("evolution-body");
  if (!evolution || evolution.insufficient_data) {
    const hasAny = evolution && evolution.run_count > 0;
    evoEl.innerHTML = `<div class="evolution-empty">${hasAny
      ? `Only ${evolution.run_count} run recorded — need at least 2 to compute trend.<br>Run <code>onmc autopilot "your goal"</code> again to see improvement metrics.`
      : `No runs yet. Run <code>onmc autopilot "your goal"</code> a few times to see your agent improve.`
    }</div>`;
    byId("evolution-window-label").textContent = "";
  } else {
    const costPct = evolution.cost_change_pct;
    const iterPct = evolution.iterations_change_pct;
    const verRate = Math.round((evolution.verified_rate || 0) * 100);

    const formatPct = (pct) => {
      if (pct === null || pct === undefined) return "—";
      const sign = pct < 0 ? "↓" : pct > 0 ? "↑" : "—";
      return `${sign}${Math.abs(pct).toFixed(1)}%`;
    };
    const pctClass = (pct) => {
      if (pct === null || pct === undefined) return "neutral";
      return pct < 0 ? "improving" : pct > 0 ? "worsening" : "neutral";
    };

    byId("evolution-window-label").textContent = `${evolution.run_count} runs · ${verRate}% verified`;

    const costLabel = evolution.cost_unavailable ? "—" : formatPct(costPct);
    const costCls = evolution.cost_unavailable ? "neutral" : pctClass(costPct);

    evoEl.innerHTML = `<div class="evolution-stats">
      <div class="evolution-stat">
        <div class="evolution-stat-label">Cost trend</div>
        <div class="evolution-stat-value ${escapeHtml(costCls)}">${escapeHtml(costLabel)}</div>
      </div>
      <div class="evolution-stat">
        <div class="evolution-stat-label">Iterations trend</div>
        <div class="evolution-stat-value ${escapeHtml(pctClass(iterPct))}">${escapeHtml(formatPct(iterPct))}</div>
      </div>
      <div class="evolution-stat">
        <div class="evolution-stat-label">Verified rate</div>
        <div class="evolution-stat-value neutral">${verRate}%</div>
      </div>
      <div class="evolution-stat">
        <div class="evolution-stat-label">Total runs</div>
        <div class="evolution-stat-value neutral">${formatNumber(evolution.run_count)}</div>
      </div>
    </div>`;
  }

  // Recent runs table
  const runsEl = byId("runs-body");
  byId("runs-subtitle").textContent = runs.length ? `last ${runs.length}` : "";
  if (!runs.length) {
    runsEl.innerHTML = '<div class="evolution-empty">No runs recorded yet. Receipts appear here after each <code>onmc autopilot</code> run.</div>';
  } else {
    runsEl.innerHTML = `<div class="runs-table-shell"><table class="runs-table"><thead><tr>
      <th>Goal</th><th>Agent</th><th>✓</th><th>Iters</th><th>Cost</th><th>When</th><th>Hash</th>
    </tr></thead><tbody>${runs.map((run) => `<tr>
      <td><span class="run-goal">${escapeHtml(truncate(run.goal, 60))}</span></td>
      <td><span class="run-agent">${escapeHtml(run.agent)}</span></td>
      <td class="${run.verified ? "run-verified-yes" : "run-verified-no"}">${run.verified ? "✓" : "✗"}</td>
      <td>${formatNumber(run.iterations)}</td>
      <td>${run.cost_usd !== null && run.cost_usd !== undefined ? `$${Number(run.cost_usd).toFixed(3)}` : "—"}</td>
      <td>${escapeHtml(run.when ? formatDate(run.when) : "—")}</td>
      <td><span class="run-hash">${escapeHtml(run.receipt_hash_short || "")}</span></td>
    </tr>`).join("")}</tbody></table></div>`;
  }
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
byId("copy-scorecard").addEventListener("click", async () => { try { await navigator.clipboard.writeText((state.data.scorecard || {}).markdown || ""); showToast("Scorecard copied"); } catch { showToast("Copy unavailable"); } });
window.addEventListener("resize", () => { if (state.view === "codegraph") requestAnimationFrame(drawCodegraph); });

// Swarm drilldown, filters, and live-refresh controls.
byId("swarm-list").addEventListener("click", (event) => {
  const row = event.target.closest(".unit-row");
  if (row) openUnitDrawer(Number(row.dataset.swarmIndex), Number(row.dataset.unitIndex));
});
byId("swarm-list").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest(".unit-row");
  if (row) { event.preventDefault(); openUnitDrawer(Number(row.dataset.swarmIndex), Number(row.dataset.unitIndex)); }
});
byId("drawer-close").addEventListener("click", closeDrawer);
byId("drawer-backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !byId("unit-drawer").hidden) closeDrawer(); });
byId("swarm-search").addEventListener("input", (event) => { state.swarmSearch = event.target.value; renderSwarms(); });
document.querySelectorAll("[data-swarm-filter]").forEach((btn) => btn.addEventListener("click", () => {
  state.swarmFilter = btn.dataset.swarmFilter;
  document.querySelectorAll("[data-swarm-filter]").forEach((b) => b.classList.toggle("is-active", b === btn));
  renderSwarms();
}));
byId("autorefresh-toggle").addEventListener("change", (event) => {
  state.autoRefresh = event.target.checked;
  renderLiveStatus();
  if (state.autoRefresh) refreshSilently();
});

// Live auto-refresh: silently re-fetch and re-render so running swarms update
// in place. Skipped for the static export (embedded data) and while the tab is
// hidden. Keeps the last good data on a failed poll — never flashes an error.
const LIVE_REFRESH_MS = 4000;
async function refreshSilently() {
  if (!state.autoRefresh || document.hidden || byId("onmc-dashboard-data") || byId("error-state").hidden === false) return;
  // Don't yank the ground out while the user is reading a unit drawer.
  if (!byId("unit-drawer").hidden) return;
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) return;
    state.data = await response.json();
    state.lastUpdated = Date.now();
    hydrateDashboard();
  } catch { /* keep last good data until the next tick */ }
}

renderDashboard();
if (!byId("onmc-dashboard-data")) {
  setInterval(refreshSilently, LIVE_REFRESH_MS);
  setInterval(renderLiveStatus, 1000);
}
