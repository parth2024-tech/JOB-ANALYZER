/**
 * CyberSec Job Scraper - Tactical Dashboard Controller
 * Handles live queries, analytics charts, modals, bookmarks, and on-demand scraping.
 */

const state = {
  search: '',
  type: 'all',
  domain: 'all',
  remote: null,
  sort: 'newest',
  page: 1,
  pageSize: 24,
  savedJobIds: new Set(JSON.parse(localStorage.getItem('saved_cyber_jobs') || '[]')),
  showSavedOnly: false,
  stats: null,
  charts: {},
  activeModalJob: null
};

// DOM references
const dom = {
  searchInput: document.getElementById('search-input'),
  clearSearch: document.getElementById('clear-search'),
  typeTabs: document.getElementById('type-tabs'),
  domainPills: document.getElementById('domain-pills'),
  remoteToggle: document.getElementById('remote-toggle'),
  sortSelect: document.getElementById('sort-select'),
  jobGrid: document.getElementById('job-grid'),
  jobCountText: document.getElementById('job-count-text'),
  pagination: document.getElementById('pagination'),
  savedCountBadge: document.getElementById('saved-count-badge'),
  viewSavedBtn: document.getElementById('view-saved-btn'),
  scrapeBtn: document.getElementById('scrape-btn'),
  exportBtn: document.getElementById('export-btn'),
  analyticsToggle: document.getElementById('analytics-toggle'),
  analyticsDrawer: document.getElementById('analytics-drawer'),
  jobModal: document.getElementById('job-modal'),
  modalContent: document.getElementById('modal-content'),
  toast: document.getElementById('toast'),
  toastMessage: document.getElementById('toast-message'),
  systemStatusDot: document.getElementById('system-status-dot'),
  systemStatusText: document.getElementById('system-status-text')
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  updateSavedBadge();
  loadStats();
  loadDomains();
  loadJobs();

  // Refresh status every 30 seconds
  setInterval(checkStatus, 30000);
});

// Event Listeners setup
function initEventListeners() {
  // Search with debounce
  let searchTimer;
  dom.searchInput.addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.search = e.target.value.trim();
      state.page = 1;
      dom.clearSearch.classList.toggle('hidden', !state.search);
      loadJobs();
    }, 300);
  });

  dom.clearSearch.addEventListener('click', () => {
    dom.searchInput.value = '';
    state.search = '';
    dom.clearSearch.classList.add('hidden');
    state.page = 1;
    loadJobs();
  });

  // Global keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement !== dom.searchInput) {
      e.preventDefault();
      dom.searchInput.focus();
    }
    if (e.key === 'Escape') {
      closeJobModal();
    }
  });

  // Remote toggle
  dom.remoteToggle.addEventListener('change', (e) => {
    state.remote = e.target.checked ? true : null;
    state.page = 1;
    loadJobs();
  });

  // Sort select
  dom.sortSelect.addEventListener('change', (e) => {
    state.sort = e.target.value;
    state.page = 1;
    loadJobs();
  });

  // View Saved / Bookmarked button
  dom.viewSavedBtn.addEventListener('click', () => {
    state.showSavedOnly = !state.showSavedOnly;
    dom.viewSavedBtn.classList.toggle('bg-amber-500/20', state.showSavedOnly);
    dom.viewSavedBtn.classList.toggle('border-amber-500', state.showSavedOnly);
    dom.viewSavedBtn.classList.toggle('text-amber-300', state.showSavedOnly);
    state.page = 1;
    loadJobs();
  });

  // Analytics toggle
  dom.analyticsToggle.addEventListener('click', () => {
    dom.analyticsDrawer.classList.toggle('hidden');
    const isVisible = !dom.analyticsDrawer.classList.contains('hidden');
    dom.analyticsToggle.querySelector('span').textContent = isVisible ? 'Hide Telemetry' : 'Telemetry Charts';
    if (isVisible && state.stats) {
      renderCharts(state.stats);
    }
  });

  // Trigger Scrape Button
  dom.scrapeBtn.addEventListener('click', triggerScrape);

  // Export CSV
  dom.exportBtn.addEventListener('click', exportToCSV);
}

// Check Backend Engine Status
async function checkStatus() {
  try {
    const res = await fetch('/api/status');
    if (res.ok) {
      const data = await res.json();
      dom.systemStatusDot.className = data.is_scraping 
        ? 'w-2.5 h-2.5 rounded-full bg-amber-400 animate-ping' 
        : 'w-2.5 h-2.5 rounded-full bg-emerald-400 pulse-emerald';
      dom.systemStatusText.textContent = data.is_scraping ? 'Scraping in progress...' : 'System Nominal';
    }
  } catch (err) {
    dom.systemStatusDot.className = 'w-2.5 h-2.5 rounded-full bg-rose-500';
    dom.systemStatusText.textContent = 'Offline';
  }
}

// Load Telemetry & Stats
async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    const stats = await res.json();
    state.stats = stats;

    document.getElementById('stat-total-jobs').textContent = stats.total.toLocaleString();
    document.getElementById('stat-internships').textContent = stats.internships.toLocaleString();
    document.getElementById('stat-remote-pct').textContent = `${stats.remote_pct}%`;

    const topDomainEntry = Object.entries(stats.top_domains || {})[0];
    const topDomainName = topDomainEntry ? topDomainEntry[0] : 'Security Eng';
    document.getElementById('stat-top-domain').textContent = topDomainName.toUpperCase();

    if (stats.last_scraped) {
      const date = new Date(stats.last_scraped);
      document.getElementById('stat-last-sync').textContent = date.toLocaleDateString(undefined, { 
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' 
      });
    }

    if (!dom.analyticsDrawer.classList.contains('hidden')) {
      renderCharts(stats);
    }
  } catch (e) {
    console.error('Failed to load stats:', e);
  }
}

// Render Telemetry Charts
function renderCharts(stats) {
  // Chart 1: Role Type Distribution (Doughnut)
  const ctxType = document.getElementById('chart-job-types');
  if (ctxType) {
    if (state.charts.types) state.charts.types.destroy();
    const typeLabels = Object.keys(stats.by_type || {});
    const typeCounts = Object.values(stats.by_type || {});

    state.charts.types = new Chart(ctxType, {
      type: 'doughnut',
      data: {
        labels: typeLabels.map(l => l.charAt(0).toUpperCase() + l.slice(1)),
        datasets: [{
          data: typeCounts,
          backgroundColor: ['#10b981', '#06b6d4', '#f59e0b', '#8b5cf6', '#64748b'],
          borderColor: '#0f172a',
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom', labels: { color: '#94a3b8', font: { family: 'Plus Jakarta Sans', size: 12 } } }
        },
        cutout: '70%'
      }
    });
  }

  // Chart 2: Top Security Domains (Bar)
  const ctxDomain = document.getElementById('chart-domains');
  if (ctxDomain) {
    if (state.charts.domains) state.charts.domains.destroy();
    const domainLabels = Object.keys(stats.top_domains || {});
    const domainCounts = Object.values(stats.top_domains || {});

    state.charts.domains = new Chart(ctxDomain, {
      type: 'bar',
      data: {
        labels: domainLabels.map(d => d.length > 14 ? d.slice(0, 14) + '…' : d),
        datasets: [{
          label: 'Open Roles',
          data: domainCounts,
          backgroundColor: 'rgba(6, 182, 212, 0.7)',
          hoverBackgroundColor: '#06b6d4',
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } },
          y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(51, 65, 85, 0.2)' } }
        },
        plugins: {
          legend: { display: false }
        }
      }
    });
  }
}

// Load Domain Filter Pills
async function loadDomains() {
  try {
    const res = await fetch('/api/domains');
    if (!res.ok) return;
    const data = await res.json();
    const topDomains = (data.domains || []).slice(0, 14);

    let pillsHtml = `
      <button data-domain="all" class="domain-pill px-3 py-1 text-xs rounded-full font-mono transition-all ${state.domain === 'all' ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500' : 'bg-slate-800 text-slate-400 border border-slate-700/60 hover:border-slate-500'}">
        All Domains
      </button>
    `;

    topDomains.forEach(d => {
      const active = state.domain.toLowerCase() === d.tag.toLowerCase();
      pillsHtml += `
        <button data-domain="${escapeHtml(d.tag)}" class="domain-pill px-3 py-1 text-xs rounded-full font-mono transition-all ${active ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500' : 'bg-slate-800/80 text-slate-400 border border-slate-700/60 hover:border-slate-500'}">
          ${escapeHtml(d.tag)} <span class="opacity-60 text-[10px]">(${d.count})</span>
        </button>
      `;
    });

    dom.domainPills.innerHTML = pillsHtml;

    // Attach click events
    dom.domainPills.querySelectorAll('.domain-pill').forEach(btn => {
      btn.addEventListener('click', () => {
        state.domain = btn.getAttribute('data-domain');
        state.page = 1;
        loadDomains();
        loadJobs();
      });
    });
  } catch (e) {
    console.error('Failed to load domains:', e);
  }
}

// Select Job Type tab
function setJobType(type) {
  state.type = type;
  state.page = 1;
  document.querySelectorAll('#type-tabs button').forEach(btn => {
    const active = btn.getAttribute('data-type') === type;
    btn.className = `px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
      active 
        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/50 shadow-sm' 
        : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
    }`;
  });
  loadJobs();
}

// Load Jobs Feed
async function loadJobs() {
  dom.jobGrid.innerHTML = `
    <div class="col-span-full py-16 flex flex-col items-center justify-center text-slate-500">
      <svg class="animate-spin h-8 w-8 text-cyan-500 mb-3" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
      </svg>
      <p class="font-mono text-xs uppercase tracking-wider">Querying Cyber Intelligence Matrix...</p>
    </div>
  `;

  try {
    const params = new URLSearchParams({
      search: state.search,
      type: state.type,
      domain: state.domain,
      sort: state.sort,
      page: state.page,
      page_size: state.pageSize
    });
    if (state.remote !== null) {
      params.append('remote', state.remote);
    }

    const res = await fetch(`/api/jobs?${params.toString()}`);
    if (!res.ok) throw new Error('API query failed');
    const data = await res.json();

    let jobs = data.items || [];

    // Filter by bookmarks if toggled
    if (state.showSavedOnly) {
      jobs = jobs.filter(j => state.savedJobIds.has(j.id));
      dom.jobCountText.textContent = `Showing ${jobs.length} Bookmarked Opportunities`;
    } else {
      dom.jobCountText.textContent = `Showing ${(data.total === 0 ? 0 : (data.page - 1) * data.page_size + 1)}–${Math.min(data.page * data.page_size, data.total)} of ${data.total.toLocaleString()} positions`;
    }

    renderJobCards(jobs);
    renderPagination(data.total, data.page, data.total_pages);
  } catch (err) {
    console.error('Job load error:', err);
    dom.jobGrid.innerHTML = `
      <div class="col-span-full py-12 text-center text-rose-400">
        <p class="font-bold">Error loading jobs</p>
        <p class="text-xs text-slate-500 mt-1">${err.message}</p>
        <button onclick="loadJobs()" class="mt-4 px-4 py-1.5 bg-slate-800 text-xs rounded border border-slate-700 hover:bg-slate-700 text-slate-300">
          Retry
        </button>
      </div>
    `;
  }
}

// Render Job Cards Matrix
function renderJobCards(jobs) {
  if (!jobs || jobs.length === 0) {
    dom.jobGrid.innerHTML = `
      <div class="col-span-full py-16 text-center text-slate-500 hud-card rounded-xl p-8 border border-slate-800">
        <svg class="w-12 h-12 mx-auto text-slate-600 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
        </svg>
        <h3 class="text-base font-semibold text-slate-300">No matching security positions located</h3>
        <p class="text-xs text-slate-500 mt-1 max-w-sm mx-auto">Try adjusting your keywords, toggling remote filters, or clearing the specialization pill.</p>
        <button onclick="resetFilters()" class="mt-4 px-4 py-2 bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 text-xs rounded-lg hover:bg-cyan-500/20 transition-all font-mono">
          Reset Filter Matrix
        </button>
      </div>
    `;
    return;
  }

  dom.jobGrid.innerHTML = jobs.map(job => {
    const isSaved = state.savedJobIds.has(job.id);
    const isInternship = job.job_type === 'internship';
    const isContract = job.job_type === 'contract';

    const typeBadgeClass = isInternship
      ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
      : isContract
      ? 'bg-purple-500/15 text-purple-300 border-purple-500/30'
      : 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';

    const typeLabel = isInternship ? '🎓 Internship' : isContract ? '📝 Contract' : '💼 Full-Time';

    const locationText = job.remote 
      ? `🌍 ${job.location || 'Remote'} (Remote)` 
      : `🏢 ${job.location || 'Onsite'}`;

    const tags = (job.domain_tags || []).slice(0, 3);
    const tagsHtml = tags.map(t => `
      <span class="badge-domain text-[11px] px-2 py-0.5 rounded font-mono">
        #${escapeHtml(t.replace(/\s+/g, ''))}
      </span>
    `).join('');

    const formattedDate = job.discovered_at 
      ? timeAgo(new Date(job.discovered_at))
      : 'Recently';

    return `
      <div class="hud-card rounded-xl p-5 flex flex-col justify-between group relative border border-slate-800">
        <div>
          <!-- Top Row: Type & Save -->
          <div class="flex items-center justify-between gap-2 mb-3">
            <span class="text-[11px] font-mono px-2.5 py-0.5 rounded-full border ${typeBadgeClass}">
              ${typeLabel}
            </span>
            <div class="flex items-center gap-1.5">
              <span class="text-[10px] font-mono text-slate-500">${formattedDate}</span>
              <button onclick="toggleBookmark('${escapeHtml(job.id)}', event)" 
                title="${isSaved ? 'Remove Bookmark' : 'Bookmark Job'}"
                class="p-1 rounded text-slate-500 hover:text-amber-400 transition-colors">
                <svg class="w-4 h-4 ${isSaved ? 'text-amber-400 fill-amber-400' : 'stroke-current'}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
                </svg>
              </button>
            </div>
          </div>

          <!-- Title & Company -->
          <h4 class="text-base font-bold text-slate-100 group-hover:text-cyan-400 transition-colors line-clamp-2 leading-snug">
            ${escapeHtml(job.title)}
          </h4>
          <p class="text-xs font-semibold text-slate-400 mt-1 flex items-center gap-1.5">
            <span class="text-cyan-400">@</span> ${escapeHtml(job.company)}
          </p>

          <!-- Location & Source -->
          <p class="text-xs text-slate-500 mt-2 flex items-center gap-1 truncate font-mono">
            ${escapeHtml(locationText)}
          </p>

          <!-- Domain Tags -->
          <div class="flex flex-wrap gap-1.5 mt-3 min-h-[22px]">
            ${tagsHtml}
          </div>
        </div>

        <!-- Action Footer -->
        <div class="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between gap-2">
          <span class="text-[10px] font-mono text-slate-500 truncate max-w-[110px]" title="Source: ${escapeHtml(job.source)}">
            ${escapeHtml(job.source)}
          </span>
          <div class="flex items-center gap-2">
            <button onclick="openJobModal('${escapeHtml(job.id)}')" 
              class="px-2.5 py-1.5 text-xs text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-700/80 rounded border border-slate-700 transition-all font-mono">
              Inspect
            </button>
            <a href="${escapeHtml(job.apply_url || '#')}" target="_blank" rel="noopener noreferrer" 
              class="px-3 py-1.5 text-xs font-medium text-slate-950 bg-cyan-400 hover:bg-cyan-300 rounded font-mono flex items-center gap-1 transition-all shadow-sm">
              Apply
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/>
              </svg>
            </a>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

// Render Pagination
function renderPagination(total, currentPage, totalPages) {
  if (totalPages <= 1) {
    dom.pagination.innerHTML = '';
    return;
  }

  let html = `
    <button onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}
      class="px-3 py-1.5 text-xs font-mono rounded bg-slate-800 text-slate-300 border border-slate-700 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-700">
      ← Prev
    </button>
    <span class="text-xs font-mono text-slate-400 px-2">Page ${currentPage} of ${totalPages}</span>
    <button onclick="goToPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}
      class="px-3 py-1.5 text-xs font-mono rounded bg-slate-800 text-slate-300 border border-slate-700 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-700">
      Next →
    </button>
  `;

  dom.pagination.innerHTML = html;
}

function goToPage(p) {
  state.page = p;
  loadJobs();
  window.scrollTo({ top: 400, behavior: 'smooth' });
}

// Open Job Inspection Modal
async function openJobModal(jobId) {
  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) throw new Error('Failed to fetch job details');
    const job = await res.json();
    state.activeModalJob = job;

    const isSaved = state.savedJobIds.has(job.id);
    const tags = job.domain_tags || [];
    const tagsHtml = tags.map(t => `<span class="badge-domain text-xs px-2.5 py-1 rounded font-mono">#${escapeHtml(t)}</span>`).join('');

    dom.modalContent.innerHTML = `
      <div class="flex items-start justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <span class="text-xs font-mono uppercase tracking-wider text-cyan-400">${escapeHtml(job.job_type || 'Full-Time')}</span>
          <h2 class="text-xl font-bold text-white mt-1">${escapeHtml(job.title)}</h2>
          <p class="text-sm font-semibold text-slate-300 mt-0.5">
            <span class="text-cyan-400">Company:</span> ${escapeHtml(job.company)} 
            <span class="text-slate-500 mx-2">•</span> 
            <span class="text-slate-400">${escapeHtml(job.location || 'Remote')}</span>
          </p>
        </div>
        <button onclick="closeJobModal()" class="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <!-- Metadata Strip -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 py-4 border-b border-slate-800 text-xs font-mono">
        <div class="bg-slate-900/60 p-2.5 rounded border border-slate-800">
          <span class="text-slate-500 block">Work Mode</span>
          <span class="text-slate-200 font-bold">${job.remote ? '🌍 Remote' : '🏢 Onsite'}</span>
        </div>
        <div class="bg-slate-900/60 p-2.5 rounded border border-slate-800">
          <span class="text-slate-500 block">Discovered</span>
          <span class="text-slate-200 font-bold">${timeAgo(new Date(job.discovered_at))}</span>
        </div>
        <div class="bg-slate-900/60 p-2.5 rounded border border-slate-800">
          <span class="text-slate-500 block">Source Provider</span>
          <span class="text-slate-200 font-bold truncate">${escapeHtml(job.source)}</span>
        </div>
        <div class="bg-slate-900/60 p-2.5 rounded border border-slate-800">
          <span class="text-slate-500 block">Fingerprint ID</span>
          <span class="text-slate-400 font-mono text-[10px] truncate">${escapeHtml(job.hash || job.id)}</span>
        </div>
      </div>

      <!-- Domain Tags -->
      <div class="py-4 border-b border-slate-800">
        <span class="text-xs font-mono uppercase text-slate-400 block mb-2">Classified Cybersecurity Specializations:</span>
        <div class="flex flex-wrap gap-1.5">
          ${tagsHtml || '<span class="text-xs text-slate-500">General Security</span>'}
        </div>
      </div>

      <!-- Job Description Body -->
      <div class="py-4 max-h-[380px] overflow-y-auto pr-2 space-y-2 text-sm text-slate-300 leading-relaxed font-sans">
        <h3 class="text-xs font-mono uppercase tracking-wider text-slate-400">Position Brief / Description:</h3>
        <div class="whitespace-pre-wrap bg-slate-900/40 p-4 rounded-lg border border-slate-800/80 text-xs font-mono leading-normal text-slate-300">
          ${escapeHtml(job.description || 'No direct raw text description extracted from provider API. Direct application link is provided below.')}
        </div>
      </div>

      <!-- Modal Footer -->
      <div class="pt-4 border-t border-slate-800 flex items-center justify-between gap-3">
        <button onclick="toggleBookmark('${escapeHtml(job.id)}', event)" 
          class="px-4 py-2 text-xs font-mono rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 flex items-center gap-2">
          <svg class="w-4 h-4 ${isSaved ? 'text-amber-400 fill-amber-400' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
          </svg>
          ${isSaved ? 'Saved to Bookmarks' : 'Save Position'}
        </button>

        <a href="${escapeHtml(job.apply_url)}" target="_blank" rel="noopener noreferrer" 
          class="px-5 py-2.5 text-xs font-bold text-slate-950 bg-cyan-400 hover:bg-cyan-300 rounded-lg font-mono flex items-center gap-2 shadow-lg shadow-cyan-500/20">
          Open Official Application
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
          </svg>
        </a>
      </div>
    `;

    dom.jobModal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  } catch (err) {
    showToast('Failed to open job details', 'error');
  }
}

function closeJobModal() {
  dom.jobModal.classList.add('hidden');
  document.body.style.overflow = '';
}

// Bookmarking Handler
function toggleBookmark(jobId, event) {
  if (event) event.stopPropagation();
  if (state.savedJobIds.has(jobId)) {
    state.savedJobIds.delete(jobId);
    showToast('Removed from saved bookmarks');
  } else {
    state.savedJobIds.add(jobId);
    showToast('Saved to bookmarks ⭐');
  }
  localStorage.setItem('saved_cyber_jobs', JSON.stringify(Array.from(state.savedJobIds)));
  updateSavedBadge();
  loadJobs();
}

function updateSavedBadge() {
  dom.savedCountBadge.textContent = state.savedJobIds.size;
}

// On-Demand Scraper Trigger
async function triggerScrape() {
  dom.scrapeBtn.disabled = true;
  dom.scrapeBtn.classList.add('opacity-50');
  dom.scrapeBtn.querySelector('span').textContent = 'Scraping...';

  try {
    const res = await fetch('/api/scrape', { method: 'POST' });
    const data = await res.json();
    if (res.status === 409) {
      showToast('A scrape cycle is already executing');
      return;
    }
    showToast('Scraper cycle initiated in background 🚀');
    
    // Poll for status
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      const statusRes = await fetch('/api/status');
      if (statusRes.ok) {
        const s = await statusRes.json();
        if (!s.is_scraping || attempts > 30) {
          clearInterval(interval);
          dom.scrapeBtn.disabled = false;
          dom.scrapeBtn.classList.remove('opacity-50');
          dom.scrapeBtn.querySelector('span').textContent = 'Trigger Scrape';
          showToast('Scrape cycle complete! New positions indexed.');
          loadStats();
          loadJobs();
        }
      }
    }, 3000);
  } catch (err) {
    showToast('Error triggering scraper', 'error');
    dom.scrapeBtn.disabled = false;
    dom.scrapeBtn.classList.remove('opacity-50');
  }
}

// Export Current View to CSV
async function exportToCSV() {
  showToast('Generating CSV export...');
  try {
    const params = new URLSearchParams({
      search: state.search,
      type: state.type,
      domain: state.domain,
      sort: state.sort,
      page: 1,
      page_size: 500 // Export up to 500
    });
    if (state.remote !== null) params.append('remote', state.remote);

    const res = await fetch(`/api/jobs?${params.toString()}`);
    const data = await res.json();
    const rows = data.items || [];

    if (rows.length === 0) {
      showToast('No jobs to export');
      return;
    }

    const headers = ['Title', 'Company', 'Location', 'Remote', 'Type', 'Domain Tags', 'Source', 'Apply URL', 'Discovered'];
    const csvContent = [
      headers.join(','),
      ...rows.map(r => [
        `"${(r.title || '').replace(/"/g, '""')}"`,
        `"${(r.company || '').replace(/"/g, '""')}"`,
        `"${(r.location || '').replace(/"/g, '""')}"`,
        r.remote ? 'Yes' : 'No',
        r.job_type,
        `"${(r.domain_tags || []).join(';')}"`,
        r.source,
        `"${r.apply_url}"`,
        r.discovered_at
      ].join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `cybersec_jobs_${new Date().toISOString().slice(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('CSV export downloaded! 📁');
  } catch (e) {
    showToast('Export failed', 'error');
  }
}

// Toast Feedback
function showToast(msg, type = 'info') {
  dom.toastMessage.textContent = msg;
  dom.toast.classList.remove('hidden');
  setTimeout(() => {
    dom.toast.classList.add('hidden');
  }, 3500);
}

// Helpers
function resetFilters() {
  state.search = '';
  state.type = 'all';
  state.domain = 'all';
  state.remote = null;
  state.sort = 'newest';
  state.page = 1;
  state.showSavedOnly = false;
  dom.searchInput.value = '';
  dom.remoteToggle.checked = false;
  dom.sortSelect.value = 'newest';
  setJobType('all');
  loadDomains();
  loadJobs();
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function timeAgo(date) {
  if (isNaN(date.getTime())) return 'Recently';
  const seconds = Math.floor((new Date() - date) / 1000);
  const intervals = [
    { label: 'yr', seconds: 31536000 },
    { label: 'mo', seconds: 2592000 },
    { label: 'd', seconds: 86400 },
    { label: 'h', seconds: 3600 },
    { label: 'm', seconds: 60 }
  ];
  for (const interval of intervals) {
    const count = Math.floor(seconds / interval.seconds);
    if (count >= 1) return `${count}${interval.label} ago`;
  }
  return 'Just now';
}
