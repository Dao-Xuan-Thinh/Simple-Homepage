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
          disk, disk_used_gb, disk_total_gb,
          disk_read_mbs, disk_write_mbs,
          uptime, net_tx, net_rx, temp, thermal_pressure, cpu_freq_ghz } = d;

  const upEl = document.getElementById('stat-uptime');
  if (upEl) { upEl._baseUptime = uptime; uptimeOffset = 0; }

  document.getElementById('stat-cpu').textContent  = cpu + '%';
  document.getElementById('stat-ram').textContent  = ram + '%';
  document.getElementById('stat-swap').textContent = swap != null ? swap + '%' : 'N/A';
  document.getElementById('stat-disk').textContent = disk + '%';
  const tempEl = document.getElementById('stat-temp');
  if (temp != null) {
    tempEl.textContent = temp + '°C';
    tempEl.style.color = '';
  } else if (thermal_pressure) {
    const pressureColors = { Nominal: '', Moderate: 'var(--warning)', Heavy: 'var(--offline)', Sleeping: '' };
    tempEl.textContent = thermal_pressure;
    tempEl.style.color = pressureColors[thermal_pressure] ?? '';
  } else {
    tempEl.textContent = 'N/A';
  }
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

  // Reset text color (in case we were in error state)
  ['stat-cpu','stat-ram','stat-swap','stat-disk','stat-temp','stat-net','stat-uptime','stat-diskio'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.color = '';
  });

  setBar('bar-cpu',  cpu);
  setBar('bar-ram',  ram);
  setBar('bar-swap', swap ?? 0);
  setBar('bar-disk', disk);
}

function renderStatsError() {
  ['stat-cpu','stat-ram','stat-swap','stat-disk','stat-temp','stat-net','stat-uptime','stat-diskio'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = '—'; el.style.color = 'var(--offline)'; }
  });
  ['stat-ram-detail','stat-swap-detail','stat-disk-detail','stat-cpu-freq'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '';
  });
  ['bar-cpu','bar-ram','bar-swap','bar-disk'].forEach(id => {
    const bar = document.getElementById(id);
    if (bar) bar.style.width = '0%';
  });
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
    // Update local config and re-render
    _config = newConfig;
    renderProjectCards(newConfig.projects);
    renderServiceCards(newConfig.services);
    populateLogSelector(newConfig.services);
    updateContainerSelector(newConfig.services);
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
  renderProjectCards(_config.projects);
  renderServiceCards(_config.services);
  populateLogSelector(_config.services);

  // 2. Load stats
  const statsOk = await fetchAndRenderStats();
  if (!statsOk) renderStatsError();

  // 3. Load service/project statuses (already checked by the server)
  const svcOk = await fetchAndRenderServices();
  if (!svcOk) renderServicesError();

  // 4. Load logs for the first service
  refreshLog();
})();

