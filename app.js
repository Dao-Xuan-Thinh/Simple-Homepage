/* ── Theme Toggle ───────────────────────────────────────────────── */
const body       = document.body;
const themeBtn   = document.getElementById('theme-toggle');
const themeIcon  = document.getElementById('theme-icon');

function applyTheme(dark) {
  body.classList.toggle('dark', dark);
  themeIcon.textContent = dark ? '☀️' : '🌙';
}

// Restore saved preference (default: dark)
const saved = localStorage.getItem('theme');
const isDark = saved !== null ? saved === 'dark' : true;
applyTheme(isDark);

themeBtn.addEventListener('click', () => {
  const nowDark = !body.classList.contains('dark');
  applyTheme(nowDark);
  localStorage.setItem('theme', nowDark ? 'dark' : 'light');
});

/* ── Helpers ────────────────────────────────────────────────────── */
function rand(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function setBar(barId, pct) {
  const bar = document.getElementById(barId);
  if (!bar) return;
  bar.style.width = pct + '%';
  bar.classList.toggle('hot',      pct >= 70 && pct < 85);
  bar.classList.toggle('critical', pct >= 85);
}

function now() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/* ── Mac Mini Mock Stats ────────────────────────────────────────── */
function updateStats() {
  const cpu  = rand(8, 72);
  const ram  = rand(40, 82);
  const disk = rand(55, 78);
  const temp = rand(38, 61);
  const netTx = rand(10, 450);
  const netRx = rand(20, 900);

  document.getElementById('stat-cpu').textContent  = cpu + '%';
  document.getElementById('stat-ram').textContent  = ram + '%';
  document.getElementById('stat-disk').textContent = disk + '%';
  document.getElementById('stat-temp').textContent = temp + '°C';
  document.getElementById('stat-net').textContent  = `↑${netTx} ↓${netRx} KB/s`;

  setBar('bar-cpu',  cpu);
  setBar('bar-ram',  ram);
  setBar('bar-disk', disk);

  updateUptime();
}

// Simulate a plausible uptime that ticks
let uptimeSeconds = rand(3600 * 24 * 2, 3600 * 24 * 14); // 2–14 days base

function updateUptime() {
  uptimeSeconds++;
  const d = Math.floor(uptimeSeconds / 86400);
  const h = Math.floor((uptimeSeconds % 86400) / 3600);
  const m = Math.floor((uptimeSeconds % 3600)  / 60);
  const s = uptimeSeconds % 60;
  document.getElementById('stat-uptime').textContent =
    `${d}d ${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

// Update stats on load, then every 5 seconds
updateStats();
setInterval(updateStats,  5000);
setInterval(updateUptime, 1000);

/* ── Server Status Mock ─────────────────────────────────────────── */
const serverIds = ['immich', 'openclaw', 'projects', 'proto', 'tailscale'];

function updateLastChecked() {
  const t = now();
  serverIds.forEach(id => {
    const el = document.getElementById(`lc-${id}`);
    if (el) el.textContent = `Checked ${t}`;
  });
}

updateLastChecked();
setInterval(updateLastChecked, 30000);

/* ── Log Data ───────────────────────────────────────────────────── */
const LOG_TEMPLATES = {
  immich: [
    ['INFO',  'Server started on port 2283'],
    ['INFO',  'Connected to PostgreSQL database'],
    ['INFO',  'Asset upload from 192.168.1.5 — 14.2 MB'],
    ['INFO',  'Thumbnail generation completed — 34 assets'],
    ['DEBUG', 'Machine learning pipeline initialized'],
    ['INFO',  'Face detection job queued — 8 items'],
    ['INFO',  'Smart album "Last Month" updated — 127 photos'],
    ['WARN',  'Storage usage at 74% — consider cleanup'],
    ['INFO',  'User session started from 100.64.x.x'],
    ['DEBUG', 'EXIF extraction completed for batch #42'],
    ['INFO',  'Library scan finished — 0 new assets'],
    ['INFO',  'Backup sync to external drive complete'],
    ['DEBUG', 'Redis cache hit ratio: 91.3%'],
    ['INFO',  'Cleanup job removed 12 temporary files'],
    ['WARN',  'Slow query detected: 340ms on asset lookup'],
  ],
  openclaw: [
    ['INFO',  'Dashboard loaded — 5 services registered'],
    ['INFO',  'Health check: all services responding'],
    ['DEBUG', 'Fetched Docker stats for 3 containers'],
    ['INFO',  'New deployment triggered: immich v1.101.0'],
    ['INFO',  'Deployment complete in 42s'],
    ['WARN',  'Container "proto-app" restarted — exit code 1'],
    ['INFO',  'CPU alert threshold set to 80%'],
    ['DEBUG', 'Webhook received from GitHub Actions'],
    ['INFO',  'Log archive rotation completed'],
    ['ERROR', 'Failed to pull image: timeout after 30s'],
    ['INFO',  'Retry succeeded on second attempt'],
    ['DEBUG', 'Port scan: all bound ports healthy'],
  ],
  projects: [
    ['INFO',  'Nginx reloaded — config applied'],
    ['INFO',  'TLS certificate valid until 2025-12-01'],
    ['INFO',  'GET / 200 12ms from 100.64.x.x'],
    ['INFO',  'GET /api/health 200 4ms'],
    ['DEBUG', 'Static asset cache warm — 98% hit'],
    ['INFO',  'Deploy hook received — pulling latest main'],
    ['INFO',  'Build completed in 18s'],
    ['INFO',  'Site restarted successfully'],
    ['WARN',  'Rate limit exceeded for /api/submit — throttled'],
    ['INFO',  'Scheduled backup completed'],
  ],
  proto: [
    ['INFO',  'Dev server started on port 4000'],
    ['WARN',  'Experimental feature flag enabled: ai-mode'],
    ['DEBUG', 'Hot reload triggered — 3 modules updated'],
    ['ERROR', 'Unhandled exception in /api/test — NullRef'],
    ['INFO',  'Exception captured and logged'],
    ['WARN',  'Memory usage spike: 680 MB'],
    ['DEBUG', 'WebSocket connection opened from localhost'],
    ['INFO',  'Test suite ran — 47 passed, 2 failed'],
    ['WARN',  'Deprecated API usage detected in utils.js'],
    ['INFO',  'Auto-restarted after crash'],
  ],
};

/* ── Log Viewer ─────────────────────────────────────────────────── */
const logViewer  = document.getElementById('log-viewer');
const logSelect  = document.getElementById('log-server');
const logRefresh = document.getElementById('log-refresh');
const logFollow  = document.getElementById('log-follow');

function randomPastTime(maxSecondsAgo = 600) {
  const d = new Date(Date.now() - rand(0, maxSecondsAgo) * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function buildLog(server) {
  const templates = LOG_TEMPLATES[server] || LOG_TEMPLATES.immich;
  // Pick a random subset and shuffle to simulate realistic log ordering
  const count = rand(10, templates.length);
  const picked = [...templates].sort(() => Math.random() - 0.5).slice(0, count);
  // Sort by a fake timestamp
  const entries = picked.map(([level, msg]) => ({
    time: randomPastTime(),
    level,
    msg,
  }));
  return entries;
}

function renderLog(server) {
  const entries = buildLog(server);
  logViewer.innerHTML = entries.map(({ time, level, msg }) => `
    <div class="log-line">
      <span class="log-time">${time}</span>
      <span class="log-level ${level}">${level}</span>
      <span class="log-msg">${msg}</span>
    </div>
  `).join('');

  if (logFollow.checked) {
    logViewer.scrollTop = logViewer.scrollHeight;
  }
}

// Initial render
renderLog(logSelect.value);

// Server switch
logSelect.addEventListener('change', () => renderLog(logSelect.value));

// Refresh button
logRefresh.addEventListener('click', () => renderLog(logSelect.value));

// Auto-refresh every 10 s (simulates streaming)
setInterval(() => {
  renderLog(logSelect.value);
}, 10000);
