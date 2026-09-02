/**
 * CyberSec Intel Grid - Tactical Dashboard & Link Reliability Engine
 * High-performance SPA controller for cybersecurity career intelligence.
 */

const state = {
  search: "",
  type: "all",
  domain: "all",
  locationScope: "target", // "target", "all", "india", "global_remote_intern"
  remote: null,
  sort: "newest",
  page: 1,
  pageSize: 24,
  viewMode: "grid", // "grid" or "table"
  savedJobIds: new Set(JSON.parse(localStorage.getItem("saved_cyber_jobs") || "[]")),
  showSavedOnly: false,
  stats: null,
  sources: [],
  charts: {},
  activeModalJob: null,
  cachedJobs: []
};

// DOM Cache
const dom = {
  searchInput: document.getElementById("search-input"),
  clearSearch: document.getElementById("clear-search"),
  typeTabs: document.getElementById("type-tabs"),
  domainPills: document.getElementById("domain-pills"),
  remoteToggle: document.getElementById("remote-toggle"),
  sortSelect: document.getElementById("sort-select"),
  jobGrid: document.getElementById("job-grid"),
  jobTableContainer: document.getElementById("job-table-container"),
  jobTableBody: document.getElementById("job-table-body"),
  jobCountText: document.getElementById("job-count-text"),
  pagination: document.getElementById("pagination"),
  savedCountBadge: document.getElementById("saved-count-badge"),
  viewSavedBtn: document.getElementById("view-saved-btn"),
  scrapeBtn: document.getElementById("scrape-btn"),
  exportBtn: document.getElementById("export-btn"),
  analyticsToggle: document.getElementById("analytics-toggle"),
  analyticsDrawer: document.getElementById("analytics-drawer"),
  sourcesToggle: document.getElementById("sources-toggle"),
  sourcesDrawer: document.getElementById("sources-drawer"),
  sourcesGrid: document.getElementById("sources-grid"),
  jobModal: document.getElementById("job-modal"),
  modalContent: document.getElementById("modal-content"),
  shortcutsModal: document.getElementById("shortcuts-modal"),
  toast: document.getElementById("toast"),
  toastMessage: document.getElementById("toast-message"),
  systemStatusDot: document.getElementById("system-status-dot"),
  systemStatusText: document.getElementById("system-status-text"),
  viewGridBtn: document.getElementById("view-grid-btn"),
  viewTableBtn: document.getElementById("view-table-btn")
};

// Initialize Application
document.addEventListener("DOMContentLoaded", () => {
  readUrlParams();
  bindEvents();
  updateSavedBadge();
  loadStats();
  loadDomains();
  loadSources();
  loadJobs();
  checkStatus();
  setInterval(checkStatus, 15000);
});

// Sync State from/to URL Query Parameters
function readUrlParams() {
  const params = new URLSearchParams(window.location.search);
  if (params.has("q")) {
    state.search = params.get("q");
    if (dom.searchInput) dom.searchInput.value = state.search;
  }
  if (params.has("type")) state.type = params.get("type");
  if (params.has("domain")) state.domain = params.get("domain");
  if (params.has("scope")) state.locationScope = params.get("scope");
  if (params.has("sort")) state.sort = params.get("sort");
  if (params.has("page")) state.page = parseInt(params.get("page")) || 1;
  if (params.has("view")) state.viewMode = params.get("view");
  if (params.has("remote")) state.remote = params.get("remote") === "true";

  if (dom.remoteToggle) dom.remoteToggle.checked = !!state.remote;
  if (dom.sortSelect) dom.sortSelect.value = state.sort;
}

function syncUrlParams() {
  const params = new URLSearchParams();
  if (state.search) params.set("q", state.search);
  if (state.type !== "all") params.set("type", state.type);
  if (state.domain !== "all") params.set("domain", state.domain);
  if (state.locationScope !== "target") params.set("scope", state.locationScope);
  if (state.sort !== "newest") params.set("sort", state.sort);
  if (state.page > 1) params.set("page", state.page);
  if (state.viewMode !== "grid") params.set("view", state.viewMode);
  if (state.remote !== null) params.set("remote", state.remote);

  const newUrl = window.location.pathname + (params.toString() ? "?" + params.toString() : "");
  window.history.replaceState(null, "", newUrl);
}

// Bind Global UI Listeners
function bindEvents() {
  // Search Input with Debounce
  let debounceTimer;
  dom.searchInput.addEventListener("input", (e) => {
    clearTimeout(debounceTimer);
    state.search = e.target.value.trim();
    dom.clearSearch.classList.toggle("hidden", !state.search);
    debounceTimer = setTimeout(() => {
      state.page = 1;
      syncUrlParams();
      loadJobs();
    }, 280);
  });

  dom.clearSearch.addEventListener("click", () => {
    dom.searchInput.value = "";
    state.search = "";
    dom.clearSearch.classList.add("hidden");
    state.page = 1;
    syncUrlParams();
    loadJobs();
    dom.searchInput.focus();
  });

  // Remote Switch
  dom.remoteToggle.addEventListener("change", (e) => {
    state.remote = e.target.checked ? true : null;
    state.page = 1;
    syncUrlParams();
    loadJobs();
  });

  // Sort Selector
  dom.sortSelect.addEventListener("change", (e) => {
    state.sort = e.target.value;
    state.page = 1;
    syncUrlParams();
    loadJobs();
  });

  // Saved Bookmarks Button
  dom.viewSavedBtn.addEventListener("click", () => {
    state.showSavedOnly = !state.showSavedOnly;
    dom.viewSavedBtn.classList.toggle("bg-amber-500/20", state.showSavedOnly);
    dom.viewSavedBtn.classList.toggle("border-amber-500/60", state.showSavedOnly);
    state.page = 1;
    loadJobs();
  });

  // Analytics Drawer Toggle
  dom.analyticsToggle.addEventListener("click", () => {
    const isHidden = dom.analyticsDrawer.classList.toggle("hidden");
    dom.analyticsToggle.classList.toggle("border-cyan-500", !isHidden);
    dom.analyticsToggle.classList.toggle("bg-cyan-500/20", !isHidden);
    if (!isHidden && state.stats) {
      renderCharts(state.stats);
    }
  });

  // Sources Health Drawer Toggle
  dom.sourcesToggle.addEventListener("click", () => {
    const isHidden = dom.sourcesDrawer.classList.toggle("hidden");
    dom.sourcesToggle.classList.toggle("border-emerald-500", !isHidden);
    dom.sourcesToggle.classList.toggle("bg-emerald-500/20", !isHidden);
    if (!isHidden) {
      loadSources();
    }
  });

  // Trigger On-Demand Scraper
  dom.scrapeBtn.addEventListener("click", triggerScrape);

  // Export CSV
  dom.exportBtn.addEventListener("click", exportCurrentJobsCSV);

  // Global Keyboard Shortcuts
  document.addEventListener("keydown", handleKeyboardShortcuts);

  // Modal Backdrop Clicks
  dom.jobModal.addEventListener("click", (e) => {
    if (e.target === dom.jobModal) closeJobModal();
  });
  dom.shortcutsModal.addEventListener("click", (e) => {
    if (e.target === dom.shortcutsModal) toggleShortcutsModal();
  });
}

// Keyboard Shortcuts Router
function handleKeyboardShortcuts(e) {
  // If typing in search input, let Esc blur
  if (document.activeElement === dom.searchInput) {
    if (e.key === "Escape") {
      dom.searchInput.blur();
    }
    return;
  }

  if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    dom.searchInput.focus();
    dom.searchInput.select();
  } else if (e.key === "Escape") {
    if (!dom.jobModal.classList.contains("hidden")) {
      closeJobModal();
    } else if (!dom.shortcutsModal.classList.contains("hidden")) {
      toggleShortcutsModal();
    } else if (state.search) {
      resetFilters();
    }
  } else if (e.key === "1" && !e.ctrlKey && !e.metaKey) {
    setLocationScope(state.locationScope === "target" ? "all" : "target");
  } else if (e.key.toLowerCase() === "g" && !e.ctrlKey && !e.metaKey) {
    setViewMode("grid");
  } else if (e.key.toLowerCase() === "t" && !e.ctrlKey && !e.metaKey) {
    setViewMode("table");
  } else if (e.key === "?" || (e.shiftKey && e.key === "?")) {
    toggleShortcutsModal();
  }
}

// View Mode Switcher (Grid vs Table)
function setViewMode(mode) {
  state.viewMode = mode;
  syncUrlParams();

  const isGrid = mode === "grid";
  dom.jobGrid.classList.toggle("hidden", !isGrid);
  dom.jobTableContainer.classList.toggle("hidden", isGrid);

  dom.viewGridBtn.className = isGrid
    ? "px-2.5 py-1 rounded bg-slate-800 text-cyan-300 font-bold flex items-center gap-1"
    : "px-2.5 py-1 rounded text-slate-400 hover:text-slate-200 flex items-center gap-1";

  dom.viewTableBtn.className = !isGrid
    ? "px-2.5 py-1 rounded bg-slate-800 text-cyan-300 font-bold flex items-center gap-1"
    : "px-2.5 py-1 rounded text-slate-400 hover:text-slate-200 flex items-center gap-1";

  if (state.cachedJobs.length > 0) {
    if (isGrid) {
      renderJobCards(state.cachedJobs);
    } else {
      renderJobTable(state.cachedJobs);
    }
  }
}

// Check Backend Engine Status
async function checkStatus() {
  try {
    const res = await fetch("/api/status");
    if (res.ok) {
      const data = await res.json();
      dom.systemStatusDot.className = data.is_scraping 
        ? "w-2.5 h-2.5 rounded-full bg-amber-400 animate-ping" 
        : "w-2.5 h-2.5 rounded-full bg-emerald-400 pulse-emerald";
      dom.systemStatusText.textContent = data.is_scraping ? "Scraping In Progress..." : "System Nominal";
    }
  } catch (err) {
    dom.systemStatusDot.className = "w-2.5 h-2.5 rounded-full bg-rose-500";
    dom.systemStatusText.textContent = "Offline";
  }
}

// Load Telemetry & Stats
async function loadStats() {
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) return;
    const stats = await res.json();
    state.stats = stats;

    document.getElementById("stat-total-jobs").textContent = (stats.total || 0).toLocaleString();
    document.getElementById("stat-internships").textContent = (stats.internships || 0).toLocaleString();

    // Target telemetry counters
    if (document.getElementById("stat-target-matches")) {
      document.getElementById("stat-target-matches").textContent = (stats.target_count || 0).toLocaleString();
    }
    if (document.getElementById("stat-india-jobs")) {
      document.getElementById("stat-india-jobs").textContent = (stats.india_count || 0).toLocaleString();
    }
    if (document.getElementById("stat-global-remote-interns")) {
      document.getElementById("stat-global-remote-interns").textContent = (stats.global_remote_intern_count || 0).toLocaleString();
    }
    if (document.getElementById("target-count-badge")) {
      document.getElementById("target-count-badge").textContent = (stats.target_count || 0).toLocaleString();
    }
    if (document.getElementById("india-count-badge")) {
      document.getElementById("india-count-badge").textContent = (stats.india_count || 0).toLocaleString();
    }
    if (document.getElementById("global-intern-count-badge")) {
      document.getElementById("global-intern-count-badge").textContent = (stats.global_remote_intern_count || 0).toLocaleString();
    }

    if (stats.last_scraped) {
      const date = new Date(stats.last_scraped);
      document.getElementById("stat-last-sync").textContent = date.toLocaleDateString(undefined, { 
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" 
      });
    }

    if (!dom.analyticsDrawer.classList.contains("hidden")) {
      renderCharts(stats);
    }
  } catch (e) {
    console.error("Failed to load stats:", e);
  }
}

// Load Feeder Sources Health
async function loadSources() {
  try {
    const res = await fetch("/api/sources");
    if (!res.ok) return;
    const data = await res.json();
    state.sources = data.sources || [];

    dom.sourcesGrid.innerHTML = state.sources.map(s => {
      const lastSeenStr = s.last_seen ? timeAgo(new Date(s.last_seen)) : "Active";
      return `
        <div class="p-3 rounded-xl bg-slate-950/80 border border-slate-800 flex items-center justify-between">
          <div class="truncate mr-2">
            <div class="flex items-center gap-1.5">
              <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
              <span class="text-xs font-bold text-slate-200 truncate">${escapeHtml(s.source)}</span>
            </div>
            <span class="text-[10px] text-slate-500 block mt-0.5 font-mono">Discovered: ${lastSeenStr}</span>
          </div>
          <span class="px-2 py-0.5 rounded text-[11px] font-mono bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 flex-shrink-0">
            ${s.count} roles
          </span>
        </div>
      `;
    }).join("");
  } catch (e) {
    console.error("Failed to load sources:", e);
  }
}

// Select Location Scope filter
function setLocationScope(scope) {
  state.locationScope = scope;
  state.page = 1;
  syncUrlParams();
  document.querySelectorAll("#location-scope-tabs button").forEach(btn => {
    const active = btn.getAttribute("data-scope") === scope;
    btn.className = `px-3 py-1.5 rounded-lg text-xs font-mono transition-all flex items-center gap-1.5 ${
      active 
        ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/60 font-bold shadow-sm"
        : "text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-transparent"
    }`;
  });
  loadJobs();
}

// Render Telemetry Charts
function renderCharts(stats) {
  const ctxType = document.getElementById("chart-job-types");
  if (ctxType) {
    if (state.charts.types) state.charts.types.destroy();
    const typeLabels = Object.keys(stats.by_type || {});
    const typeCounts = Object.values(stats.by_type || {});

    state.charts.types = new Chart(ctxType, {
      type: "doughnut",
      data: {
        labels: typeLabels.map(l => l.charAt(0).toUpperCase() + l.slice(1)),
        datasets: [{
          data: typeCounts,
          backgroundColor: ["#10b981", "#06b6d4", "#f59e0b", "#8b5cf6"],
          borderColor: "#0f172a",
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { color: "#94a3b8", font: { family: "Plus Jakarta Sans", size: 12 } } }
        },
        cutout: "70%"
      }
    });
  }

  const ctxDomain = document.getElementById("chart-domains");
  if (ctxDomain) {
    if (state.charts.domains) state.charts.domains.destroy();
    const domainLabels = Object.keys(stats.top_domains || {});
    const domainCounts = Object.values(stats.top_domains || {});

    state.charts.domains = new Chart(ctxDomain, {
      type: "bar",
      data: {
        labels: domainLabels.map(l => l.toUpperCase()),
        datasets: [{
          label: "Active Roles",
          data: domainCounts,
          backgroundColor: "rgba(6, 182, 212, 0.4)",
          borderColor: "#06b6d4",
          borderWidth: 1.5,
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#64748b", font: { family: "JetBrains Mono", size: 10 } }, grid: { display: false } },
          y: { ticks: { color: "#64748b", font: { family: "JetBrains Mono", size: 10 } }, grid: { color: "rgba(51, 65, 85, 0.3)" } }
        }
      }
    });
  }
}

// Load Domain Pills
async function loadDomains() {
  try {
    const res = await fetch("/api/domains");
    if (!res.ok) return;
    const data = await res.json();
    const domains = data.domains || [];

    let pillsHtml = `
      <button onclick="setDomain('all')" class="badge-domain px-3 py-1 rounded-lg text-xs font-mono transition-all ${
        state.domain === "all" ? "bg-cyan-500/20 text-cyan-300 border-cyan-500 font-bold" : "text-slate-400"
      }">
        ALL SPECIALIZATIONS
      </button>
    `;

    pillsHtml += domains.slice(0, 14).map(d => `
      <button onclick="setDomain('${escapeHtml(d.tag)}')" class="badge-domain px-2.5 py-1 rounded-lg text-xs font-mono transition-all ${
        state.domain === d.tag ? "bg-cyan-500/20 text-cyan-300 border-cyan-500 font-bold" : "text-slate-400"
      }">
        #${escapeHtml(d.tag.replace(/\s+/g, ""))} (${d.count})
      </button>
    `).join("");

    dom.domainPills.innerHTML = pillsHtml;
  } catch (err) {
    console.error("Failed to load domains:", err);
  }
}

function setDomain(tag) {
  state.domain = tag;
  state.page = 1;
  syncUrlParams();
  loadDomains();
  loadJobs();
}

function setJobType(type) {
  state.type = type;
  state.page = 1;
  syncUrlParams();
  document.querySelectorAll("#type-tabs button").forEach(btn => {
    const active = btn.getAttribute("data-type") === type;
    btn.className = `px-4 py-2 text-xs font-semibold rounded-lg transition-all font-mono ${
      active 
        ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/50 shadow-sm" 
        : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent"
    }`;
  });
  loadJobs();
}

// Load Jobs Feed
async function loadJobs() {
  const loadingHtml = `
    <div class="col-span-full py-16 flex flex-col items-center justify-center text-slate-500">
      <svg class="animate-spin h-8 w-8 text-cyan-500 mb-3" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
      </svg>
      <p class="font-mono text-xs uppercase tracking-wider">Querying Cyber Intelligence Matrix...</p>
    </div>
  `;
  dom.jobGrid.innerHTML = loadingHtml;
  dom.jobTableBody.innerHTML = `<tr><td colspan="6" class="p-8 text-center">${loadingHtml}</td></tr>`;

  try {
    const params = new URLSearchParams({
      search: state.search,
      type: state.type,
      domain: state.domain,
      location_scope: state.locationScope,
      sort: state.sort,
      page: state.page,
      page_size: state.pageSize
    });
    if (state.remote !== null) {
      params.append("remote", state.remote);
    }

    const res = await fetch(`/api/jobs?${params.toString()}`);
    if (!res.ok) throw new Error("API query failed");
    const data = await res.json();

    let jobs = data.items || [];
    state.cachedJobs = jobs;

    // Filter by bookmarks if toggled
    if (state.showSavedOnly) {
      jobs = jobs.filter(j => state.savedJobIds.has(j.id));
      dom.jobCountText.textContent = `Showing ${jobs.length} Bookmarked Cybersecurity Opportunities`;
    } else {
      const scopeLabel = state.locationScope === "target" 
        ? " [🎯 Target: India Cyber (Office/WFH) + Global Online Cyber Internships]" 
        : state.locationScope === "india" 
        ? " [🇮🇳 India Cyber Roles]" 
        : state.locationScope === "global_remote_intern" 
        ? " [💻 Global Online Cyber Internships]" 
        : " [🌐 All Global Cyber Roles]";
      dom.jobCountText.textContent = `Showing ${(data.total === 0 ? 0 : (data.page - 1) * data.page_size + 1)}–${Math.min(data.page * data.page_size, data.total)} of ${data.total.toLocaleString()} cybersecurity positions${scopeLabel}`;
    }

    if (state.viewMode === "grid") {
      renderJobCards(jobs);
    } else {
      renderJobTable(jobs);
    }
    renderPagination(data.total, data.page, data.total_pages);
  } catch (err) {
    console.error("Job load error:", err);
    const errHtml = `
      <div class="col-span-full py-12 text-center text-rose-400">
        <p class="font-bold">Error loading cybersecurity jobs</p>
        <p class="text-xs text-slate-500 mt-1">${err.message}</p>
        <button onclick="loadJobs()" class="mt-4 px-4 py-1.5 bg-slate-800 text-xs rounded border border-slate-700 hover:bg-slate-700 text-slate-300">
          Retry
        </button>
      </div>
    `;
    dom.jobGrid.innerHTML = errHtml;
    dom.jobTableBody.innerHTML = `<tr><td colspan="6" class="p-8 text-center text-rose-400">${errHtml}</td></tr>`;
  }
}

// Render Job Cards Matrix (Grid View)
function renderJobCards(jobs) {
  if (!jobs || jobs.length === 0) {
    dom.jobGrid.innerHTML = `
      <div class="col-span-full py-16 text-center text-slate-500 hud-card rounded-xl p-8 border border-slate-800">
        <svg class="w-12 h-12 mx-auto text-slate-600 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
        </svg>
        <h3 class="text-base font-semibold text-slate-300">No matching cybersecurity positions located</h3>
        <p class="text-xs text-slate-500 mt-1 max-w-sm mx-auto">Try switching to "All Global Cyber Roles" or clearing specific specialization filters.</p>
        <button onclick="resetFilters()" class="mt-4 px-4 py-2 bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 text-xs rounded-lg hover:bg-cyan-500/20 transition-all font-mono">
          Reset Filter Matrix
        </button>
      </div>
    `;
    return;
  }

  dom.jobGrid.innerHTML = jobs.map(job => {
    const isSaved = state.savedJobIds.has(job.id);
    const isInternship = job.job_type === "internship";
    const isContract = job.job_type === "contract";

    const typeBadgeClass = isInternship
      ? "bg-amber-500/15 text-amber-300 border-amber-500/30"
      : isContract
      ? "bg-purple-500/15 text-purple-300 border-purple-500/30"
      : "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";

    const typeLabel = isInternship ? "🎓 Internship" : isContract ? "📝 Contract" : "💼 Full-Time";

    const targetBadgeHtml = job.target_badge ? `
      <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${
        job.is_india 
          ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40" 
          : "bg-purple-500/15 text-purple-300 border-purple-500/40"
      }">
        ${escapeHtml(job.target_badge)}
      </span>
    ` : "";

    const locationText = job.remote 
      ? `🌍 ${job.location || "Remote"} (Remote)` 
      : `🏢 ${job.location || "Onsite"}`;

    const tags = (job.domain_tags || []).slice(0, 3);
    const tagsHtml = tags.map(t => `
      <span class="badge-domain text-[11px] px-2 py-0.5 rounded font-mono">
        #${escapeHtml(t.replace(/\s+/g, ""))}
      </span>
    `).join("");

    const formattedDate = job.discovered_at 
      ? timeAgo(new Date(job.discovered_at))
      : "Recently";

    const routes = job.application_routes || {};

    return `
      <div class="hud-card rounded-xl p-5 flex flex-col justify-between group relative border border-slate-800">
        <div>
          <!-- Top Row: Type, Target & Save -->
          <div class="flex items-start justify-between gap-2 mb-3">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="text-[11px] font-mono px-2.5 py-0.5 rounded-full border ${typeBadgeClass}">
                ${typeLabel}
              </span>
              ${targetBadgeHtml}
            </div>
            <div class="flex items-center gap-1.5 flex-shrink-0">
              <span class="text-[10px] font-mono text-slate-500">${formattedDate}</span>
              <button onclick="toggleBookmark('${escapeHtml(job.id)}', event)" 
                title="${isSaved ? "Remove Bookmark" : "Bookmark Job"}"
                class="p-1 rounded text-slate-400 hover:text-amber-400 transition-colors">
                <svg class="w-4 h-4 ${isSaved ? "text-amber-400 fill-amber-400" : ""}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/>
                </svg>
              </button>
            </div>
          </div>

          <!-- Job Title & Company -->
          <h3 class="text-base font-bold text-white group-hover:text-cyan-400 transition-colors leading-snug line-clamp-2 cursor-pointer" onclick="openJobModal('${escapeHtml(job.id)}')">
            ${escapeHtml(job.title)}
          </h3>
          <div class="mt-1 flex items-center gap-2 text-xs font-semibold text-slate-300">
            <span class="truncate max-w-[180px] text-cyan-300">${escapeHtml(job.company)}</span>
            <span class="text-slate-600">•</span>
            <span class="truncate text-slate-400 max-w-[140px]">${escapeHtml(locationText)}</span>
          </div>

          <!-- Domain Tags -->
          <div class="mt-3 flex flex-wrap gap-1.5">
            ${tagsHtml || '<span class="text-[10px] font-mono text-slate-600">#cybersecurity</span>'}
          </div>
        </div>

        <!-- Action Footer with Direct ATS & Redundant Fallback Search -->
        <div class="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between gap-2">
          <span class="text-[10px] font-mono text-slate-500 truncate max-w-[100px]" title="Source: ${escapeHtml(job.source)}">
            ${escapeHtml(job.source)}
          </span>
          <div class="flex items-center gap-1.5">
            <button onclick="openJobModal('${escapeHtml(job.id)}')" 
              class="px-2.5 py-1.5 text-xs text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-700/80 rounded border border-slate-700 transition-all font-mono">
              Inspect
            </button>
            <a href="${escapeHtml(routes.direct_url || job.apply_url || '#')}" target="_blank" rel="noopener noreferrer" 
              class="px-3 py-1.5 text-xs font-bold text-slate-950 bg-cyan-400 hover:bg-cyan-300 rounded font-mono flex items-center gap-1 transition-all shadow-sm">
              Apply
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/>
              </svg>
            </a>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

// Render Job High-Density Table View
function renderJobTable(jobs) {
  if (!jobs || jobs.length === 0) {
    dom.jobTableBody.innerHTML = `
      <tr>
        <td colspan="6" class="p-12 text-center text-slate-500">
          No matching cybersecurity positions found in table view.
        </td>
      </tr>
    `;
    return;
  }

  dom.jobTableBody.innerHTML = jobs.map(job => {
    const isSaved = state.savedJobIds.has(job.id);
    const routes = job.application_routes || {};
    const tags = (job.domain_tags || []).slice(0, 2);
    const tagsHtml = tags.map(t => `<span class="badge-domain text-[10px] px-1.5 py-0.2 rounded font-mono">#${escapeHtml(t.replace(/\s+/g, ""))}</span>`).join(" ");
    const formattedDate = job.discovered_at ? timeAgo(new Date(job.discovered_at)) : "Recently";

    return `
      <tr class="hover:bg-slate-850/60 transition-colors group">
        <td class="p-3.5">
          <div class="font-bold text-white group-hover:text-cyan-400 cursor-pointer text-xs" onclick="openJobModal('${escapeHtml(job.id)}')">
            ${escapeHtml(job.title)}
          </div>
          <div class="flex items-center gap-2 mt-1">
            <span class="text-[10px] text-slate-400 font-mono">${escapeHtml(job.job_type)}</span>
            ${job.target_badge ? `<span class="text-[9px] px-1.5 py-0.2 rounded font-mono bg-cyan-500/10 text-cyan-300 border border-cyan-500/30">${escapeHtml(job.target_badge)}</span>` : ""}
          </div>
        </td>
        <td class="p-3.5 font-semibold text-slate-300 text-xs">
          ${escapeHtml(job.company)}
        </td>
        <td class="p-3.5 text-slate-400 text-xs truncate max-w-[150px]">
          ${job.remote ? "🌍 Remote" : "🏢 " + escapeHtml(job.location || "Onsite")}
        </td>
        <td class="p-3.5">
          ${tagsHtml || '<span class="text-[10px] text-slate-600 font-mono">#security</span>'}
        </td>
        <td class="p-3.5 text-[11px] text-slate-500 font-mono">
          ${formattedDate}
        </td>
        <td class="p-3.5 text-right">
          <div class="flex items-center justify-end gap-1.5">
            <button onclick="toggleBookmark('${escapeHtml(job.id)}', event)" class="p-1.5 text-slate-400 hover:text-amber-400 rounded">
              <svg class="w-4 h-4 ${isSaved ? "text-amber-400 fill-amber-400" : ""}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/>
              </svg>
            </button>
            <button onclick="openJobModal('${escapeHtml(job.id)}')" class="px-2 py-1 bg-slate-800 text-[11px] text-slate-300 hover:text-white rounded border border-slate-700">
              Inspect
            </button>
            <a href="${escapeHtml(routes.direct_url || job.apply_url)}" target="_blank" rel="noopener noreferrer" 
              class="px-2.5 py-1 bg-cyan-400 text-slate-950 font-bold text-[11px] rounded hover:bg-cyan-300">
              Apply
            </a>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

// Render Pagination
function renderPagination(total, currentPage, totalPages) {
  if (totalPages <= 1) {
    dom.pagination.innerHTML = "";
    return;
  }

  let html = `
    <button onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? "disabled" : ""}
      class="px-3 py-1.5 text-xs font-mono rounded bg-slate-800 text-slate-300 border border-slate-700 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-700">
      ← Prev
    </button>
    <span class="text-xs font-mono text-slate-400 px-2">Page ${currentPage} of ${totalPages}</span>
    <button onclick="goToPage(${currentPage + 1})" ${currentPage === totalPages ? "disabled" : ""}
      class="px-3 py-1.5 text-xs font-mono rounded bg-slate-800 text-slate-300 border border-slate-700 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-700">
      Next →
    </button>
  `;

  dom.pagination.innerHTML = html;
}

function goToPage(p) {
  state.page = p;
  syncUrlParams();
  loadJobs();
  window.scrollTo({ top: 380, behavior: "smooth" });
}

// Open Job Inspection & Application Hub Modal
async function openJobModal(jobId) {
  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) throw new Error("Failed to fetch job details");
    const job = await res.json();
    state.activeModalJob = job;

    const isSaved = state.savedJobIds.has(job.id);
    const tags = job.domain_tags || [];
    const tagsHtml = tags.map(t => `<span class="badge-domain text-xs px-2.5 py-1 rounded font-mono">#${escapeHtml(t)}</span>`).join("");
    const routes = job.application_routes || {};

    dom.modalContent.innerHTML = `
      <div class="flex items-start justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <div class="flex items-center gap-2 flex-wrap mb-1">
            <span class="text-xs font-mono uppercase tracking-wider text-cyan-400 font-bold">${escapeHtml(job.job_type || "Full-Time")}</span>
            ${job.target_badge ? `<span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${job.is_india ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" : "bg-purple-500/20 text-purple-300 border-purple-500/40"}">${escapeHtml(job.target_badge)}</span>` : ""}
          </div>
          <h2 class="text-xl font-bold text-white">${escapeHtml(job.title)}</h2>
          <p class="text-sm font-semibold text-slate-300 mt-0.5">
            <span class="text-cyan-400">Company:</span> ${escapeHtml(job.company)} 
            <span class="text-slate-500 mx-2">•</span> 
            <span class="text-slate-400">${escapeHtml(job.location || "Remote")}</span>
          </p>
        </div>
        <button onclick="closeJobModal()" class="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <!-- Application Routes & Fallback Hub (Redundant Link Architecture) -->
      <div class="p-3.5 my-3 rounded-xl bg-slate-900/90 border border-slate-800 space-y-2.5">
        <div class="flex items-center justify-between">
          <span class="text-xs font-mono uppercase tracking-wider font-bold text-cyan-300 flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-cyan-400"></span> Guaranteed Application Routes Hub
          </span>
          <span class="text-[10px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30">Auto-Resolved</span>
        </div>
        
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs font-mono">
          <!-- Primary Direct ATS -->
          <a href="${escapeHtml(routes.direct_url || job.apply_url)}" target="_blank" rel="noopener noreferrer"
            class="p-2.5 rounded-lg bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/40 text-cyan-200 flex items-center justify-between transition-all group">
            <span class="font-bold flex items-center gap-1.5 truncate">
              ⚡ Primary Direct ATS Apply
            </span>
            <svg class="w-4 h-4 text-cyan-400 group-hover:translate-x-0.5 transition-transform flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/>
            </svg>
          </a>

          <!-- Google Jobs Search Fallback -->
          <a href="${escapeHtml(routes.google_jobs_url)}" target="_blank" rel="noopener noreferrer"
            class="p-2.5 rounded-lg bg-slate-850 hover:bg-slate-800 border border-slate-700 text-slate-300 hover:text-white flex items-center justify-between transition-all">
            <span class="truncate">🔍 Google Jobs Search</span>
            <span class="text-[10px] text-slate-500">Fallback</span>
          </a>

          <!-- LinkedIn Jobs Search Fallback -->
          <a href="${escapeHtml(routes.linkedin_jobs_url)}" target="_blank" rel="noopener noreferrer"
            class="p-2.5 rounded-lg bg-slate-850 hover:bg-slate-800 border border-slate-700 text-slate-300 hover:text-white flex items-center justify-between transition-all">
            <span class="truncate">💼 LinkedIn Jobs Search</span>
            <span class="text-[10px] text-slate-500">Fallback</span>
          </a>

          <!-- Company Careers Search Fallback -->
          <a href="${escapeHtml(routes.company_careers_url)}" target="_blank" rel="noopener noreferrer"
            class="p-2.5 rounded-lg bg-slate-850 hover:bg-slate-800 border border-slate-700 text-slate-300 hover:text-white flex items-center justify-between transition-all">
            <span class="truncate">🏢 Company Portal Search</span>
            <span class="text-[10px] text-slate-500">Fallback</span>
          </a>
        </div>
      </div>

      <!-- Metadata Strip -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5 py-3 border-b border-slate-800 text-xs font-mono">
        <div class="bg-slate-900/60 p-2.5 rounded border border-slate-800">
          <span class="text-slate-500 block text-[10px]">Work Mode</span>
          <span class="text-slate-200 font-bold">${job.remote ? "🌍 Remote" : "🏢 Onsite"}</span>
        </div>
        <div class="bg-slate-900/60 p-2.5 rounded border border-slate-800">
          <span class="text-slate-500 block text-[10px]">Discovered</span>
          <span class="text-slate-200 font-bold">${timeAgo(new Date(job.discovered_at))}</span>
        </div>
        <div class="bg-slate-900/60 p-2.5 rounded border border-slate-800">
          <span class="text-slate-500 block text-[10px]">Source Engine</span>
          <span class="text-slate-200 font-bold truncate">${escapeHtml(job.source)}</span>
        </div>
        <div class="bg-slate-900/60 p-2.5 rounded border border-slate-800">
          <span class="text-slate-500 block text-[10px]">Fingerprint ID</span>
          <span class="text-slate-400 font-mono text-[10px] truncate">${escapeHtml(job.hash || job.id)}</span>
        </div>
      </div>

      <!-- Domain Tags -->
      <div class="py-3 border-b border-slate-800">
        <span class="text-[11px] font-mono uppercase text-slate-400 block mb-1.5">Classified Cybersecurity Specializations:</span>
        <div class="flex flex-wrap gap-1.5">
          ${tagsHtml || '<span class="text-xs text-slate-500 font-mono">#cybersecurity</span>'}
        </div>
      </div>

      <!-- Job Description Body -->
      <div class="py-3 max-h-[300px] overflow-y-auto pr-2 space-y-2 text-sm text-slate-300 leading-relaxed font-sans">
        <h3 class="text-[11px] font-mono uppercase tracking-wider text-slate-400">Position Brief / Description:</h3>
        <div class="whitespace-pre-wrap bg-slate-900/40 p-4 rounded-lg border border-slate-800/80 text-xs font-mono leading-normal text-slate-300">
          ${escapeHtml(job.description || "Direct ATS application provided via the Guaranteed Application Routes above.")}
        </div>
      </div>

      <!-- Modal Action Footer -->
      <div class="pt-3 border-t border-slate-800 flex items-center justify-between gap-3 flex-wrap">
        <div class="flex items-center gap-2">
          <button onclick="toggleBookmark('${escapeHtml(job.id)}', event)" 
            class="px-3.5 py-2 text-xs font-mono rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 flex items-center gap-1.5">
            <svg class="w-4 h-4 ${isSaved ? "text-amber-400 fill-amber-400" : ""}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
            </svg>
            ${isSaved ? "Saved" : "Save"}
          </button>
          <button onclick="copyApplyLink('${escapeHtml(routes.direct_url || job.apply_url)}')" 
            class="px-3.5 py-2 text-xs font-mono rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 flex items-center gap-1.5">
            📋 Copy Apply Link
          </button>
        </div>

        <a href="${escapeHtml(routes.direct_url || job.apply_url)}" target="_blank" rel="noopener noreferrer" 
          class="px-5 py-2.5 text-xs font-bold text-slate-950 bg-cyan-400 hover:bg-cyan-300 rounded-lg font-mono flex items-center gap-2 shadow-lg shadow-cyan-500/20">
          Open Official ATS Application
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
          </svg>
        </a>
      </div>
    `;

    dom.jobModal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
  } catch (err) {
    showToast("Failed to open job details", "error");
  }
}

function closeJobModal() {
  dom.jobModal.classList.add("hidden");
  document.body.style.overflow = "";
}

function toggleShortcutsModal() {
  dom.shortcutsModal.classList.toggle("hidden");
}

// Copy link helper
function copyApplyLink(url) {
  navigator.clipboard.writeText(url).then(() => {
    showToast("Apply link copied to clipboard! 📋");
  }).catch(() => {
    showToast("Failed to copy link", "error");
  });
}

// Bookmarking Handler
function toggleBookmark(jobId, event) {
  if (event) event.stopPropagation();
  if (state.savedJobIds.has(jobId)) {
    state.savedJobIds.delete(jobId);
    showToast("Removed from saved bookmarks");
  } else {
    state.savedJobIds.add(jobId);
    showToast("Saved to bookmarks ⭐");
  }
  localStorage.setItem("saved_cyber_jobs", JSON.stringify(Array.from(state.savedJobIds)));
  updateSavedBadge();
  if (state.showSavedOnly) loadJobs();
  else {
    // Re-render to update star icon
    if (state.viewMode === "grid") renderJobCards(state.cachedJobs);
    else renderJobTable(state.cachedJobs);
  }
}

function updateSavedBadge() {
  dom.savedCountBadge.textContent = state.savedJobIds.size;
}

// On-Demand Scraper Trigger
async function triggerScrape() {
  try {
    dom.scrapeBtn.disabled = true;
    dom.scrapeBtn.innerHTML = `
      <svg class="animate-spin h-3.5 w-3.5 text-slate-950" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
      </svg>
      <span>Extracting...</span>
    `;

    const res = await fetch("/api/scrape", { method: "POST" });
    const data = await res.json();

    if (res.ok) {
      showToast("Scraper cycle triggered! Telemetry updating in background.");
      checkStatus();
      setTimeout(() => {
        loadStats();
        loadSources();
        loadJobs();
      }, 5000);
    } else {
      showToast(data.message || "Scraper busy", "info");
    }
  } catch (err) {
    showToast("Failed to start scraper", "error");
  } finally {
    setTimeout(() => {
      dom.scrapeBtn.disabled = false;
      dom.scrapeBtn.innerHTML = `
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
        </svg>
        <span>Trigger Scrape</span>
      `;
    }, 3000);
  }
}

// Export CSV of Currently Filtered Opportunities
async function exportCurrentJobsCSV() {
  try {
    showToast("Generating CSV export...");
    const params = new URLSearchParams({
      search: state.search,
      type: state.type,
      domain: state.domain,
      location_scope: state.locationScope,
      sort: state.sort,
      page: 1,
      page_size: 1000
    });
    if (state.remote !== null) params.append("remote", state.remote);

    const res = await fetch(`/api/jobs?${params.toString()}`);
    if (!res.ok) throw new Error("Export fetch failed");
    const data = await res.json();
    const rows = data.items || [];

    if (rows.length === 0) {
      showToast("No jobs matching current filters to export", "info");
      return;
    }

    const headers = ["Title", "Company", "Location", "Remote", "Type", "Domain Tags", "Source", "Direct Apply URL", "Google Jobs Link", "LinkedIn Link", "Discovered"];
    const csvContent = [
      headers.join(","),
      ...rows.map(r => {
        const routes = r.application_routes || {};
        return [
          `"${(r.title || "").replace(/"/g, """")}"`,
          `"${(r.company || "").replace(/"/g, """")}"`,
          `"${(r.location || "").replace(/"/g, """")}"`,
          r.remote ? "Yes" : "No",
          r.job_type,
          `"${(r.domain_tags || []).join(";")}"`,
          r.source,
          `"${routes.direct_url || r.apply_url}"`,
          `"${routes.google_jobs_url || ""}"`,
          `"${routes.linkedin_jobs_url || ""}"`,
          r.discovered_at
        ].join(",");
      })
    ].join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `cybersecurity_jobs_${new Date().toISOString().slice(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast("CSV export downloaded! 📁");
  } catch (e) {
    showToast("Export failed", "error");
  }
}

// Toast Feedback
function showToast(msg, type = "info") {
  dom.toastMessage.textContent = msg;
  dom.toast.classList.remove("hidden");
  setTimeout(() => {
    dom.toast.classList.add("hidden");
  }, 3500);
}

// Helpers
function resetFilters() {
  state.search = "";
  state.type = "all";
  state.domain = "all";
  state.locationScope = "target";
  state.remote = null;
  state.sort = "newest";
  state.page = 1;
  state.showSavedOnly = false;
  dom.searchInput.value = "";
  dom.clearSearch.classList.add("hidden");
  dom.remoteToggle.checked = false;
  dom.sortSelect.value = "newest";
  setJobType("all");
  setLocationScope("target");
  loadDomains();
  loadJobs();
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function timeAgo(date) {
  if (isNaN(date.getTime())) return "Recently";
  const seconds = Math.floor((new Date() - date) / 1000);
  const intervals = [
    { label: "yr", seconds: 31536000 },
    { label: "mo", seconds: 2592000 },
    { label: "d", seconds: 86400 },
    { label: "h", seconds: 3600 },
    { label: "m", seconds: 60 }
  ];
  for (const interval of intervals) {
    const count = Math.floor(seconds / interval.seconds);
    if (count >= 1) return `${count}${interval.label} ago`;
  }
  return "Just now";
}
