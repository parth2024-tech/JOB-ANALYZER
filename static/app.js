// ===== CyberSec Intel Grid v3 - app.js =====
"use strict";

// ===== STATE =====
const state = {
  page: 1, pageSize: 24, totalPages: 1, totalJobs: 0,
  search: "", type: "", domain: "", source: "", seniority: "",
  company_category: "", min_salary_lpa: "",
  sort: "newest", location_scope: "all", remote: null,
  viewMode: localStorage.getItem("viewMode") || "grid",
  lastTimestamp: new Date().toISOString(),
  appliedIds: new Set(),
  charts: {},
  ws: null, wsReady: false,
  pendingNewJobs: 0,
};

// ===== INIT =====
document.addEventListener("DOMContentLoaded", () => {
  applyTheme(localStorage.getItem("theme") || "dark");
  setViewMode(state.viewMode, false);
  readUrlParams();
  loadJobs();
  loadStats();
  loadDomains();
  loadSources();
  setupSearch();
  setupKeyboard();
  connectWebSocket();
  // Poll for new jobs every 60s as fallback
  setInterval(pollNewJobs, 60000);
});

// ===== THEME =====
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  document.getElementById("theme-toggle").textContent = theme === "dark" ? "🌙" : "☀️";
  localStorage.setItem("theme", theme);
}
function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  applyTheme(current === "dark" ? "light" : "dark");
}

// ===== WEBSOCKET =====
function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${location.host}/ws`;
  state.ws = new WebSocket(url);
  state.ws.onopen = () => {
    state.wsReady = true;
    // Ping every 25s
    setInterval(() => { if (state.ws && state.ws.readyState === 1) state.ws.send("ping"); }, 25000);
  };
  state.ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.event === "scrape_complete" && msg.data.new_jobs > 0) {
        showNewJobsBanner(msg.data.new_jobs);
        loadStats();
      }
      if (msg.event === "scrape_started") {
        showToast("⚡ Scrape cycle started...", 3000);
      }
    } catch(e) {}
  };
  state.ws.onclose = () => {
    state.wsReady = false;
    setTimeout(connectWebSocket, 5000);
  };
}

// ===== WS BANNER =====
function showNewJobsBanner(count) {
  state.pendingNewJobs = count;
  const banner = document.getElementById("ws-banner");
  document.getElementById("ws-banner-text").textContent = `🆕 ${count} new cybersecurity job${count !== 1 ? "s" : ""} discovered!`;
  banner.classList.remove("hidden");
}
function dismissBanner() {
  document.getElementById("ws-banner").classList.add("hidden");
}
function refreshJobsFromBanner() {
  dismissBanner();
  state.page = 1;
  state.lastTimestamp = new Date().toISOString();
  loadJobs();
  loadStats();
}

// ===== POLLING FALLBACK =====
async function pollNewJobs() {
  try {
    const res = await fetch(`/api/jobs/new?since=${encodeURIComponent(state.lastTimestamp)}&limit=1`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.new_count > 0 && !document.getElementById("ws-banner").classList.contains("hidden") === false) {
      showNewJobsBanner(data.new_count);
    }
  } catch(e) {}
}

// ===== URL SYNC =====
function syncUrlParams() {
  const params = new URLSearchParams();
  if (state.search) params.set("q", state.search);
  if (state.type) params.set("type", state.type);
  if (state.domain) params.set("domain", state.domain);
  if (state.source) params.set("source", state.source);
  if (state.seniority) params.set("seniority", state.seniority);
  if (state.sort !== "newest") params.set("sort", state.sort);
  if (state.location_scope !== "all") params.set("scope", state.location_scope);
  if (state.remote !== null) params.set("remote", state.remote ? "1" : "0");
  if (state.page > 1) params.set("page", state.page);
  history.replaceState(null, "", params.toString() ? `?${params}` : location.pathname);
}
function readUrlParams() {
  const p = new URLSearchParams(location.search);
  if (p.get("q")) state.search = p.get("q");
  if (p.get("type")) state.type = p.get("type");
  if (p.get("domain")) state.domain = p.get("domain");
  if (p.get("source")) state.source = p.get("source");
  if (p.get("seniority")) state.seniority = p.get("seniority");
  if (p.get("sort")) state.sort = p.get("sort");
  if (p.get("scope")) state.location_scope = p.get("scope");
  if (p.get("remote")) state.remote = p.get("remote") === "1";
  if (p.get("page")) state.page = Math.max(1, parseInt(p.get("page")));
  // Reflect in UI
  if (state.search) document.getElementById("search-input").value = state.search;
  if (state.sort) document.getElementById("sort-select").value = state.sort;
}

// ===== KEYBOARD SHORTCUTS =====
function setupKeyboard() {
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") {
      if (e.key === "Escape") {
        e.target.blur();
        state.search = "";
        document.getElementById("search-input").value = "";
        applyFilters();
      }
      return;
    }
    switch (e.key) {
      case "/": e.preventDefault(); document.getElementById("search-input").focus(); break;
      case "Escape":
        closeJobModal();
        toggleShortcutsModal(true);
        document.getElementById("applied-panel").classList.add("hidden");
        document.getElementById("applied-overlay").classList.add("hidden");
        break;
      case "g": case "G": setViewMode("grid"); break;
      case "t": case "T": setViewMode("table"); break;
      case "d": case "D": toggleTheme(); break;
      case "1": setFilter("location_scope", state.location_scope === "target" ? "all" : "target",
                  document.querySelector(`#scope-tabs [data-val="${state.location_scope === "target" ? "all" : "target"}"]`), "scope-tabs"); break;
      case "?": toggleShortcutsModal(); break;
      case "ArrowLeft": if (state.page > 1) changePage(-1); break;
      case "ArrowRight": if (state.page < state.totalPages) changePage(1); break;
    }
  });
}

// ===== VIEW MODE =====
function setViewMode(mode, save = true) {
  state.viewMode = mode;
  if (save) localStorage.setItem("viewMode", mode);
  document.getElementById("view-grid-btn").classList.toggle("active", mode === "grid");
  document.getElementById("view-table-btn").classList.toggle("active", mode === "table");
  document.getElementById("job-grid").classList.toggle("hidden", mode !== "grid");
  document.getElementById("job-table-container").classList.toggle("hidden", mode !== "table");
}

// ===== SEARCH & AUTOCOMPLETE =====
let _searchTimer = null;
function setupSearch() {
  const input = document.getElementById("search-input");
  const dropdown = document.getElementById("autocomplete-dropdown");

  input.addEventListener("input", () => {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
      state.search = input.value.trim();
      state.page = 1;
      applyFilters();
      fetchAutocomplete(state.search);
    }, 280);
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search-wrapper")) dropdown.classList.add("hidden");
  });
}
async function fetchAutocomplete(q) {
  const dropdown = document.getElementById("autocomplete-dropdown");
  if (q.length < 2) { dropdown.classList.add("hidden"); return; }
  try {
    const res = await fetch(`/api/search/suggestions?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    const items = [
      ...data.titles.slice(0, 5).map(t => ({ label: t, type: "Title" })),
      ...data.companies.slice(0, 4).map(c => ({ label: c, type: "Company" })),
    ];
    if (!items.length) { dropdown.classList.add("hidden"); return; }
    dropdown.innerHTML = items.map(i => `
      <div class="autocomplete-item" onclick="selectAutocomplete('${escapeHtml(i.label)}')">
        ${escapeHtml(i.label)} <span class="ac-type">${i.type}</span>
      </div>`).join("");
    dropdown.classList.remove("hidden");
  } catch(e) { dropdown.classList.add("hidden"); }
}
function selectAutocomplete(val) {
  document.getElementById("search-input").value = val;
  document.getElementById("autocomplete-dropdown").classList.add("hidden");
  state.search = val;
  state.page = 1;
  applyFilters();
}

// ===== FILTERS =====
function setFilter(key, value, el, groupId) {
  state[key] = value;
  state.page = 1;
  if (el && groupId) {
    document.querySelectorAll(`#${groupId} .pill`).forEach(b => b.classList.remove("active"));
    el.classList.add("active");
  }
  applyFilters();
}
function applyFilters() {
  state.domain = document.getElementById("domain-select").value;
  state.source = document.getElementById("source-select").value;
  state.sort = document.getElementById("sort-select").value;
  syncUrlParams();
  loadJobs();
}
function clearFilters() {
  state.search = ""; state.type = ""; state.domain = ""; state.source = "";
  state.seniority = ""; state.sort = "newest"; state.location_scope = "all"; state.remote = null;
  state.page = 1;
  document.getElementById("search-input").value = "";
  document.getElementById("domain-select").value = "";
  document.getElementById("source-select").value = "";
  document.getElementById("sort-select").value = "newest";
  const salEl = document.getElementById("salary-select");
  if (salEl) salEl.value = "";
  state.company_category = "";
  state.min_salary_lpa = "";
  document.querySelectorAll("#category-tabs .pill").forEach(p => p.classList.toggle("active", p.dataset.val === ""));
  document.getElementById("remote-toggle").textContent = "Any";
  document.getElementById("remote-toggle").classList.remove("active");
  document.querySelectorAll(".tab-pills .pill").forEach(p => p.classList.toggle("active", p.dataset.val === "" || p.dataset.val === "all"));
  syncUrlParams();
  loadJobs();
}
function toggleRemoteFilter() {
  if (state.remote === null) { state.remote = true; }
  else if (state.remote === true) { state.remote = false; }
  else { state.remote = null; }
  const btn = document.getElementById("remote-toggle");
  btn.textContent = state.remote === null ? "Any" : state.remote ? "Remote Only" : "Onsite Only";
  btn.classList.toggle("active", state.remote !== null);
  state.page = 1;
  applyFilters();
}

// ===== PAGINATION =====
function changePage(delta) {
  const newPage = state.page + delta;
  if (newPage < 1 || newPage > state.totalPages) return;
  state.page = newPage;
  syncUrlParams();
  loadJobs();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function updatePagination() {
  const info = `Page ${state.page} of ${state.totalPages}`;
  ["page-info", "page-info-b"].forEach(id => { const el = document.getElementById(id); if (el) el.textContent = info; });
  ["prev-btn", "prev-btn-b"].forEach(id => { const el = document.getElementById(id); if (el) el.disabled = state.page <= 1; });
  ["next-btn", "next-btn-b"].forEach(id => { const el = document.getElementById(id); if (el) el.disabled = state.page >= state.totalPages; });
}

// ===== LOAD JOBS =====
async function loadJobs() {
  const grid = document.getElementById("job-grid");
  const tbody = document.getElementById("job-table-body");
  grid.innerHTML = `<div class="loading-text" style="grid-column:1/-1">⟳ Loading cybersecurity opportunities...</div>`;
  tbody.innerHTML = "";

  const params = new URLSearchParams();
  if (state.search) params.set("search", state.search);
  if (state.type) params.set("type", state.type);
  if (state.domain) params.set("domain", state.domain);
  if (state.source) params.set("source", state.source);
  if (state.seniority) params.set("seniority", state.seniority);
  if (state.company_category) params.set("company_category", state.company_category);
  if (state.min_salary_lpa) params.set("min_salary_lpa", state.min_salary_lpa);
  if (state.sort) params.set("sort", state.sort);
  if (state.location_scope) params.set("location_scope", state.location_scope);
  if (state.remote !== null) params.set("remote", state.remote ? "1" : "0");
  params.set("page", state.page);
  params.set("page_size", state.pageSize);

  try {
    const res = await fetch(`/api/jobs?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.totalPages = data.total_pages || 1;
    state.totalJobs = data.total || 0;

    // Update applied set
    state.appliedIds = new Set(data.items.filter(j => j.applied).map(j => j.id));

    document.getElementById("results-count").textContent =
      `Showing ${data.items.length} of ${data.total.toLocaleString()} results`;

    if (!data.items.length) {
      grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><div class="empty-icon">🔍</div><h3>No jobs found</h3><p>Try adjusting your filters</p></div>`;
    } else {
      renderJobCards(data.items);
      renderJobTable(data.items);
    }
    updatePagination();
    state.lastTimestamp = new Date().toISOString();
  } catch(e) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><div class="empty-icon">⚠️</div><h3>Failed to load jobs</h3><p>${e.message}</p></div>`;
  }
}


function getCategoryInfo(cat) {
  const map = {
    vendor: { icon: "🏭", label: "Vendor", cls: "badge-cat-vendor" },
    mssp: { icon: "🛡️", label: "MSSP", cls: "badge-cat-mssp" },
    consulting: { icon: "🏢", label: "Consulting", cls: "badge-cat-consulting" },
    indian_it: { icon: "🇮🇳", label: "Indian IT", cls: "badge-cat-indian-it" },
    government: { icon: "🏛️", label: "Govt", cls: "badge-cat-govt" },
    other: { icon: "💼", label: "Enterprise", cls: "badge-cat-other" },
  };
  return map[cat] || { icon: "💼", label: cat || "Enterprise", cls: "badge-cat-other" };
}

// ===== RENDER GRID =====
function renderJobCards(jobs) {
  const grid = document.getElementById("job-grid");
  grid.innerHTML = jobs.map(j => {
    const routes = j.application_routes || {};
    const directUrl = routes.direct_url || j.apply_url || "#";
        const seniority = j.seniority_level || "mid";
    const catInfo = getCategoryInfo(j.company_category);
    const seniorityLabel = { junior: "🟢 Junior", mid: "🔵 Mid", senior: "🟡 Senior", lead: "🟠 Lead", manager: "🔴 Manager" }[seniority] || seniority;
    const skills = (j.skills_required || []).slice(0, 4);
    const tags = (j.domain_tags || []).slice(0, 4);
    const isApplied = j.applied || state.appliedIds.has(j.id);
    const domain = extractDomain(directUrl);
    const logoUrl = domain ? `https://logo.clearbit.com/${domain}` : null;

    return `<div class="job-card ${j.is_target_match ? 'target-match' : ''} ${isApplied ? 'applied-job' : ''}" onclick="openJobModal('${j.id}')">
      <div class="card-top">
        <div class="company-logo">
          ${logoUrl ? `<img src="${logoUrl}" onerror="this.style.display='none';this.parentElement.textContent='🏢'" alt="${escapeHtml(j.company)}" />` : '🏢'}
        </div>
        <div class="card-title-block">
          <div class="card-title">${escapeHtml(j.title)}</div>
          <div class="card-company">${escapeHtml(j.company)}</div>
        </div>
      </div>

      <div class="card-meta">
        <span class="badge badge-type">${j.job_type || 'full-time'}</span>
        <span class="badge badge-seniority-${seniority}">${seniorityLabel}</span>
        <span class="badge ${catInfo.cls}">${catInfo.icon} ${catInfo.label}</span>
        ${j.salary_display ? `<span class="badge badge-salary">💰 ${escapeHtml(j.salary_display)}</span>` : ''}
        ${j.remote ? '<span class="badge badge-remote">🌍 Remote</span>' : ''}
        ${j.target_badge ? `<span class="badge badge-target">${j.target_badge}</span>` : ''}
        ${isApplied ? '<span class="badge badge-applied">✅ Applied</span>' : ''}
      </div>

      <div class="card-location">
        📍 ${escapeHtml(j.location || 'Remote')}
        ${j.salary_display ? ` &nbsp;•&nbsp; <span class="salary-text">💰 ${escapeHtml(j.salary_display)}</span>` : ''}
      </div>

      ${tags.length ? `<div class="domain-tags">${tags.map(t => `<span class="domain-tag">${escapeHtml(t)}</span>`).join("")}</div>` : ""}
      ${skills.length ? `<div class="skills-tags">${skills.map(s => `<span class="skill-tag">⚡ ${escapeHtml(s)}</span>`).join("")}</div>` : ""}

      <div class="card-actions" onclick="event.stopPropagation()">
        <a class="btn-card apply" href="${escapeHtml(directUrl)}" target="_blank" rel="noopener">🔗 Apply</a>
        <button class="btn-card ${isApplied ? 'mark-applied done' : 'mark-applied'}"
          onclick="${isApplied ? `unmarkApplied('${j.id}', this)` : `markApplied('${j.id}', this)`}">
          ${isApplied ? '✅ Applied' : '📋 Mark Applied'}
        </button>
        <button class="btn-card" onclick="copyLink('${escapeHtml(directUrl)}')" title="Copy link">📋</button>
      </div>
    </div>`;
  }).join("");
}

// ===== RENDER TABLE =====
function renderJobTable(jobs) {
  const tbody = document.getElementById("job-table-body");
  tbody.innerHTML = jobs.map(j => {
    const routes = j.application_routes || {};
    const directUrl = routes.direct_url || j.apply_url || "#";
    const seniority = j.seniority_level || "mid";
    const tags = (j.domain_tags || []).slice(0, 3).map(t => `<span class="domain-tag">${escapeHtml(t)}</span>`).join("");
    const isApplied = j.applied || state.appliedIds.has(j.id);
    return `<tr onclick="openJobModal('${j.id}')">
      <td class="td-title" data-label="Title">${escapeHtml(j.title)}</td>
      <td data-label="Company">${escapeHtml(j.company)}</td>
      <td class="td-location" data-label="Location">${escapeHtml(j.location || 'Remote')}</td>
      <td data-label="Type"><span class="badge badge-type">${j.job_type || 'full-time'}</span></td>
      <td data-label="Level"><span class="badge badge-seniority-${seniority}">${seniority}</span></td>
      <td data-label="Tags"><div style="display:flex;flex-wrap:wrap;gap:3px;">${tags}</div></td>
      <td data-label="Apply" onclick="event.stopPropagation()">
        <a class="btn-card apply" href="${escapeHtml(directUrl)}" target="_blank" rel="noopener" style="display:inline-flex;padding:4px 10px;font-size:0.75rem">Apply</a>
      </td>
      <td data-label="Applied?" onclick="event.stopPropagation()">
        ${isApplied
          ? `<button class="btn-sm" onclick="unmarkApplied('${j.id}', this)">✅ Applied</button>`
          : `<button class="btn-sm" onclick="markApplied('${j.id}', this)">Mark</button>`}
      </td>
    </tr>`;
  }).join("");
}

// ===== STATS & CHARTS =====
async function loadStats() {
  try {
    const res = await fetch("/api/stats");
    const s = await res.json();

    document.getElementById("kpi-total").textContent = (s.total || 0).toLocaleString();
    document.getElementById("kpi-target").textContent = (s.target_count || 0).toLocaleString();
    document.getElementById("kpi-india").textContent = (s.india_count || 0).toLocaleString();
    document.getElementById("kpi-globe").textContent = (s.global_remote_intern_count || 0).toLocaleString();
    document.getElementById("kpi-remote").textContent = `${s.remote_pct || 0}%`;
    document.getElementById("kpi-applied").textContent = (s.applied_count || 0).toLocaleString();

    renderCharts(s);
  } catch(e) { console.error("Stats load error:", e); }
}

function renderCharts(s) {
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  const textColor = isDark ? "#94a3b8" : "#475569";
  const gridColor = isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)";
  Chart.defaults.color = textColor;

  // Type chart
  const typeData = s.by_type || {};
  renderDoughnutChart("chart-type", Object.keys(typeData), Object.values(typeData), ["#00d488","#3b82f6","#a855f7","#f59e0b"]);

  // Domain chart
  const topDomains = s.top_domains || {};
  renderBarChart("chart-domain", Object.keys(topDomains).slice(0,8), Object.values(topDomains).slice(0,8), gridColor);

  // Timeline chart
  const history = (s.job_history || []);
  renderLineChart("chart-timeline", history.map(h => h.day), history.map(h => h.count), gridColor);

  // Seniority chart
  const seniorityData = s.by_seniority || {};
  const seniorityColors = { junior: "#22c55e", mid: "#3b82f6", senior: "#f59e0b", lead: "#f97316", manager: "#ef4444" };
  renderDoughnutChart("chart-seniority",
    Object.keys(seniorityData),
    Object.values(seniorityData),
    Object.keys(seniorityData).map(k => seniorityColors[k] || "#94a3b8")
  );
}

function renderDoughnutChart(id, labels, data, colors) {
  const ctx = document.getElementById(id);
  if (!ctx) return;
  if (state.charts[id]) state.charts[id].destroy();
  state.charts[id] = new Chart(ctx, {
    type: "doughnut",
    data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 0 }] },
    options: { responsive: true, plugins: { legend: { position: "bottom", labels: { font: { size: 11 }, padding: 8 } } }, cutout: "65%" }
  });
}
function renderBarChart(id, labels, data, gridColor) {
  const ctx = document.getElementById(id);
  if (!ctx) return;
  if (state.charts[id]) state.charts[id].destroy();
  state.charts[id] = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ data, backgroundColor: "rgba(0,212,136,0.6)", borderRadius: 4 }] },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { font: { size: 9 } }, grid: { color: gridColor } }, y: { grid: { color: gridColor } } } }
  });
}
function renderLineChart(id, labels, data, gridColor) {
  const ctx = document.getElementById(id);
  if (!ctx) return;
  if (state.charts[id]) state.charts[id].destroy();
  state.charts[id] = new Chart(ctx, {
    type: "line",
    data: { labels, datasets: [{ data, borderColor: "#00d488", backgroundColor: "rgba(0,212,136,0.1)", fill: true, tension: 0.4, pointRadius: 3 }] },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { font: { size: 9 }, maxTicksLimit: 8 }, grid: { color: gridColor } }, y: { grid: { color: gridColor } } } }
  });
}

// ===== DOMAINS & SOURCES =====
async function loadDomains() {
  try {
    const res = await fetch("/api/domains");
    const data = await res.json();
    const sel = document.getElementById("domain-select");
    const current = sel.value;
    sel.innerHTML = '<option value="">All Domains</option>' +
      (data.domains || []).slice(0, 30).map(d => `<option value="${escapeHtml(d.tag)}">${escapeHtml(d.tag)} (${d.count})</option>`).join("");
    sel.value = current;
  } catch(e) {}
}

async function loadSources() {
  try {
    const [srcRes, histRes] = await Promise.all([
      fetch("/api/sources"),
      fetch("/api/scrape/history")
    ]);
    const srcData = await srcRes.json();
    const histData = await histRes.json();

    const srcSel = document.getElementById("source-select");
    const currentSrc = srcSel.value;
    const sources = srcData.sources || [];
    srcSel.innerHTML = '<option value="">All Sources</option>' +
      sources.map(s => `<option value="${escapeHtml(s.source)}">${escapeHtml(s.source)} (${s.count})</option>`).join("");
    srcSel.value = currentSrc;

    // Source health drawer
    const content = document.getElementById("sources-content");
    if (sources.length) {
      content.innerHTML = sources.map(s => `
        <div class="source-item">
          <div class="source-name">${escapeHtml(s.source)}</div>
          <div class="source-meta">
            <span>${s.count} jobs</span>
            <span class="source-status">● Operational</span>
          </div>
          <div style="font-size:0.7rem;color:var(--text-muted)">Last: ${formatDate(s.last_seen)}</div>
        </div>`).join("");
    } else {
      content.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem">No sources loaded yet. Run a scrape!</p>';
    }

    // Scrape history
    const histEl = document.getElementById("scrape-history-list");
    const history = (histData.history || []).slice(0, 30);
    if (history.length) {
      histEl.innerHTML = history.map(h => `
        <div class="history-item">
          <span class="h-source">${escapeHtml(h.source)}</span>
          <span class="h-new">+${h.new_jobs}</span>
          <span class="h-time">${formatDate(h.run_at)}</span>
        </div>`).join("");
    } else {
      histEl.innerHTML = '<p style="color:var(--text-muted);font-size:0.78rem">No scrape runs yet.</p>';
    }
  } catch(e) {}
}

// ===== JOB MODAL =====
async function openJobModal(jobId) {
  const overlay = document.getElementById("job-modal-overlay");
  const body = document.getElementById("modal-body");
  overlay.classList.remove("hidden");
  body.innerHTML = '<div class="loading-text">Loading details...</div>';
  document.getElementById("modal-title").textContent = "Loading...";
  document.getElementById("modal-company").textContent = "";

  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) throw new Error("Job not found");
    const j = await res.json();
    const routes = j.application_routes || {};
    const isApplied = j.applied || state.appliedIds.has(j.id);
    const skills = j.skills_required || [];
    const tags = j.domain_tags || [];
    const seniority = j.seniority_level || "mid";
    const seniorityLabel = { junior: "🟢 Junior", mid: "🔵 Mid", senior: "🟡 Senior", lead: "🟠 Lead", manager: "🔴 Manager" }[seniority] || seniority;

    document.getElementById("modal-title").textContent = j.title;
    document.getElementById("modal-company").textContent = `${j.company} • ${j.location} • ${seniorityLabel}`;

    body.innerHTML = `
      <div class="job-detail-section">
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px">
          <span class="badge badge-type">${j.job_type || 'full-time'}</span>
          <span class="badge badge-seniority-${seniority}">${seniorityLabel}</span>
          ${j.remote ? '<span class="badge badge-remote">🌍 Remote</span>' : ''}
          ${j.target_badge ? `<span class="badge badge-target">${j.target_badge}</span>` : ''}
          ${isApplied ? '<span class="badge badge-applied">✅ Applied</span>' : ''}
        </div>
        ${tags.length ? `<div class="domain-tags" style="margin-bottom:8px">${tags.map(t => `<span class="domain-tag">${escapeHtml(t)}</span>`).join("")}</div>` : ""}
        ${skills.length ? `<div class="skills-tags">${skills.slice(0,10).map(s => `<span class="skill-tag">⚡ ${escapeHtml(s)}</span>`).join("")}</div>` : ""}
      </div>

      <div class="job-detail-section">
        <h4>🔗 Application Hub</h4>
        <div class="apply-hub">
          <a class="apply-btn primary" href="${escapeHtml(routes.direct_url || '#')}" target="_blank" rel="noopener">🎯 Direct Apply</a>
          <a class="apply-btn" href="${escapeHtml(routes.google_jobs_url || '#')}" target="_blank" rel="noopener">🔍 Google Jobs</a>
          <a class="apply-btn" href="${escapeHtml(routes.linkedin_jobs_url || '#')}" target="_blank" rel="noopener">💼 LinkedIn Search</a>
          <a class="apply-btn" href="${escapeHtml(routes.company_careers_url || '#')}" target="_blank" rel="noopener">🏢 Company Careers</a>
        </div>
      </div>

      <div class="job-detail-section">
        <h4>📄 Description</h4>
        <div class="job-description">${escapeHtml(j.description || "No description available.")}</div>
      </div>

      <div class="job-detail-section" style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn-action ${isApplied ? 'btn-primary' : ''}" id="modal-apply-btn"
          onclick="${isApplied ? `unmarkApplied('${j.id}', this)` : `markApplied('${j.id}', this)`}">
          ${isApplied ? '✅ Already Applied' : '📋 Mark as Applied'}
        </button>
        <button class="btn-action" onclick="copyLink('${escapeHtml(routes.direct_url || '')}')">📋 Copy Link</button>
        <span style="font-size:0.75rem;color:var(--text-muted);align-self:center">Source: ${escapeHtml(j.source || '')} • ${formatDate(j.discovered_at)}</span>
      </div>
    `;
  } catch(e) {
    body.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><h3>Error loading job</h3><p>${e.message}</p></div>`;
  }
}
function closeJobModal() {
  document.getElementById("job-modal-overlay").classList.add("hidden");
}

// ===== APPLICATION TRACKER =====
async function markApplied(jobId, btn) {
  try {
    const res = await fetch(`/api/applications/${jobId}/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
    if (!res.ok) throw new Error();
    state.appliedIds.add(jobId);
    if (btn) { btn.textContent = "✅ Applied"; btn.classList.add("done"); }
    showToast("✅ Marked as applied!");
    loadStats();
  } catch(e) { showToast("❌ Could not mark as applied", 3000); }
}
async function unmarkApplied(jobId, btn) {
  try {
    await fetch(`/api/applications/${jobId}`, { method: "DELETE" });
    state.appliedIds.delete(jobId);
    if (btn) { btn.textContent = "📋 Mark Applied"; btn.classList.remove("done"); }
    showToast("Removed from applied list.");
    loadStats();
  } catch(e) {}
}
async function showAppliedJobs() {
  const panel = document.getElementById("applied-panel");
  const overlay = document.getElementById("applied-overlay");
  panel.classList.remove("hidden");
  overlay.classList.remove("hidden");

  const list = document.getElementById("applied-list");
  list.innerHTML = '<div class="loading-text">Loading...</div>';

  try {
    const res = await fetch("/api/applications");
    const data = await res.json();
    const items = data.items || [];
    if (!items.length) {
      list.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><h3>No applications yet</h3><p>Mark jobs as Applied to track them here.</p></div>';
      return;
    }
    list.innerHTML = items.map(j => {
      const routes = j.application_routes || {};
      return `<div class="applied-item">
        <div class="applied-item-title">${escapeHtml(j.title)}</div>
        <div class="applied-item-company">${escapeHtml(j.company)} • ${escapeHtml(j.location || '')}</div>
        <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:8px">Applied: ${formatDate(j.applied_at)}</div>
        <div class="applied-item-actions">
          <a class="btn-sm" href="${escapeHtml(routes.direct_url || '#')}" target="_blank">🔗 Apply Again</a>
          <button class="btn-sm danger" onclick="unmarkApplied('${j.id}', this);this.closest('.applied-item').remove()">✕ Remove</button>
        </div>
      </div>`;
    }).join("");
  } catch(e) {
    list.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><h3>Error loading applications</h3></div>';
  }
}
function hideAppliedJobs() {
  document.getElementById("applied-panel").classList.add("hidden");
  document.getElementById("applied-overlay").classList.add("hidden");
}

// ===== SCRAPE =====
async function triggerScrape() {
  const btn = document.querySelector(".btn-primary");
  if (btn) { btn.disabled = true; btn.textContent = "⟳ Scraping..."; }
  try {
    const res = await fetch("/api/scrape", { method: "POST" });
    const data = await res.json();
    showToast(data.status === "initiated" ? "⚡ Scrape started! Watch for new job alerts." : `⚠️ ${data.message}`, 4000);
  } catch(e) {
    showToast("❌ Scrape trigger failed", 3000);
  } finally {
    setTimeout(() => {
      if (btn) { btn.disabled = false; btn.textContent = "⚡ Scrape Now"; }
    }, 8000);
  }
}

// ===== CSV EXPORT =====
function exportCSV() {
  const params = new URLSearchParams();
  if (state.search) params.set("search", state.search);
  if (state.type) params.set("type", state.type);
  if (state.domain) params.set("domain", state.domain);
  if (state.seniority) params.set("seniority", state.seniority);
  if (state.location_scope) params.set("location_scope", state.location_scope);
  window.open(`/api/export/csv?${params}`, "_blank");
}

// ===== DRAWERS / MODALS =====
function toggleSourcesDrawer() {
  const drawer = document.getElementById("sources-drawer");
  const overlay = document.getElementById("sources-overlay");
  const isHidden = drawer.classList.contains("hidden");
  drawer.classList.toggle("hidden", !isHidden);
  overlay.classList.toggle("hidden", !isHidden);
  if (isHidden) loadSources();
}
function toggleShortcutsModal(forceClose = false) {
  const modal = document.getElementById("shortcuts-modal");
  if (forceClose) { modal.classList.add("hidden"); return; }
  modal.classList.toggle("hidden");
}

// ===== UTILITIES =====
function showToast(msg, duration = 2500) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  setTimeout(() => t.classList.add("hidden"), duration);
}
function copyLink(url) {
  if (!url || url === "#") { showToast("⚠️ No link to copy", 2000); return; }
  navigator.clipboard.writeText(url).then(() => showToast("📋 Link copied!")).catch(() => showToast("❌ Could not copy"));
}
function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function extractDomain(url) {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "");
  } catch { return null; }
}
function formatDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const diff = Math.floor((Date.now() - d.getTime()) / 1000);
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
    return `${Math.floor(diff/86400)}d ago`;
  } catch { return iso.substring(0,10); }
}
