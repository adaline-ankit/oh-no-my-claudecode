"use strict";

const WELCOME_KEY = "onmc_welcome_dismissed_v1";
const WELCOME_FRESH_THRESHOLD = 20;

const state = { data: null, view: "overview", search: "", kind: "", swarmFilter: "all", swarmScope: "repo", swarmSearch: "", autoRefresh: true, lastUpdated: null, renderedSwarms: [], seenVerified: null, liveSince: 0, liveActive: [], liveEvents: [] };
const THEME_KEY = "onmc_theme";

function applyTheme(theme) {
  const dark = theme === "dark";
  document.body.classList.toggle("theme-dark", dark);
  try { localStorage.setItem(THEME_KEY, dark ? "dark" : "light"); } catch { /* ignore */ }
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = dark ? "○" : "◐";
}
function toggleTheme() { applyTheme(document.body.classList.contains("theme-dark") ? "light" : "dark"); }
try { if (localStorage.getItem(THEME_KEY) === "dark") document.body.classList.add("theme-dark"); } catch { /* ignore */ }
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
  renderHomeLive();
  renderActivity();
  renderSwarms();
  renderAgents();
  renderPerformance();
  renderScorecard();
  renderTimeline();
  renderIntegration();
  renderMemoryFilters();
  renderMemories();
  renderTasks();
  renderCodegraphLists();
  renderHealth();
  renderMission();
  renderLiveStatus();
  renderWall();
  celebrateVerifications();
  switchView(state.view);
  renderWelcome();
}

function celebrateVerifications() {
  const swarms = (state.data && state.data.global && state.data.global.swarms)
    || (state.data && state.data.swarms && state.data.swarms.swarms) || [];
  const current = new Set();
  swarms.forEach((s) => (s.units || []).forEach((u) => {
    if (u.verified === true) current.add(`${s.swarm_id}:${u.unit_id}`);
  }));
  if (state.seenVerified === null) { state.seenVerified = current; return; } // first load: no toast storm
  let fresh = 0;
  current.forEach((k) => { if (!state.seenVerified.has(k)) fresh += 1; });
  state.seenVerified = current;
  if (fresh > 0) {
    showToast(`✓ ${fresh} agent${fresh > 1 ? "s" : ""} verified`);
    document.body.classList.add("celebrate");
    setTimeout(() => document.body.classList.remove("celebrate"), 900);
  }
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

function renderSwarmCard(sc, cardIndex) {
  const counts = sc.state_counts || {};
  const pills = SWARM_STATE_ORDER.filter((st) => counts[st]).map((st) => swarmStatePill(st, counts[st])).join("");
  const units = (sc.units || []).map((u, unitIndex) => `
    <li class="unit-row state-${escapeHtml(u.state)}" data-card-index="${cardIndex}" data-unit-index="${unitIndex}" tabindex="0" role="button" aria-label="Open ${escapeHtml(u.unit_id || "unit")} details">
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
        ${sc.repo ? `<span class="swarm-repo" title="repo">${escapeHtml(sc.repo)}</span>` : ""}
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

function scopedSwarms() {
  if (state.swarmScope === "global") {
    return (state.data && state.data.global && state.data.global.swarms) || [];
  }
  return (state.data && state.data.swarms && state.data.swarms.swarms) || [];
}

function visibleSwarms() {
  const q = state.swarmSearch.trim().toLowerCase();
  return scopedSwarms().filter((sc) => {
    if (state.swarmFilter === "live" && !sc.live) return false;
    if (!q) return true;
    return `${sc.label || ""} ${sc.swarm_id || ""} ${sc.repo || ""}`.toLowerCase().includes(q);
  });
}

function renderSwarms() {
  const global = state.swarmScope === "global";
  const sw = (state.data && state.data.swarms) || { summary: {}, swarms: [] };
  const g = (state.data && state.data.global) || { summary: {}, swarms: [] };
  const s = sw.summary || {};
  const gs = g.summary || {};
  const liveN = global ? (gs.live || 0) : (s.live || 0);
  const metrics = global
    ? [
        ["Live swarms", String(liveN), `${formatNumber(gs.swarms || 0)} across repos`],
        ["Running agents", String(gs.running_units || 0), "in flight now"],
        ["Repos", String(gs.repos || 0), "with agent activity"],
        ["Swarms", String(gs.swarms || 0), "all projects"],
      ]
    : [
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
  state.renderedSwarms = shown;
  byId("swarm-empty").hidden = shown.length > 0;
  byId("swarm-list").innerHTML = shown.map((sc, i) => renderSwarmCard(sc, i)).join("");
}

function renderAgents() {
  const sw = (state.data && state.data.swarms) || { summary: {}, swarms: [] };
  const s = sw.summary || {};
  const liveN = s.live || 0;
  const metrics = [
    ["Swarms", String(s.swarms || 0), "this repo"],
    ["Live", String(liveN), "active now"],
    ["Running units", String(s.running_units || 0), "in-flight agents"],
    ["Verified", String(s.verified_units || 0), `of ${formatNumber(s.total_units || 0)}`],
    ["Fleet cost", `$${Number(s.total_cost_usd || 0).toFixed(2)}`, "recorded"],
  ];
  byId("agents-metric-grid").innerHTML = metrics.map(([label, value, detail]) => `
    <div class="metric"><span class="metric-label">${escapeHtml(label)}</span><strong class="metric-value">${escapeHtml(value)}</strong><span class="metric-detail">${escapeHtml(detail)}</span></div>
  `).join("");
  const chip = byId("agents-live-chip");
  chip.className = `status-chip ${liveN > 0 ? "ready" : ""}`;
  chip.textContent = liveN > 0 ? `${liveN} live` : "idle";
  const dot = byId("nav-agents-dot");
  if (dot) dot.hidden = !liveN;
  const swarms = sw.swarms || [];
  byId("agents-empty").hidden = swarms.length > 0;
  byId("agents-swarms-sub").textContent = `${swarms.length} swarm(s)`;
  byId("agents-swarm-list").innerHTML = swarms.map((sc) => renderAgentSwarmCard(sc)).join("");
}

function renderAgentSwarmCard(sc) {
  const counts = sc.state_counts || {};
  const pills = SWARM_STATE_ORDER.filter((st) => counts[st]).map((st) => swarmStatePill(st, counts[st])).join("");
  const cost = sc.cost_usd ? Number(sc.cost_usd).toFixed(2) : null;
  const abortBtn = sc.aborted
    ? `<span class="swarm-aborted">ABORTED</span>`
    : `<button class="button button-outline agents-abort-btn" data-swarm-id="${escapeHtml(sc.swarm_id)}" type="button">Abort</button>`;
  return `<article class="swarm-card ${sc.live ? "is-live" : ""}">
    <header class="swarm-card-head">
      <div class="swarm-title">
        <code title="${escapeHtml(sc.swarm_id)}">${escapeHtml(String(sc.swarm_id).slice(0, 10))}</code>
        <span class="swarm-label">${escapeHtml(truncate(sc.label || "swarm", 66))}</span>
      </div>
      <div class="swarm-meta agents-card-actions">${abortBtn}</div>
    </header>
    <div class="swarm-stats">${pills}
      <span class="swarm-verified">${formatNumber(sc.verified_count || 0)}/${formatNumber(sc.total || 0)} verified</span>
      ${cost ? `<span class="swarm-cost">$${cost}</span>` : ""}
    </div>
  </article>`;
}

async function agentAction(payload) {
  try {
    const resp = await fetch("/api/agents/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    showToast(data.ok ? "Done" : `Failed: ${String(data.output || "error").slice(0, 60)}`);
    return data;
  } catch {
    showToast("Action request failed");
    return { ok: false, returncode: 1, output: "request error" };
  }
}

function openUnitDrawer(cardIndex, unitIndex) {
  const sc = (state.renderedSwarms || [])[cardIndex];
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

  renderSparklines((fw && fw.trend) || []);
}

// Rolling verified-rate + cost-per-run sparklines over recent receipts.
function sparklineSvg(values, color, fill) {
  const n = values.length;
  if (n < 2) return "";
  const w = 240, h = 44, pad = 3;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || 1;
  const x = (i) => pad + (i / (n - 1)) * (w - pad * 2);
  const y = (v) => h - pad - ((v - lo) / span) * (h - pad * 2);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const line = `M${pts.join(" L")}`;
  const area = `${line} L${x(n - 1).toFixed(1)},${h} L${x(0).toFixed(1)},${h} Z`;
  const lastX = x(n - 1).toFixed(1), lastY = y(values[n - 1]).toFixed(1);
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-hidden="true">
    <path d="${area}" fill="${fill}"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${lastX}" cy="${lastY}" r="2.4" fill="${color}"/>
  </svg>`;
}

function renderSparklines(trend) {
  const panel = byId("perf-trend-panel");
  if (!panel) return;
  if (!trend || trend.length < 2) { panel.hidden = true; return; }
  panel.hidden = false;
  byId("perf-trend-count").textContent = `last ${trend.length} runs`;

  // Rolling verified rate (window of 5) → percentage series.
  const win = 5;
  const rate = trend.map((_, i) => {
    const from = Math.max(0, i - win + 1);
    const slice = trend.slice(from, i + 1);
    const ok = slice.filter((p) => p.verified).length;
    return Math.round((ok / slice.length) * 100);
  });
  byId("spark-rate").innerHTML = sparklineSvg(rate, "#237a50", "rgba(35,122,80,.12)");
  byId("spark-rate-val").textContent = `${rate[rate.length - 1]}%`;

  const costs = trend.map((p) => Number(p.cost || 0));
  const hasCost = costs.some((c) => c > 0);
  if (hasCost) {
    byId("spark-cost").innerHTML = sparklineSvg(costs, "#356f91", "rgba(53,111,145,.12)");
    byId("spark-cost-val").textContent = `$${costs[costs.length - 1].toFixed(2)}`;
  } else {
    byId("spark-cost").innerHTML = '<span class="spark-none">no cost recorded</span>';
    byId("spark-cost-val").textContent = "n/a";
  }
}

// ── Agent Wall (fullscreen monitor mode) ─────────────────────────────────
const wall = { open: false };

function wallSwarms() {
  const g = (state.data && state.data.global) || {};
  const gs = (g.swarms || []).filter((s) => s.live);
  if (gs.length) return gs;
  const repo = (state.data && state.data.swarms && state.data.swarms.swarms) || [];
  return repo.filter((s) => s.live);
}

function renderWall() {
  if (!wall.open) return;
  const swarms = wallSwarms();
  const running = swarms.reduce((n, s) => n + (s.running_units || 0), 0);
  byId("wall-sub").textContent = `${swarms.length} live · ${running} agents running`;
  byId("wall-empty").hidden = swarms.length > 0;
  byId("wall-grid").innerHTML = swarms.map((s) => {
    const counts = s.state_counts || {};
    const pills = SWARM_STATE_ORDER.filter((st) => counts[st]).map((st) => `<span class="wall-pill state-${escapeHtml(st)}">${escapeHtml(st)} ${counts[st]}</span>`).join("");
    return `<article class="wall-tile">
      <div class="wall-tile-top"><span class="wall-live"><span class="wall-live-dot"></span>LIVE</span>${s.repo ? `<span class="wall-repo">${escapeHtml(s.repo)}</span>` : ""}</div>
      <div class="wall-label">${escapeHtml(truncate(s.label || "swarm", 90))}</div>
      <div class="wall-run"><strong>${formatNumber(s.running_units || 0)}</strong> running · ${formatNumber(s.verified_count || 0)}/${formatNumber(s.total || 0)} verified</div>
      <div class="wall-pills">${pills}</div>
    </article>`;
  }).join("");
}

function openWall() { wall.open = true; byId("wall").hidden = false; document.body.classList.add("wall-active"); renderWall(); }
function closeWall() { wall.open = false; byId("wall").hidden = true; document.body.classList.remove("wall-active"); }

// ── Command palette (⌘K) ────────────────────────────────────────────────
const cmdk = { open: false, items: [], filtered: [], index: 0 };

function commandItems() {
  const items = SHORTCUT_VIEWS.map((v, i) => ({
    kind: "View",
    label: `Go to ${v.charAt(0).toUpperCase()}${v.slice(1)}`,
    sub: `press ${i + 1}`,
    run: () => switchView(v),
  }));
  const swarms = (state.data && state.data.swarms && state.data.swarms.swarms) || [];
  swarms.forEach((s) => items.push({
    kind: "Swarm",
    label: s.label || s.swarm_id,
    sub: `${s.live ? "live · " : ""}${String(s.swarm_id).slice(0, 8)}`,
    run: () => { switchView("swarms"); state.swarmSearch = String(s.swarm_id).slice(0, 8); const el = byId("swarm-search"); if (el) el.value = state.swarmSearch; renderSwarms(); },
  }));
  const memories = (state.data && state.data.memories) || [];
  memories.slice(0, 60).forEach((m) => items.push({
    kind: "Memory",
    label: m.title,
    sub: formatKind(m.kind),
    run: () => { switchView("memory"); state.search = m.title; byId("memory-search").value = m.title; renderMemories(); },
  }));
  return items;
}

function renderCmdk() {
  const list = byId("cmdk-results");
  list.innerHTML = cmdk.filtered.slice(0, 40).map((it, i) => `
    <li class="cmdk-item ${i === cmdk.index ? "is-active" : ""}" role="option" aria-selected="${i === cmdk.index}" data-cmdk-index="${i}">
      <span class="cmdk-kind">${escapeHtml(it.kind)}</span>
      <span class="cmdk-label">${escapeHtml(truncate(it.label || "", 64))}</span>
      <span class="cmdk-sub">${escapeHtml(it.sub || "")}</span>
    </li>`).join("") || '<li class="cmdk-empty">No matches</li>';
}

function filterCmdk(query) {
  const q = query.trim().toLowerCase();
  cmdk.filtered = !q ? cmdk.items : cmdk.items.filter((it) => `${it.label} ${it.sub} ${it.kind}`.toLowerCase().includes(q));
  cmdk.index = 0;
  renderCmdk();
}

function openCmdk() {
  cmdk.open = true;
  cmdk.items = commandItems();
  byId("cmdk-backdrop").hidden = false;
  byId("cmdk").hidden = false;
  const input = byId("cmdk-input");
  input.value = "";
  filterCmdk("");
  input.focus();
}

function closeCmdk() {
  cmdk.open = false;
  byId("cmdk-backdrop").hidden = true;
  byId("cmdk").hidden = true;
}

function runCmdk(index) {
  const item = cmdk.filtered[index];
  closeCmdk();
  if (item) item.run();
}

function timeAgo(ts) {
  if (!ts) return "";
  const then = new Date(ts).valueOf();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

function activityGlyph(u) {
  if (u.verified === true) return '<span class="feed-glyph ok" title="verified">✓</span>';
  if (u.state === "failed" || u.state === "aborted") return '<span class="feed-glyph bad" title="failed">✕</span>';
  if (u.state === "running") return '<span class="feed-glyph run" title="running">◐</span>';
  return '<span class="feed-glyph pending" title="pending">•</span>';
}

function renderActivity() {
  const swarms = (state.data && state.data.global && state.data.global.swarms)
    || (state.data && state.data.swarms && state.data.swarms.swarms) || [];
  const events = [];
  swarms.forEach((s) => (s.units || []).forEach((u) => {
    events.push({ unit: u, repo: s.repo, label: u.goal || s.label || "unit", ts: u.ended_at || u.started_at || s.started_at });
  }));
  events.sort((a, b) => String(b.ts || "").localeCompare(String(a.ts || "")));
  const top = events.slice(0, 14);
  byId("activity-feed-sub").textContent = `${formatNumber(events.length)} events`;
  byId("activity-feed").innerHTML = top.length
    ? top.map((e) => `
      <li class="feed-row">
        ${activityGlyph(e.unit)}
        <span class="feed-text">${escapeHtml(truncate(e.label, 78))}</span>
        ${e.repo ? `<span class="feed-repo">${escapeHtml(e.repo)}</span>` : ""}
        <span class="feed-state feed-${escapeHtml(e.unit.state)}">${escapeHtml(e.unit.state)}</span>
        <span class="feed-when">${escapeHtml(timeAgo(e.ts))}</span>
      </li>`).join("")
    : '<li class="feed-empty">No agent activity yet.</li>';
}

function renderHomeLive() {
  const sw = (state.data && state.data.swarms) || { summary: {}, swarms: [] };
  const s = sw.summary || {};
  const live = (sw.swarms || []).filter((x) => x.live).slice(0, 4);
  const stats = `<div class="live-home-stats">
    <span class="${(s.live || 0) ? "on" : ""}"><strong>${formatNumber(s.live || 0)}</strong> live</span>
    <span class="${(s.running_units || 0) ? "on" : ""}"><strong>${formatNumber(s.running_units || 0)}</strong> running agents</span>
    <span><strong>${formatNumber(s.swarms || 0)}</strong> swarms</span>
    <span><strong>${formatNumber(s.verified_units || 0)}</strong> verified</span>
  </div>`;
  const rows = live.length
    ? live.map((sc) => `<button class="live-home-row" data-go-view="swarms" type="button">
        <span class="live-badge"><span class="live-dot"></span>LIVE</span>
        <span class="live-home-label">${escapeHtml(truncate(sc.label || "swarm", 72))}</span>
        <span class="live-home-run">${formatNumber(sc.running_units || 0)} running</span></button>`).join("")
    : '<div class="live-home-empty">No agents running right now — start one with <code>onmc swarm plan</code>.</div>';
  byId("live-home-body").innerHTML = stats + rows;
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

const TIMELINE_PER_PERIOD = 40;

function renderIntegration() {
  const it = (state.data && state.data.integration) || {};
  const level = it.level || "none";
  const chip = byId("integration-chip");
  chip.className = `status-chip ${level === "full" ? "ready" : "needs-attention"}`;
  chip.textContent = level === "full" ? "default layer" : level === "partial" ? "partial" : "not connected";
  const dot = byId("nav-integ-dot");
  if (dot) dot.hidden = level === "full";

  const heads = {
    full: ["onmc is the default layer", "All Claude Code agent work routes through onmc — swarm, memory, and verified receipts."],
    partial: ["Partially wired", "Some pieces are active. Finish setup so every Claude Code session runs on onmc."],
    none: ["Not connected yet", "Wire onmc into Claude Code so it becomes the default layer for every session."],
  };
  const [head, sub] = heads[level] || heads.none;
  byId("integ-banner").innerHTML = `<div class="integ-banner-body level-${escapeHtml(level)}"><strong>${escapeHtml(head)}</strong><p>${escapeHtml(sub)}</p></div>`;

  const checks = [
    ["MCP server registered", it.mcp_registered, "onmc serve --mcp · .mcp.json"],
    ["Session hooks installed", it.hooks_installed, "PreCompact · SessionStart · UserPromptSubmit · SessionEnd"],
    ["Strict wrap (Task intercept)", it.wrap_installed, "native agent spawns → onmc swarm"],
    ["CLAUDE.md policy stanza", it.claude_md_stanza, "onmc usage policy for the agent"],
  ];
  byId("integ-checklist").innerHTML = checks.map(([label, ok, detail]) => `
    <li class="integ-check ${ok ? "ok" : "off"}"><span class="integ-mark" aria-hidden="true">${ok ? "✓" : "○"}</span><div><strong>${escapeHtml(label)}</strong><span>${escapeHtml(detail)}</span></div></li>`).join("");

  const steps = it.next_steps || [];
  byId("integ-steps-panel").hidden = steps.length === 0;
  byId("integ-steps").innerHTML = steps.map((s) => `
    <li class="integ-step"><code>${escapeHtml(s)}</code><button class="text-button integ-copy" data-copy="${escapeHtml(s)}" type="button">Copy</button></li>`).join("");
}

function renderTimeline() {
  const tl = (state.data && state.data.timeline) || { periods: [], total: 0 };
  byId("timeline-total").textContent = `${formatNumber(tl.total || 0)} milestone${tl.total === 1 ? "" : "s"}`;
  byId("timeline-empty").hidden = (tl.total || 0) > 0;
  byId("timeline-body").innerHTML = (tl.periods || []).map((p) => {
    const entries = p.entries || [];
    const shown = entries.slice(0, TIMELINE_PER_PERIOD);
    const more = entries.length - shown.length;
    const rows = shown.map((e) => `
      <li class="tl-entry">
        <span class="tl-dot kind-${escapeHtml(e.kind)}" aria-hidden="true"></span>
        <div class="tl-entry-body">
          <div class="tl-entry-head"><span class="kind-badge">${escapeHtml(formatKind(e.kind))}</span><strong>${escapeHtml(truncate(e.title || "", 84))}</strong></div>
          ${e.summary ? `<p class="tl-entry-sum">${escapeHtml(truncate(e.summary, 150))}</p>` : ""}
        </div>
      </li>`).join("");
    const moreRow = more > 0 ? `<li class="tl-more">+ ${formatNumber(more)} more this period</li>` : "";
    return `<div class="tl-period"><div class="tl-period-label">${escapeHtml(p.label)}</div><ul class="tl-entries">${rows}${moreRow}</ul></div>`;
  }).join("");
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
  const { evolution } = loops;
  const runtime = state.data.runtime || { summary: {}, runs: [] };
  const runs = runtime.runs || [];
  const runCount = runs.length;

  byId("mission-run-count").textContent = runCount
    ? `${runtime.summary.active || 0} active · ${runtime.summary.verified || 0} verified · ${runCount} recent`
    : "";

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

  // Canonical runtime table, reconstructed from durable events.
  const runsEl = byId("runs-body");
  byId("runs-subtitle").textContent = runs.length ? `last ${runs.length}` : "";
  if (!runs.length) {
    runsEl.innerHTML = '<div class="evolution-empty">No canonical runs yet. Preview one with <code>onmc run "your task"</code>; execute it explicitly with <code>--execute</code>.</div>';
  } else {
    runsEl.innerHTML = `<div class="runs-table-shell"><table class="runs-table"><thead><tr>
      <th>Run</th><th>State</th><th>Active node</th><th>Proof</th><th>Evidence / action</th><th>Updated</th><th>Receipt</th>
    </tr></thead><tbody>${runs.map((run) => `<tr>
      <td><span class="run-goal">${escapeHtml(truncate(run.task || run.run_id, 46))}</span></td>
      <td><span class="run-agent">${escapeHtml(run.state || "unknown")}</span></td>
      <td>${escapeHtml(run.active_node || "—")}</td>
      <td class="${run.verified ? "run-verified-yes" : run.proof_state === "rejected" || run.proof_state === "unavailable" ? "run-verified-no" : ""}">${escapeHtml(run.proof_state || "pending")}</td>
      <td>${escapeHtml((run.proof_reasons || [])[0] || run.action || run.last_event || "—")}</td>
      <td>${escapeHtml(run.updated_at ? formatDate(run.updated_at) : "—")}</td>
      <td><span class="run-hash">${escapeHtml((run.receipt_hash || "").slice(0, 12) || "—")}</span></td>
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

// Returns a relative-time string from a Unix timestamp (float seconds).
function formatElapsed(ts) {
  if (!ts) return "—";
  const sec = Math.round(Date.now() / 1000 - Number(ts));
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}

// Render the Live Activity panel inside the Agents view.
function renderLiveFeed() {
  const activeEl = byId("agents-active-list");
  const feedEl = byId("agents-live-feed");
  const subEl = byId("agents-live-sub");
  if (!activeEl || !feedEl) return;

  const active = state.liveActive || [];
  const events = state.liveEvents || [];

  if (subEl) {
    subEl.textContent = active.length
      ? `${active.length} active · polling`
      : "idle · polling every 2s";
  }

  if (active.length === 0) {
    activeEl.innerHTML = '<div class="agents-live-idle">No agents running.</div>';
  } else {
    activeEl.innerHTML = active.map((a) => `
      <div class="agents-live-agent-row">
        <span class="live-dot"></span>
        <span class="agents-live-agent-unit" title="${escapeHtml(String(a.unit || ""))}">${escapeHtml(String(a.unit || "—"))}</span>
        ${a.agent ? `<span class="agents-live-agent-id">${escapeHtml(String(a.agent))}</span>` : ""}
        <span class="agents-live-agent-since">${formatElapsed(a.since_ts)}</span>
      </div>`).join("");
  }

  if (events.length === 0) {
    feedEl.innerHTML = '<div class="agents-live-idle">No events yet.</div>';
  } else {
    feedEl.innerHTML = events.map((e) => `
      <div class="agents-live-event-row">
        <span class="agents-live-event-kind">${escapeHtml(formatKind(String(e.kind || "")))}</span>
        <span class="agents-live-event-agent">${escapeHtml(String(e.agent || e.unit || ""))}</span>
        ${e.tool ? `<span class="agents-live-event-tool">${escapeHtml(String(e.tool))}</span>` : ""}
        <span class="agents-live-event-ts">${formatElapsed(e.ts)}</span>
      </div>`).join("");
  }
}

// Poll /api/live every 2s and update the Agents live feed. Skipped for static
// exports (embedded data) and while the tab is hidden.
const LIVE_POLL_MS = 2000;
async function pollLiveFeed() {
  if (byId("onmc-dashboard-data") || document.hidden) return;
  try {
    const resp = await fetch(`/api/live?since=${state.liveSince}`, { cache: "no-store" });
    if (!resp.ok) return;
    const data = await resp.json();
    if (typeof data.max_ts === "number" && data.max_ts > state.liveSince) {
      state.liveSince = data.max_ts;
    }
    state.liveActive = Array.isArray(data.active) ? data.active : [];
    // Prepend newest events and cap the feed at 50 entries.
    const incoming = Array.isArray(data.events) ? data.events.slice().reverse() : [];
    state.liveEvents = [...incoming, ...state.liveEvents].slice(0, 50);
    renderLiveFeed();
  } catch { /* keep last good data until next tick */ }
}

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
  if (row) openUnitDrawer(Number(row.dataset.cardIndex), Number(row.dataset.unitIndex));
});
byId("swarm-list").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest(".unit-row");
  if (row) { event.preventDefault(); openUnitDrawer(Number(row.dataset.cardIndex), Number(row.dataset.unitIndex)); }
});
document.querySelectorAll("[data-swarm-scope]").forEach((btn) => btn.addEventListener("click", () => {
  state.swarmScope = btn.dataset.swarmScope;
  document.querySelectorAll("[data-swarm-scope]").forEach((b) => b.classList.toggle("is-active", b === btn));
  renderSwarms();
}));
byId("drawer-close").addEventListener("click", closeDrawer);
byId("drawer-backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !byId("unit-drawer").hidden) closeDrawer(); });
byId("wall-open").addEventListener("click", openWall);
byId("wall-close").addEventListener("click", closeWall);
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && wall.open) closeWall(); });
byId("swarm-search").addEventListener("input", (event) => { state.swarmSearch = event.target.value; renderSwarms(); });
document.querySelectorAll("[data-swarm-filter]").forEach((btn) => btn.addEventListener("click", () => {
  state.swarmFilter = btn.dataset.swarmFilter;
  document.querySelectorAll("[data-swarm-filter]").forEach((b) => b.classList.toggle("is-active", b === btn));
  renderSwarms();
}));
// Agents orchestration: abort per-swarm, preview canonical run, land PR.
byId("agents-swarm-list").addEventListener("click", async (event) => {
  const btn = event.target.closest(".agents-abort-btn");
  if (!btn) return;
  const swarmId = btn.dataset.swarmId || "";
  if (!swarmId) return;
  btn.disabled = true;
  await agentAction({ action: "abort", swarm_id: swarmId });
  btn.disabled = false;
});
byId("agents-mission-btn").addEventListener("click", async () => {
  const input = byId("agents-mission-input");
  const goal = (input.value || "").trim();
  if (!goal) { showToast("Enter a mission goal first"); return; }
  byId("agents-mission-btn").disabled = true;
  await agentAction({ action: "run", goal });
  byId("agents-mission-btn").disabled = false;
  input.value = "";
});
byId("agents-land-btn").addEventListener("click", async () => {
  const input = byId("agents-land-input");
  const pr_url = (input.value || "").trim();
  if (!pr_url) { showToast("Enter a PR URL first"); return; }
  byId("agents-land-btn").disabled = true;
  await agentAction({ action: "land", pr_url });
  byId("agents-land-btn").disabled = false;
  input.value = "";
});
byId("autorefresh-toggle").addEventListener("change", (event) => {
  state.autoRefresh = event.target.checked;
  renderLiveStatus();
  if (state.autoRefresh) refreshSilently();
});
byId("theme-toggle").addEventListener("click", toggleTheme);
document.addEventListener("click", async (event) => {
  const copyBtn = event.target.closest(".integ-copy");
  if (!copyBtn) return;
  try { await navigator.clipboard.writeText(copyBtn.dataset.copy || ""); showToast("Command copied"); } catch { showToast("Copy unavailable"); }
});
applyTheme(document.body.classList.contains("theme-dark") ? "dark" : "light");

// Keyboard shortcuts: 1-9 jump to a view, "/" focuses the current search, "t" theme.
const SHORTCUT_VIEWS = ["overview", "swarms", "performance", "scorecard", "timeline", "memory", "tasks", "codegraph", "health", "mission"];

// Command palette input handling (arrows/enter/esc) + open shortcut.
byId("cmdk-input").addEventListener("input", (event) => filterCmdk(event.target.value));
byId("cmdk-input").addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown") { event.preventDefault(); cmdk.index = Math.min(cmdk.index + 1, cmdk.filtered.length - 1); renderCmdk(); }
  else if (event.key === "ArrowUp") { event.preventDefault(); cmdk.index = Math.max(cmdk.index - 1, 0); renderCmdk(); }
  else if (event.key === "Enter") { event.preventDefault(); runCmdk(cmdk.index); }
  else if (event.key === "Escape") { event.preventDefault(); closeCmdk(); }
});
byId("cmdk-results").addEventListener("click", (event) => {
  const li = event.target.closest("[data-cmdk-index]");
  if (li) runCmdk(Number(li.dataset.cmdkIndex));
});
byId("cmdk-backdrop").addEventListener("click", closeCmdk);

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && (event.key === "k" || event.key === "K")) {
    event.preventDefault();
    cmdk.open ? closeCmdk() : openCmdk();
    return;
  }
  const typing = /^(input|textarea|select)$/i.test(event.target.tagName);
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (typing) { if (event.key === "Escape") event.target.blur(); return; }
  if (event.key >= "1" && event.key <= "9") {
    const view = SHORTCUT_VIEWS[Number(event.key) - 1];
    if (view) { event.preventDefault(); switchView(view); }
  } else if (event.key === "/") {
    const search = state.view === "swarms" ? byId("swarm-search") : state.view === "memory" ? byId("memory-search") : null;
    if (search) { event.preventDefault(); search.focus(); }
  } else if (event.key === "t") {
    toggleTheme();
  } else if (event.key === "w") {
    wall.open ? closeWall() : openWall();
  }
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
  setInterval(pollLiveFeed, LIVE_POLL_MS);
  pollLiveFeed(); // initial fetch, don't wait for first 2s tick
}
