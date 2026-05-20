/* ── Config ─────────────────────────────────────────────────────── */
// Public URL via Tailscale Funnel on port 8443
const API_BASE    = 'https://my-biggest-beefsteak.tail437237.ts.net:8443';
const API_TOKEN   = '3df484b5a0a1fd711ba4438c1c6d8b79cc66444375e0da80';
const API_TIMEOUT = 5000; // ms before declaring API unreachable

/* ── Theme Toggle ───────────────────────────────────────────────── */
const body       = document.body;
const themeBtn   = document.getElementById('theme-toggle');
const themeIcon  = document.getElementById('theme-icon');

function applyTheme(dark) {
  body.classList.toggle('dark', dark);
  themeIcon.textContent = dark ? '☀️' : '🌙';
}

const saved = localStorage.getItem('theme');
const isDark = saved !== null ? saved === 'dark' : true;
applyTheme(isDark);

themeBtn.addEventListener('click', () => {
  const nowDark = !body.classList.contains('dark');
  applyTheme(nowDark);
  localStorage.setItem('theme', nowDark ? 'dark' : 'light');
});

/* ── Helpers ────────────────────────────────────────────────────── */

function setBar(barId, pct) {
  const bar = document.getElementById(barId);
  if (!bar) return;
  bar.style.width = pct + '%';
  bar.classList.toggle('hot',      pct >= 70 && pct < 85);
  bar.classList.toggle('critical', pct >= 85);
}

function nowTime() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function fmtUptime(seconds) {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600)  / 60);
  const s = seconds % 60;
  return `${d}d ${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

/* ── Badge helpers ──────────────────────────────────────────────── */
function setBadgeLive(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = 'Live';
  el.classList.remove('badge-mock', 'badge-error');
  el.classList.add('badge-live');
}

function setBadgeError(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = "Can't connect";
  el.classList.remove('badge-mock', 'badge-live');
  el.classList.add('badge-error');
}

/* ── API fetch with timeout ─────────────────────────────────────── */
async function apiFetch(path) {
  // Append token — works whether path already has query params or not
  const sep = path.includes('?') ? '&' : '?';
  const url = `${API_BASE}${path}${sep}token=${API_TOKEN}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT);
  try {
    const res = await fetch(url, { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch {
    clearTimeout(timer);
    return null;
  }
}

/* ── Render stats (shared by real + mock) ───────────────────────── */
function renderStats(d) {
  const { cpu, ram, ram_used_gb, ram_total_gb,
          swap, swap_used_gb,
          disk, disk_used_gb, disk_total_gb,
          disk_read_mbs, disk_write_mbs,
          uptime, net_tx, net_rx, temp, cpu_freq_ghz } = d;

  document.getElementById('stat-cpu').textContent  = cpu + '%';
  document.getElementById('stat-ram').textContent  = ram + '%';
  document.getElementById('stat-swap').textContent = swap != null ? swap + '%' : 'N/A';
  document.getElementById('stat-disk').textContent = disk + '%';
  document.getElementById('stat-temp').textContent = temp != null ? temp + '°C' : 'N/A';
  document.getElementById('stat-net').textContent  = `↑${net_tx} ↓${net_rx} KB/s`;
  document.getElementById('stat-uptime').textContent = fmtUptime(uptime);

  const ramDetail = document.getElementById('stat-ram-detail');
  if (ramDetail && ram_used_gb != null) ramDetail.textContent = `${ram_used_gb} / ${ram_total_gb} GB`;

  const swapDetail = document.getElementById('stat-swap-detail');
  if (swapDetail && swap_used_gb != null) swapDetail.textContent = `${swap_used_gb} GB used`;

  const diskDetail = document.getElementById('stat-disk-detail');
  if (diskDetail && disk_used_gb != null) diskDetail.textContent = `${disk_used_gb} / ${disk_total_gb} GB`;

  const diskio = document.getElementById('stat-diskio');
  if (diskio) diskio.textContent = (disk_read_mbs != null)
    ? `R ${disk_read_mbs} MB/s · W ${disk_write_mbs} MB/s`
    : 'N/A';

  const cpuFreq = document.getElementById('stat-cpu-freq');
  if (cpuFreq) cpuFreq.textContent = cpu_freq_ghz != null ? `${cpu_freq_ghz} GHz` : '';

  setBar('bar-cpu',  cpu);
  setBar('bar-ram',  ram);
  setBar('bar-swap', swap ?? 0);
  setBar('bar-disk', disk);
}

/* ── Stats — real API ───────────────────────────────────────────── */
let uptimeOffset = 0; // incremented by ticker between API polls

async function fetchAndRenderStats() {
  const data = await apiFetch('/api/stats');
  if (data) {
    uptimeOffset = 0;
    renderStats(data);
    setBadgeLive('badge-mac');
    return true;
  }
  return false;
}

/* ── Stats — error state ────────────────────────────────────────── */
function renderStatsError() {
  ['stat-cpu', 'stat-ram', 'stat-swap', 'stat-disk', 'stat-temp', 'stat-net', 'stat-uptime', 'stat-diskio'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = '—'; el.style.color = 'var(--offline)'; }
  });
  ['stat-ram-detail', 'stat-swap-detail', 'stat-disk-detail', 'stat-cpu-freq'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '';
  });
  ['bar-cpu', 'bar-ram', 'bar-swap', 'bar-disk'].forEach(id => {
    const bar = document.getElementById(id);
    if (bar) bar.style.width = '0%';
  });
  setBadgeError('badge-mac');
}

/* ── Stats boot ─────────────────────────────────────────────────── */
let usingRealStats = false;

(async () => {
  usingRealStats = await fetchAndRenderStats();
  if (!usingRealStats) renderStatsError();
})();

// Uptime ticker — only runs when real stats are live
setInterval(() => {
  if (usingRealStats) {
    uptimeOffset++;
    const el = document.getElementById('stat-uptime');
    if (el && el._baseUptime != null) {
      el.textContent = fmtUptime(el._baseUptime + uptimeOffset);
    }
  }
}, 1000);

// Stats refresh every 5s
setInterval(async () => {
  const ok = await fetchAndRenderStats();
  usingRealStats = ok;
  if (!ok) renderStatsError();
}, 5000);

/* ── Server Status — real API ───────────────────────────────────── */
async function fetchAndRenderServices() {
  const data = await apiFetch('/api/services');
  if (!data) return false;

  const idMap = { immich: 'immich', openclaw: 'openclaw', projects: 'projects', proto: 'proto' };
  const t = nowTime();

  data.forEach(svc => {
    const lcEl = document.getElementById(`lc-${svc.id}`);
    if (lcEl) lcEl.textContent = `Checked ${t}`;

    // Find the status badge inside the server card
    // Cards are matched by finding server-name text
    document.querySelectorAll('.server-card').forEach(card => {
      const nameEl = card.querySelector('.server-name');
      if (!nameEl) return;
      // Match by service id → name mapping
      const cardSvcId = Object.entries(idMap).find(([id]) => id === svc.id)?.[0];
      if (!cardSvcId) return;
      if (card.querySelector(`#lc-${cardSvcId}`) === null) return;

      const badge = card.querySelector('.status-badge');
      if (!badge) return;
      badge.className = `status-badge ${svc.online ? 'online' : 'offline'}`;
      badge.textContent = svc.online ? 'Online' : 'Offline';
    });
  });

  setBadgeLive('badge-servers');
  return true;
}

function renderServicesError() {
  const t = nowTime();
  ['immich', 'openclaw', 'projects', 'proto', 'tailscale'].forEach(id => {
    const lcEl = document.getElementById(`lc-${id}`);
    if (lcEl) lcEl.textContent = `Failed ${t}`;
  });
  document.querySelectorAll('.server-card .status-badge').forEach(badge => {
    badge.className = 'status-badge offline';
    badge.textContent = 'Offline';
  });
  setBadgeError('badge-servers');
}

// Boot
(async () => {
  const ok = await fetchAndRenderServices();
  if (!ok) renderServicesError();
})();

// Refresh every 30s
setInterval(async () => {
  const ok = await fetchAndRenderServices();
  if (!ok) renderServicesError();
}, 30000);

/* ── Log Viewer ─────────────────────────────────────────────────── */
const logViewer  = document.getElementById('log-viewer');
const logSelect  = document.getElementById('log-server');
const logRefresh = document.getElementById('log-refresh');
const logFollow  = document.getElementById('log-follow');

function renderLogLines(lines) {
  if (!lines.length) {
    logViewer.innerHTML = '<div class="log-line"><span class="log-msg" style="color:var(--text-muted)">No log lines available.</span></div>';
    return;
  }
  logViewer.innerHTML = lines.map(({ time, level, msg }) => `
    <div class="log-line">
      <span class="log-time">${time ?? '——'}</span>
      <span class="log-level ${level ?? 'INFO'}">${level ?? 'INFO'}</span>
      <span class="log-msg">${msg ?? ''}</span>
    </div>
  `).join('');
  if (logFollow.checked) logViewer.scrollTop = logViewer.scrollHeight;
}

async function fetchAndRenderLogs(server) {
  const data = await apiFetch(`/api/logs?service=${server}&lines=50`);
  if (data && data.lines && data.lines.length > 0) {
    renderLogLines(data.lines);
    setBadgeLive('badge-logs');
    return true;
  }
  return false;
}

async function refreshLog() {
  const server = logSelect.value;
  const ok = await fetchAndRenderLogs(server);
  if (!ok) {
    logViewer.innerHTML = `
      <div class="log-line">
        <span class="log-level ERROR">ERROR</span>
        <span class="log-msg" style="color:var(--offline)">Can't connect to API — make sure the Mac mini is reachable over Tailscale and the server is running.</span>
      </div>`;
    setBadgeError('badge-logs');
  }
}

// Initial render
refreshLog();

logSelect.addEventListener('change', refreshLog);
logRefresh.addEventListener('click', refreshLog);
setInterval(refreshLog, 10000);
