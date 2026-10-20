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
  syncThemeColor();
});

/* ── Skins ──────────────────────────────────────────────────────────
   Whole-design prototypes to choose between, not palette swaps. A skin
   sets body[data-skin] (which drives a full structural block in
   style.css: layout, framing, typography, colour) and declares what
   *form* its graphs take — see drawSpark. Light/dark stays independent. */
const SKINS = [
  { id: 'bento',   name: 'Bento',    chart: 'area',   desc: 'Asymmetric tiles, hero panels, big soft numbers' },
  { id: 'ops',     name: 'Ops',      chart: 'bars',   desc: 'Monitoring rig — titled panels, column charts' },
  { id: 'crt',     name: 'CRT',      chart: 'blocks', desc: 'Amber phosphor terminal, graphs drawn in text' },
  { id: 'paper',   name: 'Paper',    chart: 'line',   desc: 'Editorial print — serif, hairlines, no fills' },
  { id: 'classic', name: 'Classic',  chart: 'area',   desc: 'The original look, for comparison' },
];

// Which graph form the active skin uses. Drives drawSpark.
function chartStyle() {
  return (SKINS.find(s => s.id === currentSkin()) || {}).chart || 'area';
}

const skinBtn  = document.getElementById('skin-btn');
const skinMenu = document.getElementById('skin-menu');

function currentSkin() {
  return body.dataset.skin || 'bento';
}

function applySkin(id) {
  if (!SKINS.some(s => s.id === id)) id = 'bento';
  body.dataset.skin = id;
  localStorage.setItem('skin', id);
  renderSkinMenu();
  syncThemeColor();
  // Graph *form* is part of the skin, so every chart has to be redrawn — a
  // restyle alone can't turn an area chart into block characters.
  Object.keys(_sparks).forEach(renderSpark);
}

// Keep the PWA / mobile browser chrome in step with the active skin. Read the
// computed background rather than hardcoding, so it follows skin *and* mode.
function syncThemeColor() {
  const meta = document.querySelector('meta[name="theme-color"]');
  if (!meta) return;
  const bg = getComputedStyle(body).backgroundColor;
  if (bg && bg !== 'transparent' && !bg.startsWith('rgba(0, 0, 0, 0)')) meta.content = bg;
}

function renderSkinMenu() {
  if (!skinMenu) return;
  const active = currentSkin();
  skinMenu.innerHTML = SKINS.map(s => `
    <button class="skin-opt${s.id === active ? ' active' : ''}" role="menuitem" data-skin="${s.id}">
      <span class="skin-swatch" data-swatch="${s.id}"><i></i><i></i><i></i></span>
      <span class="skin-text">
        <span class="skin-name">${escapeHtml(s.name)}</span>
        <span class="skin-desc">${escapeHtml(s.desc)}</span>
      </span>
      <span class="skin-check">${s.id === active ? '✓' : ''}</span>
    </button>`).join('');
}

function toggleSkinMenu(open) {
  if (!skinMenu || !skinBtn) return;
  const show = open ?? skinMenu.hidden;
  skinMenu.hidden = !show;
  skinBtn.setAttribute('aria-expanded', String(show));
}

if (skinBtn && skinMenu) {
  // Normalise whatever the boot script read from storage. A skin id from an older
  // set no longer matches any CSS block, which would leave the page on the bare
  // :root styling with nothing marked active in the menu.
  if (!SKINS.some(s => s.id === currentSkin())) applySkin('bento');
  renderSkinMenu();
  skinBtn.addEventListener('click', e => { e.stopPropagation(); toggleSkinMenu(); });
  skinMenu.addEventListener('click', e => {
    const opt = e.target.closest('.skin-opt');
    if (!opt) return;
    applySkin(opt.dataset.skin);
    toggleSkinMenu(false);
  });
  document.addEventListener('click', e => {
    if (!skinMenu.hidden && !skinMenu.contains(e.target) && e.target !== skinBtn) toggleSkinMenu(false);
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !skinMenu.hidden) toggleSkinMenu(false);
  });
}
syncThemeColor();

/* ── Helpers ────────────────────────────────────────────────────── */

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function slugify(str) {
  return String(str).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

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
async function apiFetch(path, options = {}) {
  const sep = path.includes('?') ? '&' : '?';
  const url = `${API_BASE}${path}${sep}token=${API_TOKEN}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT);
  try {
    const res = await fetch(url, { signal: controller.signal, ...options });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch {
    clearTimeout(timer);
    return null;
  }
}

/* ─────────────────────────────────────────────────────────────────
   DYNAMIC CARD RENDERING
   ───────────────────────────────────────────────────────────────── */

let _config = { projects: [], services: [] };

/* ── Project cards ──────────────────────────────────────────────── */
function renderProjectCards(projects, statusMap = {}) {
  const grid = document.getElementById('projects-grid');
  if (!grid) return;
  if (!projects.length) {
    grid.innerHTML = '<div class="card placeholder-card">No projects configured. Click ⚙️ to add some.</div>';
    return;
  }
  grid.innerHTML = projects.map(p => {
    const status = statusMap[p.id];
    const dotClass = status === undefined ? 'checking' : status ? 'online' : 'offline';
    const vis = p.visibility === 'private' ? ' <span class="vis-badge">Private</span>' : '';
    return `
      <a class="card project-card" href="${escapeHtml(p.url)}" target="_blank" rel="noopener" data-proj-id="${escapeHtml(p.id)}">
        <div class="card-icon">${escapeHtml(p.icon)}</div>
        <div class="card-body">
          <div class="card-name">${escapeHtml(p.name)}${vis}</div>
          <div class="card-desc">${escapeHtml(p.desc)}</div>
        </div>
        <span class="status-dot ${dotClass}" title="${dotClass}"></span>
      </a>`;
  }).join('');
}

function updateProjectStatuses(projArr) {
  projArr.forEach(p => {
    const card = document.querySelector(`[data-proj-id="${p.id}"] .status-dot`);
    if (!card) return;
    card.className = `status-dot ${p.online ? 'online' : 'offline'}`;
    card.title = p.online ? 'online' : 'offline';
  });
}

/* ── Downloads (auto-synced from GitHub) ────────────────────────────
   Fetches the owner's public repos straight from the GitHub API and
   renders download cards. No backend, no config.json, no write token —
   push a new repo and it shows up here on its own. */
const GITHUB_USER    = 'Dao-Xuan-Thinh';
const GH_CACHE_KEY   = 'gh_repos_cache_v1';
const GH_CACHE_TTL   = 3 * 60 * 60 * 1000; // 3 hours

// Repos to hide: websites already shown as project links + this dashboard.
// (Forks are dropped separately, so their names don't need listing here.)
const DOWNLOAD_IGNORE = new Set([
  'Simple-Homepage',
  'Study-Portal',
  'Simple-StandBy',
  'Prototype_Web',
]);

// GitHub's language colors (subset) for the language dot.
const LANG_COLORS = {
  Python:     '#3572A5',
  JavaScript: '#f1e05a',
  TypeScript: '#3178c6',
  C:          '#555555',
  'C++':      '#f34b7d',
  Java:       '#b07219',
  HTML:       '#e34c26',
  CSS:        '#563d7c',
  Shell:      '#89e051',
};

function fmtDate(iso) {
  if (!iso) return '';
  return iso.slice(0, 10); // YYYY-MM-DD
}

function fmtEpochDate(epochSeconds) {
  if (!epochSeconds) return '—';
  return new Date(epochSeconds * 1000)
    .toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); // e.g. Jul 9
}

function fmtEnergy(wh) {
  if (wh == null) return '—';
  return wh < 1000 ? `${wh.toFixed(1)} Wh` : `${(wh / 1000).toFixed(2)} kWh`;
}

function renderDownloadCards(repos) {
  const grid = document.getElementById('downloads-grid');
  if (!grid) return;
  if (!repos.length) {
    grid.innerHTML =
      `<a class="card placeholder-card" href="https://github.com/${GITHUB_USER}" target="_blank" rel="noopener">Browse all repos on GitHub →</a>`;
    return;
  }
  grid.innerHTML = repos.map(r => {
    const lang    = r.language || '';
    const color   = LANG_COLORS[lang] || '#8b8b8b';
    const desc    = r.description || (lang ? `${lang} project` : 'GitHub repository');
    const zipUrl  = `${r.html_url}/archive/refs/heads/${r.default_branch}.zip`;
    const langBit = lang
      ? `<span class="dl-lang"><span class="lang-dot" style="background:${color}"></span>${escapeHtml(lang)}</span>`
      : '';
    const starBit = r.stargazers_count
      ? `<span class="dl-stat">★ ${r.stargazers_count}</span>`
      : '';
    return `
      <div class="card download-card">
        <div class="card-body">
          <div class="card-name">
            <a href="${escapeHtml(r.html_url)}" target="_blank" rel="noopener">${escapeHtml(r.name)}</a>
          </div>
          <div class="card-desc">${escapeHtml(desc)}</div>
          <div class="dl-meta">
            ${langBit}
            ${starBit}
            <span class="dl-stat">updated ${escapeHtml(fmtDate(r.updated_at))}</span>
          </div>
        </div>
        <div class="dl-actions">
          <a href="${escapeHtml(r.html_url)}" target="_blank" rel="noopener">Code</a>
          <a href="${escapeHtml(zipUrl)}" rel="noopener">ZIP</a>
          <a href="${escapeHtml(r.html_url)}/releases" target="_blank" rel="noopener">Releases</a>
        </div>
      </div>`;
  }).join('');
}

function curateRepos(raw) {
  return raw
    .filter(r => !r.fork && !DOWNLOAD_IGNORE.has(r.name))
    .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
}

function readRepoCache() {
  try {
    const cached = JSON.parse(localStorage.getItem(GH_CACHE_KEY) || 'null');
    if (cached && Array.isArray(cached.repos)) return cached;
  } catch (_) { /* ignore malformed cache */ }
  return null;
}

function fmtAge(ts) {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (s < 60)    return 'just now';
  if (s < 3600)  return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function setDownloadBadge(text, state) {
  const badge = document.getElementById('badge-downloads');
  if (!badge) return;
  badge.textContent = text;
  badge.classList.remove('badge-mock', 'badge-live', 'badge-error');
  badge.classList.add(state); // 'badge-live' | 'badge-error'
}

// force = true skips the cache and always re-fetches (the ↻ button).
async function initDownloads(force = false) {
  const cache = readRepoCache();
  const fresh = cache && (Date.now() - cache.ts) < GH_CACHE_TTL;

  // Serve fresh cache immediately without hitting the network.
  if (!force && fresh) {
    const repos = curateRepos(cache.repos);
    renderDownloadCards(repos);
    setDownloadBadge(`${repos.length} repos · ${fmtAge(cache.ts)}`, 'badge-live');
    return;
  }

  try {
    const res = await fetch(
      `https://api.github.com/users/${GITHUB_USER}/repos?per_page=100&sort=updated`,
      { headers: { 'Accept': 'application/vnd.github+json' } }
    );
    if (!res.ok) throw new Error(`GitHub API ${res.status}`);
    const raw = await res.json();
    localStorage.setItem(GH_CACHE_KEY, JSON.stringify({ ts: Date.now(), repos: raw }));
    const repos = curateRepos(raw);
    renderDownloadCards(repos);
    setDownloadBadge(`${repos.length} repos · just now`, 'badge-live');
  } catch (err) {
    // Rate-limited or offline: fall back to any cached copy, however stale.
    if (cache) {
      const repos = curateRepos(cache.repos);
      renderDownloadCards(repos);
      setDownloadBadge(`${repos.length} repos · ${fmtAge(cache.ts)} (offline)`, 'badge-live');
    } else {
      renderDownloadCards([]);
      setDownloadBadge("Can't reach GitHub", 'badge-error');
    }
  }
}

// Wire the manual refresh (↻) button on the Downloads header.
const dlRefreshBtn = document.getElementById('downloads-refresh');
if (dlRefreshBtn) {
  dlRefreshBtn.addEventListener('click', async () => {
    dlRefreshBtn.classList.add('spinning');
    dlRefreshBtn.disabled = true;
    setDownloadBadge('Refreshing…', 'badge-live');
    await initDownloads(true);
    dlRefreshBtn.classList.remove('spinning');
    dlRefreshBtn.disabled = false;
  });
}

/* ── Service cards ──────────────────────────────────────────────── */
function renderServiceCards(services, svcArr = []) {
  const grid = document.getElementById('services-grid');
  if (!grid) return;
  if (!services.length) {
    grid.innerHTML = '<div class="card placeholder-card">No services configured. Click ⚙️ to add some.</div>';
    return;
  }

  const statusById = {};
  svcArr.forEach(s => statusById[s.id] = s.online);

  grid.innerHTML = services.map(svc => {
    const online = statusById[svc.id];
    const badgeClass = online === undefined ? 'checking' : online ? 'online' : 'offline';
    const badgeText  = online === undefined ? 'Checking…' : online ? 'Online' : 'Offline';
    return `
      <div class="card server-card" data-svc-id="${escapeHtml(svc.id)}">
        <div class="server-info">
          <span class="server-name">${escapeHtml(svc.name)}</span>
          <span class="server-detail">${escapeHtml(svc.detail || '')}</span>
        </div>
        <div class="server-meta">
          <span class="status-badge ${badgeClass}">${badgeText}</span>
          <span class="last-checked" id="lc-${escapeHtml(svc.id)}"></span>
        </div>
      </div>`;
  }).join('');
}

function updateServiceStatuses(svcArr) {
  const t = nowTime();
  svcArr.forEach(svc => {
    const card = document.querySelector(`[data-svc-id="${svc.id}"]`);
    if (!card) return;
    const badge = card.querySelector('.status-badge');
    if (badge) {
      badge.className = `status-badge ${svc.online ? 'online' : 'offline'}`;
      badge.textContent = svc.online ? 'Online' : 'Offline';
    }
    const lc = card.querySelector('.last-checked');
    if (lc) lc.textContent = `Checked ${t}`;
  });
}

/* ── Archived entries ───────────────────────────────────────────────
   Entries flagged `archived` in config.json leave the live grids and the log
   selector, and are listed here instead. The server doesn't probe them. */
const isLive = x => !x.archived;

function renderArchive(config) {
  const section = document.getElementById('archive-section');
  const grid = document.getElementById('archive-grid');
  if (!section || !grid) return;
  const items = [
    ...(config.projects || []).filter(p => p.archived).map(p => ({ ...p, kind: 'Project', sub: p.desc })),
    ...(config.services || []).filter(s => s.archived).map(s => ({ ...s, kind: 'Service', sub: s.detail })),
  ];
  section.hidden = !items.length;
  document.getElementById('badge-archived').textContent = items.length;
  grid.innerHTML = items.map(x => `
      <div class="card archived-card">
        <div class="card-icon">${escapeHtml(x.icon || '◉')}</div>
        <div class="card-body">
          <div class="card-name">${escapeHtml(x.name)} <span class="vis-badge">${x.kind}</span></div>
          <div class="card-desc">${escapeHtml(x.sub || '')}</div>
        </div>
      </div>`).join('');
}

function renderConfig(config) {
  const services = (config.services || []).filter(isLive);
  renderProjectCards((config.projects || []).filter(isLive));
  renderServiceCards(services);
  populateLogSelector(services);
  renderArchive(config);
}

/* ── Log selector ───────────────────────────────────────────────── */
function populateLogSelector(services) {
  const sel = document.getElementById('log-server');
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = services.map(s =>
    `<option value="${escapeHtml(s.id)}">${escapeHtml(s.name)}</option>`
  ).join('');
  if (prev && services.find(s => s.id === prev)) sel.value = prev;
  updateContainerSelector(services);
}

/* ─────────────────────────────────────────────────────────────────
   STATS
   ───────────────────────────────────────────────────────────────── */

function renderStats(d) {
  const { cpu, ram, ram_used_gb, ram_total_gb,
          swap, swap_used_gb,
          disk_read_mbs, disk_write_mbs,
          uptime, net_tx, net_rx, temp, gpu_temp, thermal_pressure, cpu_freq_ghz,
          load_1, load_5, load_15, cpu_cores,
          net_total_up_gb, net_total_down_gb,
          docker_running, docker_total, volumes,
          power_w, energy_wh, energy_since } = d;

  const upEl = document.getElementById('stat-uptime');
  if (upEl) { upEl._baseUptime = uptime; uptimeOffset = 0; }

  document.getElementById('stat-cpu').textContent  = cpu + '%';
  document.getElementById('stat-ram').textContent  = ram + '%';
  document.getElementById('stat-swap').textContent = swap != null ? swap + '%' : 'N/A';
  const tempEl = document.getElementById('stat-temp');
  const tempSub = document.getElementById('stat-temp-sub');
  if (temp != null) {
    tempEl.textContent = temp + '°C';
    // Heat coloring: cool = green, warm = metric amber (default), hot = red
    tempEl.style.color = temp >= 70 ? 'var(--offline)' : temp < 55 ? 'var(--online)' : '';
    // Sub-line: GPU temp (macmon) and/or pressure level when available
    const bits = [];
    if (gpu_temp != null) bits.push(`GPU ${gpu_temp}°C`);
    if (thermal_pressure) bits.push(thermal_pressure);
    if (tempSub) tempSub.textContent = bits.length ? bits.join(' · ') : 'CPU temperature';
  } else if (thermal_pressure) {
    const pressureColors = { Nominal: '', Moderate: 'var(--warning)', Heavy: 'var(--offline)', Sleeping: '' };
    tempEl.textContent = thermal_pressure;
    tempEl.style.color = pressureColors[thermal_pressure] ?? '';
    if (tempSub) tempSub.textContent = 'pressure level';
  } else {
    tempEl.textContent = 'N/A';
    if (tempSub) tempSub.textContent = '';
  }
  document.getElementById('stat-net').textContent  = `↑${net_tx} ↓${net_rx} KB/s`;
  document.getElementById('stat-uptime').textContent = fmtUptime(uptime);

  const ramDetail = document.getElementById('stat-ram-detail');
  if (ramDetail && ram_used_gb != null) ramDetail.textContent = `${ram_used_gb} / ${ram_total_gb} GB`;

  const swapDetail = document.getElementById('stat-swap-detail');
  if (swapDetail && swap_used_gb != null) swapDetail.textContent = `${swap_used_gb} GB used`;

  const diskio = document.getElementById('stat-diskio');
  if (diskio) diskio.textContent = (disk_read_mbs != null)
    ? `R ${disk_read_mbs} MB/s · W ${disk_write_mbs} MB/s`
    : 'N/A';

  const cpuFreq = document.getElementById('stat-cpu-freq');
  if (cpuFreq) cpuFreq.textContent = cpu_freq_ghz != null ? `${cpu_freq_ghz} GHz` : '';

  // Power / cumulative energy (estimated wall draw)
  const powerEl = document.getElementById('stat-power');
  if (powerEl) powerEl.textContent = power_w != null ? `${power_w} W` : 'N/A';
  const powerSub = document.getElementById('stat-power-sub');
  if (powerSub) {
    powerSub.textContent = energy_wh != null
      ? `${fmtEnergy(energy_wh)} since ${fmtEpochDate(energy_since)}`
      : 'system power';
  }

  // Load average
  const loadEl = document.getElementById('stat-load');
  if (loadEl) {
    loadEl.textContent = load_1 != null ? load_1.toFixed(2) : 'N/A';
    // Flag sustained load above the core count
    loadEl.style.color = (load_1 != null && cpu_cores && load_1 > cpu_cores) ? 'var(--warning)' : '';
  }
  const loadSub = document.getElementById('stat-load-sub');
  if (loadSub && load_5 != null) {
    loadSub.textContent = `5m ${load_5.toFixed(2)} · 15m ${load_15.toFixed(2)}` +
      (cpu_cores ? ` · ${cpu_cores} cores` : '');
  }

  // Cumulative network total since boot
  const netTotal = document.getElementById('stat-nettotal');
  if (netTotal) netTotal.textContent = net_total_up_gb != null
    ? `↑${net_total_up_gb} ↓${net_total_down_gb} GB`
    : 'N/A';

  // Docker container counts
  const dockerEl = document.getElementById('stat-docker');
  if (dockerEl) dockerEl.textContent = docker_running != null
    ? `${docker_running} / ${docker_total}`
    : 'N/A';

  // Per-volume disk breakdown (internal + external drives)
  renderVolumes(volumes);

  // Reset text color (in case we were in error state). Metric colors come from
  // CSS (--m per data-metric); temp manages its own heat color, so it's excluded.
  ['stat-cpu','stat-ram','stat-swap','stat-net','stat-uptime','stat-diskio',
   'stat-power','stat-load','stat-nettotal','stat-docker'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.color = '';
  });

  setBar('bar-cpu',  cpu);
  setBar('bar-ram',  ram);
  setBar('bar-swap', swap ?? 0);

  // Live sparklines — extend the window seeded from /api/history
  pushSpark('cpu', cpu);
  pushSpark('ram', ram);
  pushSpark('temp', temp);
  pushSpark('power', power_w);
  pushSpark('swap', swap);
  pushSpark('load', load_1);
  pushSpark('net_rx', net_rx);
  pushSpark('net_tx', net_tx);
  // Disk usage comes from the internal data volume in the volumes list, which is what
  // the server's `disk` metric tracks — keeps the live series on the same basis as the
  // seeded history rather than mixing in external drives.
  const dataVol = Array.isArray(volumes)
    ? volumes.find(v => v.internal) || volumes[0]
    : null;
  if (dataVol && dataVol.percent != null) pushSpark('disk', dataVol.percent);
  renderDiskTrend();
}

/* ── Sparklines ─────────────────────────────────────────────────── */
// Each buffer holds {t, v} samples (t = epoch seconds) rather than bare values, so
// the x axis is real time: the server's 20 s history samples and the browser's 5 s
// live samples can sit in the same series without distorting the shape. Buffers are
// backfilled from /api/history on boot, so a freshly-opened tab already shows a full
// window instead of drawing itself in from nothing.
const SPARK_WINDOW_MIN = 30;
const SPARK_WINDOW_S   = SPARK_WINDOW_MIN * 60;
const _sparks = {
  cpu: [], ram: [], temp: [], power: [],
  swap: [], load: [], disk: [],
  net_rx: [], net_tx: [],   // drawn together as one mirrored graph
};

// Per-metric vertical scaling. Metrics that genuinely idle near zero are anchored at
// 0 so a spike reads as a spike (the network-graph look); the rest never approach
// zero, so they're zoomed to their active band with a floor on the span to keep idle
// noise from being magnified into fake mountains.
const SPARK_CFG = {
  cpu:   { zero: true,  minTop: 25,  fmt: v => Math.round(v) + '%' },
  power: { zero: true,  minTop: 12,  fmt: v => v.toFixed(1) + ' W' },
  swap:  { zero: true,  minTop: 20,  fmt: v => Math.round(v) + '%' },
  load:  { zero: true,  minTop: 4,   fmt: v => v.toFixed(2) },
  ram:   { zero: false, minSpan: 15, fmt: v => Math.round(v) + '%' },
  temp:  { zero: false, minSpan: 10, fmt: v => Math.round(v) + '°C' },
  // Disk usage barely moves hour to hour; a tight band makes the drift legible,
  // which is the whole point of pairing it with the fill projection.
  disk:  { zero: false, minSpan: 4,  fmt: v => v.toFixed(1) + '%' },
};

// The network pair is drawn as one mirrored graph (download up, upload down) in
// #spark-net, so it routes to its own renderer rather than the generic one.
const NET_KEYS = ['net_rx', 'net_tx'];

function fmtRate(kbs) {
  return kbs >= 1024 ? (kbs / 1024).toFixed(1) + ' MB/s' : Math.round(kbs) + ' KB/s';
}

function fmtSparkSpan(sec) {
  if (sec < 90) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

function pushSpark(key, val, t) {
  if (val == null || isNaN(val)) return;
  const buf = _sparks[key];
  if (!buf) return;
  // Keep timestamps monotonic — the browser and the mini can disagree by a second or
  // two, and an out-of-order point would draw a backwards segment.
  const last = buf.length ? buf[buf.length - 1].t : 0;
  let ts = t ?? Math.floor(Date.now() / 1000);
  if (ts <= last) ts = last + 1;
  buf.push({ t: ts, v: Number(val) });
  const cutoff = ts - SPARK_WINDOW_S;
  while (buf.length && buf[0].t < cutoff) buf.shift();
  renderSpark(key);
}

// Backfill the buffers from the server's history ring (sampled every ALERT_INTERVAL
// seconds, 24/7) so the graphs are meaningful the moment the page loads.
async function seedSparksFromHistory() {
  const data = await apiFetch(`/api/history?minutes=${SPARK_WINDOW_MIN}`);
  if (!data || !Array.isArray(data.points)) return false;  // keep whatever we have
  const keys = Object.keys(_sparks);
  keys.forEach(k => { _sparks[k].length = 0; });
  for (const p of data.points) {
    if (!p || p.t == null) continue;
    for (const k of keys) {
      if (p[k] != null && !isNaN(p[k])) _sparks[k].push({ t: p.t, v: Number(p[k]) });
    }
  }
  keys.forEach(renderSpark);
  return true;
}

// A backgrounded tab stops polling, leaving a hole in the series. Rather than drawing a
// straight line across the gap, re-seed from the server ring — it kept sampling.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return;
  const newest = Math.max(0, ...Object.values(_sparks).map(b => (b.length ? b[b.length - 1].t : 0)));
  if (newest && (Date.now() / 1000 - newest) > 120) seedSparksFromHistory();
});

// Shared window geometry: the x axis is anchored to "now" but never wider than the
// data we actually have, so a short buffer fills the box rather than drawing a stub
// against the right edge. Returns null when there isn't enough to plot.
function sparkWindow(...bufs) {
  const filled = bufs.filter(b => b && b.length);
  if (!filled.length) return null;
  const newest = Math.max(...filled.map(b => b[b.length - 1].t));
  const oldest = Math.min(...filled.map(b => b[0].t));
  const now  = Math.max(Date.now() / 1000, newest);
  const t0   = Math.max(oldest, now - SPARK_WINDOW_S);
  const span = Math.max(now - t0, 30);
  return { now, t0, span, x: t => ((t - t0) / span) * 300 };
}

// Network: download above the baseline, upload below, on a shared scale so the two
// directions are comparable at a glance. The only metric where the two-direction
// form is the right one — everything else reads better anchored at the bottom.
function renderNetSpark() {
  const el = document.getElementById('spark-net');
  const rx = _sparks.net_rx, tx = _sparks.net_tx;
  if (!el || (rx.length < 2 && tx.length < 2)) return;
  const win = sparkWindow(rx, tx);
  if (!win) return;

  const W = 300, H = 100, MID = H / 2;
  const inWin = b => b.filter(p => p.t >= win.t0);
  const rxP = inWin(rx), txP = inWin(tx);
  const peakRx = rxP.length ? Math.max(...rxP.map(p => p.v)) : 0;
  const peakTx = txP.length ? Math.max(...txP.map(p => p.v)) : 0;
  const scale  = Math.max(peakRx, peakTx, 1);   // shared, and never divide by zero

  // dir +1 draws upward from the midline, -1 downward.
  const trace = (pts, dir) => {
    if (pts.length < 2) return '';
    const y = v => MID - dir * (v / scale) * (MID - 1);
    const line = pts.map(p => `${win.x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ');
    const area = `${win.x(pts[0].t).toFixed(1)},${MID} ${line} ${win.x(pts[pts.length - 1].t).toFixed(1)},${MID}`;
    return `<polygon class="spark-area" points="${area}"></polygon>` +
           `<polyline class="spark-line" vector-effect="non-scaling-stroke" points="${line}"></polyline>`;
  };

  el.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">` +
      `<g class="net-rx">${trace(rxP, 1)}</g>` +
      `<g class="net-tx">${trace(txP, -1)}</g>` +
      `<line class="spark-mid" x1="0" y1="${MID}" x2="${W}" y2="${MID}" ` +
        `vector-effect="non-scaling-stroke"></line>` +
    `</svg>` +
    `<span class="spark-peak">↓ ${fmtRate(peakRx)}</span>` +
    `<span class="spark-peak low">↑ ${fmtRate(peakTx)}</span>` +
    `<span class="spark-span">${fmtSparkSpan(win.now - win.t0)}</span>`;
}

function renderSpark(key) {
  if (NET_KEYS.includes(key)) return renderNetSpark();
  const el  = document.getElementById('spark-' + key);
  const buf = _sparks[key];
  if (!el || !buf || buf.length < 2) return;
  const cfg = SPARK_CFG[key] || { zero: true, minTop: 1, fmt: v => Math.round(v) };
  const W = 300, H = 100;

  const win = sparkWindow(buf);
  if (!win) return;
  const { now, t0 } = win;
  const pts = buf.filter(p => p.t >= t0);
  if (pts.length < 2) return;

  const vals = pts.map(p => p.v);
  const peak = Math.max(...vals);
  let lo, hi;
  if (cfg.zero) {
    lo = 0;
    hi = Math.max(peak * 1.15, cfg.minTop);
  } else {
    lo = Math.min(...vals);
    hi = peak;
    const short = cfg.minSpan - (hi - lo);
    if (short > 0) { lo -= short / 2; hi += short / 2; }
    const pad = (hi - lo) * 0.12;
    lo -= pad; hi += pad;
  }
  if (hi - lo < 1e-6) hi = lo + 1;

  const x = win.x;
  const y = v => H - ((v - lo) / (hi - lo)) * H;
  const norm = v => (v - lo) / (hi - lo);   // 0..1, for forms that don't use SVG coords

  el.innerHTML =
    drawSpark(chartStyle(), { pts, x, y, norm, W, H }) +
    `<span class="spark-peak">${cfg.fmt(peak)}</span>` +
    `<span class="spark-span">${fmtSparkSpan(now - t0)}</span>`;
}

/* ── Chart forms ────────────────────────────────────────────────────
   A skin doesn't just recolour the graph, it changes what kind of graph
   it is: filled area, bare stroke, discrete columns, or block characters
   rendered as text. Each form takes the same scaled geometry. */
function drawSpark(style, g) {
  const { pts, x, y, norm, W, H } = g;

  if (style === 'blocks') {
    // Text, not vectors: downsample to a fixed column count and map each to one
    // of the eighth-height block glyphs.
    const GLYPHS = '▁▂▃▄▅▆▇█';
    const COLS = 46;
    const step = pts.length / COLS;
    let out = '';
    for (let i = 0; i < COLS; i++) {
      const slice = pts.slice(Math.floor(i * step), Math.max(Math.floor((i + 1) * step), Math.floor(i * step) + 1));
      if (!slice.length) continue;
      const v = Math.max(...slice.map(p => p.v));
      const idx = Math.min(GLYPHS.length - 1, Math.max(0, Math.round(norm(v) * (GLYPHS.length - 1))));
      out += GLYPHS[idx];
    }
    return `<span class="spark-blocks" aria-hidden="true">${out}</span>`;
  }

  const line = pts.map(p => `${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ');
  const svg = inner =>
    `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">${inner}</svg>`;

  if (style === 'bars') {
    // One column per sample, with a gap. Widths come from the sample spacing so
    // uneven intervals don't produce overlapping bars.
    const n = pts.length;
    const bw = Math.max(W / n * 0.68, 0.8);
    const bars = pts.map(p => {
      const top = y(p.v);
      return `<rect class="spark-bar" x="${(x(p.t) - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" ` +
             `width="${bw.toFixed(1)}" height="${Math.max(H - top, 0.5).toFixed(1)}"></rect>`;
    }).join('');
    return svg(bars);
  }

  if (style === 'line') {
    return svg(`<polyline class="spark-line" vector-effect="non-scaling-stroke" points="${line}"></polyline>`);
  }

  // 'area' (default)
  const area = `${x(pts[0].t).toFixed(1)},${H} ${line} ${x(pts[pts.length - 1].t).toFixed(1)},${H}`;
  return svg(
    `<polygon class="spark-area" points="${area}"></polygon>` +
    `<polyline class="spark-line" vector-effect="non-scaling-stroke" points="${line}"></polyline>`);
}

/* ─────────────────────────────────────────────────────────────────
   METRIC DETAIL MODAL — click a stat card for the full graph
   ───────────────────────────────────────────────────────────────── */

// Which history series and which live detail belong to each card's data-metric.
const METRIC_VIEWS = {
  cpu:    { key: 'cpu',    title: 'CPU Usage' },
  ram:    { key: 'ram',    title: 'RAM Usage' },
  // The card graphs swap as a percentage, but alerts fire on absolute GB — macOS
  // resizes its swap file, so the percentage is not something to alert on.
  swap:   { key: 'swap',   title: 'Swap', alertMetric: 'swap_gb' },
  temp:   { key: 'temp',   title: 'Thermal' },
  power:  { key: 'power',  title: 'Power' },
  load:   { key: 'load',   title: 'Load Average' },
  disk:   { key: 'disk',   title: 'Storage' },
  net:    { key: 'net_rx', title: 'Network', mirrored: true },
};

const metricOverlay = document.getElementById('metric-overlay');
let _metricView = null;      // the METRIC_VIEWS entry currently open
let _metricRange = 30;       // window in minutes

function openMetric(metric) {
  const view = METRIC_VIEWS[metric];
  if (!view || !metricOverlay) return;
  _metricView = view;
  _metricRange = 30;
  // Colour the whole modal with the clicked card's metric accent.
  metricOverlay.style.setProperty('--m', `var(--m-${metric})`);
  document.getElementById('metric-title').textContent = view.title;
  document.querySelectorAll('#metric-ranges .range-btn').forEach(b => {
    b.classList.toggle('active', Number(b.dataset.minutes) === _metricRange);
  });
  metricOverlay.hidden = false;
  document.body.style.overflow = 'hidden';
  loadMetricRange();
}

function closeMetric() {
  if (!metricOverlay) return;
  metricOverlay.hidden = true;
  document.body.style.overflow = '';
  _metricView = null;
}

// Draws into #metric-chart at a larger size than the card sparkline, with axis
// labels. Bucketed windows carry min/avg/max, so those are drawn as a band behind
// the average line rather than being flattened to a single trace.
async function loadMetricRange() {
  const view = _metricView;
  const chart = document.getElementById('metric-chart');
  if (!view || !chart) return;
  chart.innerHTML = '<div class="metric-loading">Loading…</div>';

  const data = await apiFetch(`/api/history?minutes=${_metricRange}`);
  if (!data || !Array.isArray(data.points) || data.points.length < 2) {
    chart.innerHTML = '<div class="metric-loading">Not enough history for this window yet.</div>';
    document.getElementById('metric-figures').innerHTML = '';
    return;
  }

  const bucketed = data.res === 'bucket';
  const pick = (p, k) => {
    const raw = p[k];
    if (raw == null) return null;
    return typeof raw === 'object' ? raw : { min: raw, avg: raw, max: raw };
  };

  if (view.mirrored) {
    renderBigNetChart(chart, data.points, pick);
  } else {
    renderBigChart(chart, data.points, view.key, pick, bucketed);
  }
  renderMetricFigures(data.points, view, pick);
  renderMetricDetail(view);
  renderMetricAlerts(view, data.points[0].t);
}

function renderBigChart(chart, points, key, pick, bucketed) {
  const series = points.map(p => ({ t: p.t, s: pick(p, key) })).filter(p => p.s);
  if (series.length < 2) {
    chart.innerHTML = '<div class="metric-loading">No data for this metric in this window.</div>';
    return;
  }
  const cfg = SPARK_CFG[key] || { zero: true, minTop: 1, fmt: v => Math.round(v) };
  const W = 600, H = 200;
  const t0 = series[0].t, t1 = series[series.length - 1].t;
  const span = Math.max(t1 - t0, 1);

  const peak = Math.max(...series.map(p => p.s.max));
  const low  = Math.min(...series.map(p => p.s.min));
  let lo, hi;
  if (cfg.zero) {
    lo = 0; hi = Math.max(peak * 1.1, cfg.minTop);
  } else {
    lo = low; hi = peak;
    const short = (cfg.minSpan || 1) - (hi - lo);
    if (short > 0) { lo -= short / 2; hi += short / 2; }
    const pad = (hi - lo) * 0.1;
    lo -= pad; hi += pad;
  }
  if (hi - lo < 1e-6) hi = lo + 1;

  const x = t => ((t - t0) / span) * W;
  const y = v => H - ((v - lo) / (hi - lo)) * H;
  const line = series.map(p => `${x(p.t).toFixed(1)},${y(p.s.avg).toFixed(1)}`).join(' ');
  const area = `${x(t0).toFixed(1)},${H} ${line} ${x(t1).toFixed(1)},${H}`;

  // min–max envelope: forward along the maxima, back along the minima.
  let band = '';
  if (bucketed) {
    const up = series.map(p => `${x(p.t).toFixed(1)},${y(p.s.max).toFixed(1)}`);
    const dn = series.slice().reverse().map(p => `${x(p.t).toFixed(1)},${y(p.s.min).toFixed(1)}`);
    band = `<polygon class="chart-band" points="${up.concat(dn).join(' ')}"></polygon>`;
  }

  chart.innerHTML =
    `<div class="chart-box">` +
      `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">` +
        band +
        `<polygon class="spark-area" points="${area}"></polygon>` +
        `<polyline class="spark-line" vector-effect="non-scaling-stroke" points="${line}"></polyline>` +
      `</svg>` +
      `<span class="axis-hi">${cfg.fmt(hi)}</span>` +
      `<span class="axis-lo">${cfg.fmt(lo)}</span>` +
    `</div>` +
    `<div class="chart-times"><span>${alertClock(t0)}</span><span>${alertClock(t1)}</span></div>` +
    (bucketed ? '<div class="chart-note">Shaded band = min–max within each 5-minute bucket</div>' : '');
}

function renderBigNetChart(chart, points, pick) {
  const rx = points.map(p => ({ t: p.t, s: pick(p, 'net_rx') })).filter(p => p.s);
  const tx = points.map(p => ({ t: p.t, s: pick(p, 'net_tx') })).filter(p => p.s);
  if (rx.length < 2 && tx.length < 2) {
    chart.innerHTML = '<div class="metric-loading">No network samples in this window yet.</div>';
    return;
  }
  const all = rx.concat(tx);
  const W = 600, H = 200, MID = H / 2;
  const t0 = Math.min(...all.map(p => p.t)), t1 = Math.max(...all.map(p => p.t));
  const span = Math.max(t1 - t0, 1);
  const peakRx = rx.length ? Math.max(...rx.map(p => p.s.max)) : 0;
  const peakTx = tx.length ? Math.max(...tx.map(p => p.s.max)) : 0;
  const scale = Math.max(peakRx, peakTx, 1);

  const x = t => ((t - t0) / span) * W;
  const trace = (pts, dir) => {
    if (pts.length < 2) return '';
    const y = v => MID - dir * (v / scale) * (MID - 1);
    const line = pts.map(p => `${x(p.t).toFixed(1)},${y(p.s.avg).toFixed(1)}`).join(' ');
    const area = `${x(pts[0].t).toFixed(1)},${MID} ${line} ${x(pts[pts.length - 1].t).toFixed(1)},${MID}`;
    return `<polygon class="spark-area" points="${area}"></polygon>` +
           `<polyline class="spark-line" vector-effect="non-scaling-stroke" points="${line}"></polyline>`;
  };

  chart.innerHTML =
    `<div class="chart-box">` +
      `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">` +
        `<g class="net-rx">${trace(rx, 1)}</g>` +
        `<g class="net-tx">${trace(tx, -1)}</g>` +
        `<line class="spark-mid" x1="0" y1="${MID}" x2="${W}" y2="${MID}" vector-effect="non-scaling-stroke"></line>` +
      `</svg>` +
      `<span class="axis-hi">↓ ${fmtRate(peakRx)}</span>` +
      `<span class="axis-lo">↑ ${fmtRate(peakTx)}</span>` +
    `</div>` +
    `<div class="chart-times"><span>${alertClock(t0)}</span><span>${alertClock(t1)}</span></div>`;
}

function renderMetricFigures(points, view, pick) {
  const box = document.getElementById('metric-figures');
  if (!box) return;
  const keys = view.mirrored ? ['net_rx', 'net_tx'] : [view.key];
  const rows = keys.map(k => {
    const s = points.map(p => pick(p, k)).filter(Boolean);
    if (!s.length) return '';
    const cfg = SPARK_CFG[k];
    const fmt = view.mirrored ? fmtRate : (cfg ? cfg.fmt : (v => Math.round(v)));
    const avg = s.reduce((a, b) => a + b.avg, 0) / s.length;
    const label = view.mirrored ? (k === 'net_rx' ? 'Download' : 'Upload') : 'Now';
    const nowVal = s[s.length - 1].avg;
    return `<div class="fig-row">
      <span class="fig-label">${label}</span>
      <span class="fig"><b>${fmt(nowVal)}</b><i>current</i></span>
      <span class="fig"><b>${fmt(Math.max(...s.map(v => v.max)))}</b><i>peak</i></span>
      <span class="fig"><b>${fmt(avg)}</b><i>avg</i></span>
      <span class="fig"><b>${fmt(Math.min(...s.map(v => v.min)))}</b><i>min</i></span>
    </div>`;
  }).join('');
  box.innerHTML = rows;
}

// Live specifics that don't come from the history series — read straight off the
// cards, which are already kept current by the stats poll.
function renderMetricDetail(view) {
  const box = document.getElementById('metric-detail');
  if (!box) return;
  const txt = id => (document.getElementById(id)?.textContent || '').trim();
  const bits = {
    cpu:   () => [txt('stat-cpu-freq'), txt('stat-load-sub')],
    ram:   () => [txt('stat-ram-detail'), 'Swap ' + txt('stat-swap')],
    swap:  () => [txt('stat-swap-detail')],
    temp:  () => [txt('stat-temp-sub')],
    power: () => [txt('stat-power-sub')],
    load:  () => [txt('stat-load-sub')],
    disk:  () => [txt('disk-trend')],
    net:   () => [txt('stat-nettotal') + ' since boot'],
  }[view.key === 'net_rx' ? 'net' : view.key];
  const parts = (bits ? bits() : []).filter(s => s && s !== '—');
  box.innerHTML = parts.length ? parts.map(escapeHtml).join(' · ') : '';
}

// Episodes for this metric that overlap the visible window.
function renderMetricAlerts(view, windowStart) {
  const box = document.getElementById('metric-alerts');
  if (!box) return;
  const metric = view.alertMetric || (view.key === 'net_rx' ? null : view.key);
  const hits = (_lastAlertEvents || []).filter(e =>
    e.kind !== 'service' && e.metric === metric && (e.ended_at ?? Infinity) >= windowStart);
  box.innerHTML = hits.length
    ? `<div class="metric-alerts-title">${hits.length} alert${hits.length === 1 ? '' : 's'} in this window</div>` +
      hits.slice(0, 5).map(e =>
        `<div class="ma-row"><span class="al-level ${e.level}">${e.level === 'critical' ? 'crit' : 'warn'}</span>` +
        `<span>peak ${escapeHtml(e.peak + (e.unit || ''))}</span>` +
        `<span class="al-when">${alertClock(e.started_at)}</span></div>`).join('')
    : '<div class="metric-alerts-title muted">No alerts for this metric in this window</div>';
}

if (metricOverlay) {
  document.getElementById('metric-close').addEventListener('click', closeMetric);
  metricOverlay.addEventListener('click', e => { if (e.target === metricOverlay) closeMetric(); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !metricOverlay.hidden) closeMetric();
  });
  document.getElementById('metric-ranges').addEventListener('click', e => {
    const btn = e.target.closest('.range-btn');
    if (!btn) return;
    _metricRange = Number(btn.dataset.minutes);
    document.querySelectorAll('#metric-ranges .range-btn')
      .forEach(b => b.classList.toggle('active', b === btn));
    loadMetricRange();
  });

  // Expandability is opted into per card with data-expand, not derived from
  // data-metric: the latter drives colour and is shared (Disk I/O and Storage are both
  // "disk"), and cards with nothing to plot (uptime, docker counts) must stay inert
  // rather than opening an empty modal.
  document.querySelectorAll('.stat-card[data-expand]').forEach(card => {
    const metric = card.dataset.expand;
    if (!METRIC_VIEWS[metric]) return;
    card.classList.add('expandable');
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.setAttribute('title', 'Click for the full graph');
    card.addEventListener('click', () => openMetric(metric));
    card.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openMetric(metric); }
    });
  });
}

/* ── Disk fill projection ───────────────────────────────────────────
   A least-squares fit over the persisted 5-minute buckets turns the disk
   series into a percent-per-day drift, and from there an estimate of when
   it reaches the 95% critical threshold. Anything under a day of history
   is noise, so it says so rather than inventing a number. */
let _diskTrend = null;

function diskSlope(pts) {
  if (pts.length < 2) return null;
  const hours = (pts[pts.length - 1].t - pts[0].t) / 3600;
  if (hours < 24) return { hours, insufficient: true };

  const t0 = pts[0].t, n = pts.length;
  let sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (const p of pts) {
    const x = (p.t - t0) / 86400;          // days since the first sample
    sx += x; sy += p.v; sxx += x * x; sxy += x * p.v;
  }
  const denom = n * sxx - sx * sx;
  if (Math.abs(denom) < 1e-9) return { hours, insufficient: true };

  const perDay = (n * sxy - sx * sy) / denom;
  const latest = pts[pts.length - 1].v;
  return {
    hours, perDay, latest,
    daysToCrit: perDay > 0.01 ? (95 - latest) / perDay : null,
  };
}

async function fetchDiskTrend() {
  const data = await apiFetch('/api/history?minutes=10080');   // 7 days of buckets
  if (!data || !Array.isArray(data.points)) return false;
  const pts = data.points
    .map(p => ({ t: p.t, v: (p.disk && p.disk.avg != null) ? p.disk.avg : p.disk }))
    .filter(p => typeof p.v === 'number' && !isNaN(p.v));
  _diskTrend = diskSlope(pts);
  renderDiskTrend();
  return true;
}

function renderDiskTrend() {
  const el = document.getElementById('disk-trend');
  if (!el) return;
  const t = _diskTrend;
  if (!t) { el.textContent = 'collecting usage history…'; return; }
  if (t.insufficient) {
    el.textContent = `collecting usage history — ${Math.round(t.hours)}h of 24h`;
    return;
  }
  if (t.perDay > 0.01) {
    const bits = [`+${t.perDay.toFixed(2)}%/day`];
    if (t.daysToCrit != null && t.daysToCrit < 400) {
      bits.push(t.daysToCrit < 1 ? 'hits 95% within a day' : `95% in ~${Math.round(t.daysToCrit)} days`);
    }
    el.textContent = bits.join(' · ');
  } else if (t.perDay < -0.01) {
    el.textContent = `${t.perDay.toFixed(2)}%/day · freeing up`;
  } else {
    el.textContent = 'stable';
  }
}

function renderVolumes(volumes) {
  const list = document.getElementById('volumes-list');
  if (!list) return;
  if (!Array.isArray(volumes) || !volumes.length) {
    list.innerHTML = '<div class="stat-sub">N/A</div>';
    return;
  }
  list.innerHTML = volumes.map(v => {
    const pct = v.percent ?? 0;
    const cls = pct >= 90 ? ' critical' : pct >= 75 ? ' hot' : '';
    const tag = v.internal ? '' : '<span class="vol-tag">ext</span>';
    return `<div class="vol-row">
      <div class="vol-head">
        <span class="vol-name">${escapeHtml(v.name)}${tag}</span>
        <span class="vol-figs">${v.used_gb} / ${v.total_gb} GB · ${pct}%</span>
      </div>
      <div class="stat-bar-wrap"><div class="stat-bar${cls}" style="width:${Math.min(pct, 100)}%"></div></div>
    </div>`;
  }).join('');
}

function renderStatsError() {
  ['stat-cpu','stat-ram','stat-swap','stat-temp','stat-net','stat-uptime','stat-diskio',
   'stat-power','stat-load','stat-nettotal','stat-docker'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = '—'; el.style.color = 'var(--offline)'; }
  });
  ['stat-ram-detail','stat-swap-detail','stat-cpu-freq',
   'stat-power-sub','stat-load-sub','stat-temp-sub'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '';
  });
  ['bar-cpu','bar-ram','bar-swap'].forEach(id => {
    const bar = document.getElementById(id);
    if (bar) bar.style.width = '0%';
  });
  const volList = document.getElementById('volumes-list');
  if (volList) volList.innerHTML = '<div class="stat-sub">—</div>';
  setBadgeError('badge-mac');
}

let usingRealStats = false;
let uptimeOffset = 0;

async function fetchAndRenderStats() {
  const data = await apiFetch('/api/stats');
  if (data) {
    renderStats(data);
    setBadgeLive('badge-mac');
    usingRealStats = true;
    return true;
  }
  return false;
}

// Uptime ticker
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
  if (!ok) { usingRealStats = false; renderStatsError(); }
}, 5000);

/* ─────────────────────────────────────────────────────────────────
   SERVICES & PROJECTS STATUS
   ───────────────────────────────────────────────────────────────── */

async function fetchAndRenderServices() {
  const data = await apiFetch('/api/services');
  if (!data) return false;

  const svcArr  = data.services  || [];
  const projArr = data.projects  || [];

  updateServiceStatuses(svcArr);
  updateProjectStatuses(projArr);
  setBadgeLive('badge-servers');
  return true;
}

function renderServicesError() {
  document.querySelectorAll('.server-card .status-badge').forEach(badge => {
    badge.className = 'status-badge offline';
    badge.textContent = 'Offline';
  });
  document.querySelectorAll('.status-dot').forEach(dot => {
    dot.className = 'status-dot offline';
  });
  setBadgeError('badge-servers');
}

// Services refresh every 30s
setInterval(async () => {
  const ok = await fetchAndRenderServices();
  if (!ok) renderServicesError();
}, 30000);

/* ─────────────────────────────────────────────────────────────────
   TAILSCALE DEVICES
   ───────────────────────────────────────────────────────────────── */

// Simple, universally-rendering device glyphs by OS family (no emoji).
function osGlyph(os) {
  const o = String(os || '').toLowerCase();
  if (o.includes('ios') || o.includes('ipad') || o.includes('android')) return '▯'; // phone/tablet
  if (o.includes('mac') || o.includes('linux') || o.includes('windows') || o.includes('bsd')) return '▤'; // computer
  return '▢';
}

function relTime(iso) {
  if (!iso || String(iso).startsWith('0001')) return '';
  const t = Date.parse(iso);
  if (isNaN(t)) return '';
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60)    return 'just now';
  if (s < 3600)  return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

function renderTailnetCards(devices) {
  const grid = document.getElementById('tailnet-grid');
  if (!grid) return;
  if (!Array.isArray(devices) || !devices.length) {
    grid.innerHTML = '<div class="card placeholder-card">No devices found.</div>';
    return;
  }
  grid.innerHTML = devices.map(d => {
    const cls  = d.online ? 'online' : 'offline';
    const self = d.is_self ? '<span class="ts-self-tag">this machine</span>' : '';
    const seen = !d.online ? relTime(d.last_seen) : '';
    const sub  = [escapeHtml(d.os || '?'), escapeHtml(d.ip || '')].filter(Boolean).join(' · ')
               + (seen ? ` · seen ${seen}` : '');
    return `<div class="card tailnet-card ${cls}">
      <span class="ts-os">${osGlyph(d.os)}</span>
      <div class="ts-body">
        <div class="ts-name">${escapeHtml(d.name)}${self}</div>
        <div class="ts-sub">${sub}</div>
      </div>
      <span class="status-dot ${cls}"></span>
    </div>`;
  }).join('');
}

async function fetchAndRenderTailnet() {
  const data = await apiFetch('/api/tailscale');
  if (!data || !data.devices) return false;
  renderTailnetCards(data.devices);
  const online = data.devices.filter(d => d.online).length;
  const badge = document.getElementById('badge-tailnet');
  if (badge) { badge.textContent = `${online}/${data.devices.length} online`; badge.className = 'badge badge-live'; }
  return true;
}

setInterval(async () => {
  const ok = await fetchAndRenderTailnet();
  if (!ok) setBadgeError('badge-tailnet');
}, 20000);

/* ─────────────────────────────────────────────────────────────────
   DOCKER CONTAINERS
   ───────────────────────────────────────────────────────────────── */

function renderDockerCards(containers) {
  const grid = document.getElementById('docker-grid');
  if (!grid) return;
  if (!Array.isArray(containers) || !containers.length) {
    grid.innerHTML = '<div class="card placeholder-card">No running containers.</div>';
    return;
  }
  const heat = (v, hot, crit) => v >= crit ? ' critical' : v >= hot ? ' hot' : '';
  grid.innerHTML = containers.map(c => {
    const cpu = c.cpu_pct ?? 0;
    const mem = c.mem_pct ?? 0;
    return `<div class="card docker-card">
      <div class="dk-name">${escapeHtml(c.name)}</div>
      <div class="dk-metric">
        <div class="dk-metric-head"><span>CPU</span><span class="dk-val">${cpu}%</span></div>
        <div class="dk-bar-wrap"><div class="dk-bar cpu${heat(cpu, 60, 90)}" style="width:${Math.min(cpu, 100)}%"></div></div>
      </div>
      <div class="dk-metric">
        <div class="dk-metric-head"><span>MEM</span><span class="dk-val">${escapeHtml(c.mem || mem + '%')}</span></div>
        <div class="dk-bar-wrap"><div class="dk-bar mem${heat(mem, 75, 90)}" style="width:${Math.min(mem, 100)}%"></div></div>
      </div>
    </div>`;
  }).join('');
}

async function fetchAndRenderDocker() {
  const data = await apiFetch('/api/docker');
  if (!data || !data.containers) return false;
  renderDockerCards(data.containers);
  const badge = document.getElementById('badge-docker');
  if (badge) { badge.textContent = `${data.containers.length} running`; badge.className = 'badge badge-live'; }
  return true;
}

setInterval(async () => {
  const ok = await fetchAndRenderDocker();
  if (!ok) setBadgeError('badge-docker');
}, 15000);

/* ─────────────────────────────────────────────────────────────────
   ALERTS / OVERLOAD LOG
   Episodes are detected + recorded server-side (24/7); we just render the
   history here and flash the badge when a new one appears while you're viewing.
   ───────────────────────────────────────────────────────────────── */

function alertClock(epoch) {
  return new Date(epoch * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
function alertDate(epoch) {
  return new Date(epoch * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
// Compact elapsed time between two epoch-seconds values: "45s", "8m", "1h 12m".
function alertDuration(from, to) {
  const s = Math.max(0, (to || Math.floor(Date.now() / 1000)) - from);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
function alertSameDay(epoch) {
  const d = new Date(epoch * 1000), n = new Date();
  return d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate();
}

let _lastAlertId = null;  // newest episode id at the previous render (drives the flash)
let _lastAlertEvents = [];

function renderAlertRows(events) {
  const box = document.getElementById('alert-log');
  if (!box) return;
  if (!Array.isArray(events) || !events.length) {
    box.innerHTML = '<div class="alert-empty">No alerts — all clear.</div>';
    return;
  }
  box.innerHTML = events.map(e => {
    const ongoing = e.ended_at == null;
    const lvl = e.level === 'critical' ? 'critical' : 'warning';
    // Episodes written before service outages existed have no `kind` — treat those
    // as metric episodes so an older alerts.json still renders.
    const isService = e.kind === 'service';
    const start = (alertSameDay(e.started_at) ? '' : alertDate(e.started_at) + ' ') + alertClock(e.started_at);
    const when = ongoing
      ? `${start} · <span class="al-ongoing">ongoing ${alertDuration(e.started_at, null)}</span>`
      : `${start} → ${alertClock(e.ended_at)} · ${alertDuration(e.started_at, e.ended_at)}`;
    // A service is either reachable or not — there's no peak or threshold to show,
    // so that column carries the outage duration instead.
    const detail = isService
      ? `<span class="al-peak">unreachable</span>
         <span class="al-level down">down</span>`
      : `<span class="al-peak">peak ${escapeHtml(e.peak + (e.unit || ''))}</span>
         <span class="al-level ${lvl}">${lvl === 'critical' ? 'crit' : 'warn'}</span>`;
    return `<div class="alert-row ${lvl}${ongoing ? ' ongoing' : ''}${isService ? ' service' : ''}">
      <span class="al-mark">${isService ? '×' : (lvl === 'critical' ? '!!' : '!')}</span>
      <span class="al-metric">${escapeHtml(e.label)}</span>
      ${detail}
      <span class="al-when">${when}</span>
    </div>`;
  }).join('');
}

async function fetchAndRenderAlerts() {
  const data = await apiFetch('/api/alerts');
  if (!data || !data.events) return false;
  _lastAlertEvents = data.events;   // reused by the metric modal's per-metric list
  renderAlertRows(data.events);

  const active = data.events.filter(e => e.ended_at == null).length;
  const badge = document.getElementById('badge-alerts');
  if (badge) {
    const n = data.events.length;
    badge.textContent = active ? `${active} active` : `${n} event${n === 1 ? '' : 's'}`;
    badge.className = 'badge ' + (active ? 'badge-error' : 'badge-live');
    // In-page highlight: flash the badge when a new episode has appeared this session.
    const newest = n ? data.events[0].id : null;
    if (newest != null && _lastAlertId != null && newest !== _lastAlertId) {
      void badge.offsetWidth;          // restart the animation
      badge.classList.add('badge-flash');
    }
    _lastAlertId = newest;
  }
  return true;
}

setInterval(async () => {
  const ok = await fetchAndRenderAlerts();
  if (!ok) setBadgeError('badge-alerts');
}, 30000);

/* ─────────────────────────────────────────────────────────────────
   HEADER CLOCK + GREETING
   ───────────────────────────────────────────────────────────────── */

function updateClock() {
  const now = new Date();
  const h = now.getHours();
  const greet = h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  const te = document.getElementById('clock-time');
  const ge = document.getElementById('clock-greet');
  if (te) te.textContent = now.toLocaleTimeString([], { hour12: false });
  if (ge) ge.textContent = greet;
}
setInterval(updateClock, 1000);
updateClock();

/* ─────────────────────────────────────────────────────────────────
   COMMAND PALETTE  ( / or Cmd/Ctrl-K )
   ───────────────────────────────────────────────────────────────── */

const cmdkOverlay = document.getElementById('cmdk-overlay');
const cmdkInput   = document.getElementById('cmdk-input');
const cmdkList    = document.getElementById('cmdk-list');
let cmdkItems = [];
let cmdkActive = 0;

function buildCmdkIndex() {
  const items = [];
  document.querySelectorAll('.section-title').forEach(h => {
    items.push({ name: h.textContent.replace(/\s+/g, ' ').trim(), kind: 'section', icon: '≡', el: h.closest('.section') });
  });
  document.querySelectorAll('#projects-grid .project-card').forEach(a => {
    items.push({ name: (a.querySelector('.card-name')?.textContent || '').trim(), kind: 'project', icon: '◈', url: a.href });
  });
  document.querySelectorAll('#services-grid .server-card').forEach(c => {
    items.push({ name: (c.querySelector('.server-name')?.textContent || '').trim(), kind: 'service', icon: '◉', el: c });
  });
  document.querySelectorAll('#downloads-grid .download-card').forEach(c => {
    const a = c.querySelector('.card-name a');
    items.push({ name: (a?.textContent || '').trim(), kind: 'download', icon: '↧', url: a?.href });
  });
  document.querySelectorAll('#tailnet-grid .tailnet-card').forEach(c => {
    items.push({ name: (c.querySelector('.ts-name')?.textContent || '').trim(), kind: 'device', icon: '⇄', el: c });
  });
  SKINS.forEach(s => {
    items.push({ name: `Skin: ${s.name}`, kind: 'skin', icon: '◐', run: () => applySkin(s.id) });
  });
  return items.filter(i => i.name);
}

function fuzzyMatch(query, text) {
  query = query.toLowerCase(); text = text.toLowerCase();
  if (!query) return true;
  let i = 0;
  for (const ch of text) { if (ch === query[i]) i++; if (i === query.length) return true; }
  return false;
}

function renderCmdkList() {
  const q = cmdkInput.value.trim();
  const matches = cmdkItems.filter(i => fuzzyMatch(q, i.name)).slice(0, 40);
  if (cmdkActive >= matches.length) cmdkActive = 0;
  if (!matches.length) {
    cmdkList.innerHTML = '<div class="cmdk-empty">No matches</div>';
    cmdkList._matches = [];
    return;
  }
  cmdkList.innerHTML = matches.map((m, idx) =>
    `<div class="cmdk-item ${idx === cmdkActive ? 'active' : ''}" data-idx="${idx}">
      <span class="ci-icon">${m.icon}</span>
      <span class="ci-name">${escapeHtml(m.name)}</span>
      <span class="ci-kind">${m.kind}</span>
    </div>`).join('');
  cmdkList._matches = matches;
}

function activateCmdk(item) {
  closeCmdk();
  if (!item) return;
  if (item.run) { item.run(); return; }
  if (item.url) { window.open(item.url, '_blank', 'noopener'); return; }
  if (item.el) {
    item.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    item.el.style.transition = 'outline 0.2s';
    item.el.style.outline = '2px solid var(--accent)';
    setTimeout(() => { item.el.style.outline = ''; }, 1200);
  }
}

function openCmdk() {
  cmdkItems = buildCmdkIndex();
  cmdkActive = 0;
  cmdkInput.value = '';
  cmdkOverlay.hidden = false;
  renderCmdkList();
  cmdkInput.focus();
}
function closeCmdk() { cmdkOverlay.hidden = true; }

if (cmdkOverlay) {
  cmdkInput.addEventListener('input', () => { cmdkActive = 0; renderCmdkList(); });
  cmdkList.addEventListener('click', e => {
    const item = e.target.closest('.cmdk-item');
    if (item) activateCmdk((cmdkList._matches || [])[+item.dataset.idx]);
  });
  cmdkOverlay.addEventListener('click', e => { if (e.target === cmdkOverlay) closeCmdk(); });
  cmdkInput.addEventListener('keydown', e => {
    const matches = cmdkList._matches || [];
    if (e.key === 'ArrowDown') { e.preventDefault(); cmdkActive = Math.min(cmdkActive + 1, matches.length - 1); renderCmdkList(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); cmdkActive = Math.max(cmdkActive - 1, 0); renderCmdkList(); }
    else if (e.key === 'Enter') { e.preventDefault(); activateCmdk(matches[cmdkActive]); }
    else if (e.key === 'Escape') { closeCmdk(); }
  });
}

document.addEventListener('keydown', e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) ||
                 document.activeElement?.isContentEditable;
  if ((e.key === 'k' && (e.metaKey || e.ctrlKey)) || (e.key === '/' && !typing)) {
    e.preventDefault();
    if (cmdkOverlay) (cmdkOverlay.hidden ? openCmdk() : closeCmdk());
  }
});

/* ─────────────────────────────────────────────────────────────────
   LOG VIEWER
   ───────────────────────────────────────────────────────────────── */

const logViewer  = document.getElementById('log-viewer');
const logSelect  = document.getElementById('log-server');
const logContainer = document.getElementById('log-container');
const logRefresh = document.getElementById('log-refresh');
const logFollow  = document.getElementById('log-follow');

/* Update the container sub-selector based on the chosen service */
function updateContainerSelector(services) {
  if (!logContainer) return;
  const svcId = logSelect.value;
  const svc = (services || _config.services || []).find(s => s.id === svcId);
  const containers = svc?.containers;
  if (containers && containers.length > 1) {
    const prev = logContainer.value;
    logContainer.innerHTML = containers.map(c =>
      `<option value="${escapeHtml(c.docker)}">${escapeHtml(c.label)}</option>`
    ).join('');
    if (prev && containers.find(c => c.docker === prev)) logContainer.value = prev;
    logContainer.hidden = false;
  } else {
    logContainer.innerHTML = '';
    logContainer.hidden = true;
  }
}

function renderLogLines(lines) {
  if (!lines.length) {
    logViewer.innerHTML = '<div class="log-line"><span class="log-msg" style="color:var(--text-muted)">No log lines available.</span></div>';
    return;
  }
  logViewer.innerHTML = lines.map(({ time, level, msg }) => `
    <div class="log-line">
      <span class="log-time">${escapeHtml(time ?? '——')}</span>
      <span class="log-level ${escapeHtml(level ?? 'INFO')}">${escapeHtml(level ?? 'INFO')}</span>
      <span class="log-msg">${escapeHtml(msg ?? '')}</span>
    </div>
  `).join('');
  if (logFollow.checked) logViewer.scrollTop = logViewer.scrollHeight;
}

async function refreshLog() {
  const server = logSelect.value;
  if (!server) return;
  let url = `/api/logs?service=${server}&lines=50`;
  if (logContainer && !logContainer.hidden && logContainer.value) {
    url += `&container=${encodeURIComponent(logContainer.value)}`;
  }
  const data = await apiFetch(url);
  if (data && data.lines && data.lines.length > 0) {
    renderLogLines(data.lines);
    setBadgeLive('badge-logs');
  } else {
    logViewer.innerHTML = `
      <div class="log-line">
        <span class="log-level ERROR">ERROR</span>
        <span class="log-msg" style="color:var(--offline)">Can't connect to API — make sure the Mac mini is reachable and the server is running.</span>
      </div>`;
    setBadgeError('badge-logs');
  }
}

logSelect.addEventListener('change', () => { updateContainerSelector(); refreshLog(); });
logRefresh.addEventListener('click', refreshLog);
if (logContainer) logContainer.addEventListener('change', refreshLog);
setInterval(refreshLog, 10000);

/* ─────────────────────────────────────────────────────────────────
   SETTINGS MODAL
   ───────────────────────────────────────────────────────────────── */

const modalOverlay = document.getElementById('modal-overlay');
const settingsBtn  = document.getElementById('settings-btn');
const modalClose   = document.getElementById('modal-close');
const saveStatus   = document.getElementById('save-status');
const btnSave      = document.getElementById('btn-save');
const writeTokenEl = document.getElementById('write-token');
const rememberTokenEl = document.getElementById('remember-token');
const WRITE_TOKEN_KEY = 'homepage_write_token';

// Prefill a remembered write token (opt-in — stored locally in this browser only).
(function restoreWriteToken() {
  const saved = localStorage.getItem(WRITE_TOKEN_KEY);
  if (saved) {
    writeTokenEl.value = saved;
    if (rememberTokenEl) rememberTokenEl.checked = true;
  }
})();

// Unchecking "Remember" forgets the stored token right away.
if (rememberTokenEl) {
  rememberTokenEl.addEventListener('change', () => {
    if (!rememberTokenEl.checked) localStorage.removeItem(WRITE_TOKEN_KEY);
  });
}

function openSettings() {
  populateSettingsModal(_config);
  modalOverlay.hidden = false;
  document.body.style.overflow = 'hidden';
}

function closeSettings() {
  modalOverlay.hidden = true;
  document.body.style.overflow = '';
  saveStatus.textContent = '';
  saveStatus.className = 'save-status';
}

settingsBtn.addEventListener('click', openSettings);
modalClose.addEventListener('click', closeSettings);
modalOverlay.addEventListener('click', e => { if (e.target === modalOverlay) closeSettings(); });

// Tab switching
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
    btn.classList.add('active');
    document.getElementById(`tab-${btn.dataset.tab}`).classList.remove('hidden');
  });
});

/* Settings list rendering */
function archiveToggleHtml(checked) {
  return `<label class="entry-archive"><input type="checkbox" data-field="archived" ${checked ? 'checked' : ''} /> Archived</label>`;
}

function makeDeleteBtn(onClick) {
  const btn = document.createElement('button');
  btn.className = 'btn-delete';
  btn.textContent = '🗑';
  btn.title = 'Delete';
  btn.addEventListener('click', onClick);
  return btn;
}

/* ─────────────────────────────────────────────────────────────────
   LOG SETTINGS HELPERS
   ───────────────────────────────────────────────────────────────── */

let _logKeyCounter = 0;

function makeContainerEntry(label = '', docker = '') {
  const div = document.createElement('div');
  div.className = 'log-container-entry';
  div.innerHTML = `
    <input type="text" data-field="container-label"  value="${escapeHtml(label)}"  placeholder="Label (e.g. Server)" />
    <input type="text" data-field="container-docker" value="${escapeHtml(docker)}" placeholder="Docker container name" />`;
  div.appendChild(makeDeleteBtn(() => div.remove()));
  return div;
}

function makeLogSourceSection(svc) {
  const key = ++_logKeyCounter;
  const section = document.createElement('div');
  section.className = 'log-svc-section';
  section.dataset.logKey = key;

  const header = document.createElement('div');
  header.className = 'log-svc-header';
  header.textContent = svc.name || 'Unnamed service';
  section.appendChild(header);

  const list = document.createElement('div');
  list.className = 'log-containers-list';
  section.appendChild(list);

  const containers = svc.containers || (svc.docker ? [{ label: 'Default', docker: svc.docker }] : []);
  containers.forEach(c => list.appendChild(makeContainerEntry(c.label, c.docker)));

  const addBtn = document.createElement('button');
  addBtn.className = 'btn-add-small';
  addBtn.textContent = '+ Add container';
  addBtn.type = 'button';
  addBtn.addEventListener('click', () => list.appendChild(makeContainerEntry()));
  section.appendChild(addBtn);

  return { section, key };
}

function populateSettingsModal(config) {
  // Projects
  const projList = document.getElementById('proj-list');
  projList.innerHTML = '';
  (config.projects || []).forEach((p, i) => {
    const li = document.createElement('li');
    li.className = 'settings-entry';
    li.innerHTML = `
      <span class="entry-icon">${escapeHtml(p.icon)}</span>
      <div class="entry-fields">
        <input type="text" data-field="name"       value="${escapeHtml(p.name)}"       placeholder="Name"    />
        <input type="text" data-field="icon"       value="${escapeHtml(p.icon)}"       placeholder="Icon"    maxlength="4" />
        <input type="text" data-field="desc"       value="${escapeHtml(p.desc)}"       placeholder="Description" />
        <input type="url"  data-field="url"        value="${escapeHtml(p.url)}"        placeholder="URL"     />
        <input type="url"  data-field="check_url"  value="${escapeHtml(p.check_url || p.url)}" placeholder="Check URL" />
        <select data-field="visibility">
          <option value="public"  ${p.visibility === 'public'  ? 'selected' : ''}>Public</option>
          <option value="private" ${p.visibility === 'private' ? 'selected' : ''}>Private</option>
        </select>
        ${archiveToggleHtml(p.archived)}
      </div>`;
    li.appendChild(makeDeleteBtn(() => { li.remove(); }));
    projList.appendChild(li);
  });

  // Services + Logs tab (built together to keep them linked)
  const svcList = document.getElementById('svc-list');
  const logSourcesList = document.getElementById('log-sources-list');
  svcList.innerHTML = '';
  logSourcesList.innerHTML = '';
  (config.services || []).forEach((s) => {
    const { section, key } = makeLogSourceSection(s);
    logSourcesList.appendChild(section);

    const li = document.createElement('li');
    li.className = 'settings-entry';
    li.dataset.logKey = key;
    li.innerHTML = `
      <div class="entry-fields">
        <input type="text"   data-field="name"   value="${escapeHtml(s.name)}"   placeholder="Name"   />
        <input type="text"   data-field="detail" value="${escapeHtml(s.detail || '')}" placeholder="Detail (e.g. :3000)" />
        <input type="number" data-field="port"   value="${escapeHtml(s.port ?? '')}"  placeholder="Port"   min="1" max="65535" />
        <input type="url"    data-field="check_url" value="${escapeHtml(s.check_url || '')}" placeholder="Check URL (optional)" />
        <input type="text"   data-field="docker" value="${escapeHtml(s.docker || '')}" placeholder="Docker container (optional)" />
        ${archiveToggleHtml(s.archived)}
      </div>`;
    li.appendChild(makeDeleteBtn(() => {
      document.querySelector(`.log-svc-section[data-log-key="${key}"]`)?.remove();
      li.remove();
    }));
    svcList.appendChild(li);
  });
}

/* Add buttons */
document.getElementById('btn-add-proj').addEventListener('click', () => {
  const name  = document.getElementById('add-proj-name').value.trim();
  const icon  = document.getElementById('add-proj-icon').value.trim() || '🔗';
  const desc  = document.getElementById('add-proj-desc').value.trim();
  const url   = document.getElementById('add-proj-url').value.trim();
  const check = document.getElementById('add-proj-check').value.trim() || url;
  const vis   = document.getElementById('add-proj-vis').value;
  if (!name || !url) return alert('Name and URL are required.');

  const fake = { id: slugify(name), name, icon, desc, url, check_url: check, visibility: vis };
  const li = document.createElement('li');
  li.className = 'settings-entry';
  li.innerHTML = `
    <span class="entry-icon">${escapeHtml(icon)}</span>
    <div class="entry-fields">
      <input type="text" data-field="name"      value="${escapeHtml(name)}"  placeholder="Name"    />
      <input type="text" data-field="icon"      value="${escapeHtml(icon)}"  placeholder="Icon"    maxlength="4" />
      <input type="text" data-field="desc"      value="${escapeHtml(desc)}"  placeholder="Description" />
      <input type="url"  data-field="url"       value="${escapeHtml(url)}"   placeholder="URL"     />
      <input type="url"  data-field="check_url" value="${escapeHtml(check)}" placeholder="Check URL" />
      <select data-field="visibility">
        <option value="public"  ${vis === 'public'  ? 'selected' : ''}>Public</option>
        <option value="private" ${vis === 'private' ? 'selected' : ''}>Private</option>
      </select>
      ${archiveToggleHtml(false)}
    </div>`;
  li.appendChild(makeDeleteBtn(() => li.remove()));
  document.getElementById('proj-list').appendChild(li);

  // Clear form
  ['add-proj-name','add-proj-icon','add-proj-desc','add-proj-url','add-proj-check'].forEach(id => {
    document.getElementById(id).value = '';
  });
});

document.getElementById('btn-add-svc').addEventListener('click', () => {
  const name   = document.getElementById('add-svc-name').value.trim();
  const detail = document.getElementById('add-svc-detail').value.trim();
  const port   = document.getElementById('add-svc-port').value.trim();
  const check  = document.getElementById('add-svc-check').value.trim();
  const docker = document.getElementById('add-svc-docker').value.trim();
  if (!name) return alert('Name is required.');

  const { section, key } = makeLogSourceSection({ name, docker, containers: [] });
  document.getElementById('log-sources-list').appendChild(section);

  const li = document.createElement('li');
  li.className = 'settings-entry';
  li.dataset.logKey = key;
  li.innerHTML = `
    <div class="entry-fields">
      <input type="text"   data-field="name"      value="${escapeHtml(name)}"   placeholder="Name"   />
      <input type="text"   data-field="detail"    value="${escapeHtml(detail)}" placeholder="Detail" />
      <input type="number" data-field="port"      value="${escapeHtml(port)}"   placeholder="Port"   min="1" max="65535" />
      <input type="url"    data-field="check_url" value="${escapeHtml(check)}"  placeholder="Check URL" />
      <input type="text"   data-field="docker"    value="${escapeHtml(docker)}" placeholder="Docker container" />
      ${archiveToggleHtml(false)}
    </div>`;
  li.appendChild(makeDeleteBtn(() => {
    document.querySelector(`.log-svc-section[data-log-key="${key}"]`)?.remove();
    li.remove();
  }));
  document.getElementById('svc-list').appendChild(li);

  ['add-svc-name','add-svc-detail','add-svc-port','add-svc-check','add-svc-docker'].forEach(id => {
    document.getElementById(id).value = '';
  });
});

/* Collect config from modal */
function collectConfig() {
  const projects = [];
  document.querySelectorAll('#proj-list .settings-entry').forEach(li => {
    const get = f => li.querySelector(`[data-field="${f}"]`)?.value.trim() ?? '';
    const name = get('name');
    const url  = get('url');
    if (!name || !url) return;
    projects.push({
      id:         slugify(name),
      name,
      icon:       get('icon') || '🔗',
      desc:       get('desc'),
      url,
      check_url:  get('check_url') || url,
      visibility: get('visibility') || 'public',
      archived:   li.querySelector('[data-field="archived"]')?.checked || undefined,
    });
  });

  const services = [];
  document.querySelectorAll('#svc-list .settings-entry').forEach(li => {
    const get = f => li.querySelector(`[data-field="${f}"]`)?.value.trim() ?? '';
    const name = get('name');
    if (!name) return;
    const portVal = parseInt(get('port'), 10);

    // Read containers from linked log section
    const key = li.dataset.logKey;
    const logSection = key ? document.querySelector(`.log-svc-section[data-log-key="${key}"]`) : null;
    const containers = [];
    if (logSection) {
      logSection.querySelectorAll('.log-container-entry').forEach(entry => {
        const label  = entry.querySelector('[data-field="container-label"]')?.value.trim() ?? '';
        const docker = entry.querySelector('[data-field="container-docker"]')?.value.trim() ?? '';
        if (docker) containers.push({ label: label || docker, docker });
      });
    }

    const dockerField = get('docker') || null;
    const primaryDocker = containers.length > 0 ? containers[0].docker : dockerField;
    services.push({
      id:         slugify(name),
      name,
      detail:     get('detail'),
      port:       isNaN(portVal) ? null : portVal,
      check_url:  get('check_url') || null,
      docker:     primaryDocker,
      containers: containers.length > 0 ? containers : undefined,
      log_file:   null,
      archived:   li.querySelector('[data-field="archived"]')?.checked || undefined,
    });
  });

  return { projects, services };
}

/* Save */
btnSave.addEventListener('click', async () => {
  const token = writeTokenEl.value.trim();
  if (!token) {
    saveStatus.textContent = 'Enter your write token first.';
    saveStatus.className = 'save-status error';
    return;
  }

  const newConfig = collectConfig();
  saveStatus.textContent = 'Saving…';
  saveStatus.className = 'save-status';
  btnSave.disabled = true;

  try {
    const sep = API_TOKEN ? '?' : '';
    const url = `${API_BASE}/api/config?token=${token}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    const res = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newConfig),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }
    // Remember the token for next time if opted in.
    if (rememberTokenEl && rememberTokenEl.checked) {
      localStorage.setItem(WRITE_TOKEN_KEY, token);
    }
    // Update local config and re-render
    _config = newConfig;
    renderConfig(newConfig);
    refreshLog();
    // Fetch fresh statuses immediately
    setTimeout(() => fetchAndRenderServices(), 500);

    saveStatus.textContent = '✓ Saved!';
    saveStatus.className = 'save-status ok';
    setTimeout(() => { saveStatus.textContent = ''; }, 3000);
  } catch (err) {
    saveStatus.textContent = `Error: ${err.message}`;
    saveStatus.className = 'save-status error';
  } finally {
    btnSave.disabled = false;
  }
});

/* ─────────────────────────────────────────────────────────────────
   BOOT SEQUENCE
   ───────────────────────────────────────────────────────────────── */

(async () => {
  // 1. Load config — render skeleton cards from it
  const config = await apiFetch('/api/config');
  if (config && (config.projects || config.services)) {
    _config = config;
  }
  renderConfig(_config);

  // 1b. Downloads — sourced from GitHub, independent of the Mac mini API
  initDownloads();

  // 2. Backfill sparkline history (server-side ring), then load live stats
  await seedSparksFromHistory();
  const statsOk = await fetchAndRenderStats();
  if (!statsOk) renderStatsError();

  // 3. Load service/project statuses (already checked by the server)
  const svcOk = await fetchAndRenderServices();
  if (!svcOk) renderServicesError();

  // 3b. Tailscale devices + Docker container stats + alert/overload log
  if (!(await fetchAndRenderTailnet())) setBadgeError('badge-tailnet');
  if (!(await fetchAndRenderDocker()))  setBadgeError('badge-docker');
  if (!(await fetchAndRenderAlerts()))  setBadgeError('badge-alerts');

  // 3c. Disk fill trend — needs the long (bucketed) history, so it's its own fetch.
  fetchDiskTrend();
  setInterval(fetchDiskTrend, 10 * 60 * 1000);

  // 4. Load logs for the first service
  refreshLog();
})();

/* ── PWA service worker ─────────────────────────────────────────── */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(err => console.warn('SW registration failed:', err));
  });
}

