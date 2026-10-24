# Simple Homepage Dashboard

A personal dashboard hosted on GitHub Pages that provides centralized access to self-hosted services, live system stats from a Mac mini, real-time Docker logs, Tailscale device status, and a self-updating list of downloadable GitHub projects. No code changes needed — manage services through a web-based settings modal, and downloads sync themselves straight from GitHub. Installable as a PWA on your phone.

**Live Demo**: https://dao-xuan-thinh.github.io/Simple-Homepage/

---

## Features

### ⇄ Tailscale devices
- Shows which of your tailnet devices are **online / offline**, with OS, Tailscale IP, and last-seen
- Reads `tailscale status --json` server-side (no sudo); `funnel-ingress-node` noise is filtered out
- "This machine" is flagged; polled every ~20 s

### ▣ Containers
- Per-container **CPU / MEM** from `docker stats`, with mini bars; polled every ~15 s

### ⚠ Alerts / overload log
- A **persistent record of when a stat went dangerously high** — so you can see when the server was overloaded even though you weren't watching
- Detection runs **entirely server-side, 24/7** (a background loop, not the browser), so nothing is missed when no tab is open
- Watches CPU, RAM, swap, CPU temperature, load average, and disk; each breach becomes an **episode** with a start time, duration, and peak value
- Swap is measured in **absolute GB**, not as a percentage of the swap file — macOS resizes that file on demand, so the percentage is a sawtooth that says nothing about memory pressure
- Edge-triggered with hysteresis and a 2-sample gate, so brief spikes don't flood the log; `warning` escalates to `critical` past the higher threshold
- Also logs **service outages** — the 30s health probe feeds the same episode machinery, so "Immich was down 14:02 → 14:19" lands in the same list as a CPU spike
- Persisted to `alerts.json` (git-ignored), kept across restarts (last 200). The badge **flashes** when a new alert lands while you're viewing

### ▭ Laptop tab
- The Status section has one tab per machine: **Mac mini** and **Laptop**, each with a dot showing whether it's up. The chosen tab is remembered per browser
- The laptop (the G14) runs an agent on each OS it boots, [`laptop-agent/agent.py`](laptop-agent/README.md) on Windows and [`laptop-agent/macos/agent.c`](laptop-agent/macos/README.md) on macOS. Each pushes CPU, RAM, battery, battery drain, temperature (Windows only), network and storage to the Mac's API every 1–2 minutes
- **Which OS**: both OSes share one history, labelled per sample. The badge names the OS the latest stats came from ("macOS · Live"). Expanded charts tint the background by OS, with a colour key underneath, and the hover readout names it. Lines break at an OS switch. Top Apps counts each app per OS and tags rows with their OS when a window mixes both
- **Top apps**: which apps used the most CPU and RAM right now, or averaged over the last hour, 24 hours or 7 days (hourly totals, kept 7 days)
- Same graphs and click-to-expand history (30m–7d) as the Mac's cards. Graphs leave a gap where the laptop slept instead of drawing a line across it
- While the laptop is asleep or away, its cards keep the last values, dimmed, with "Offline · seen 3h ago"

### ✨ Homelab console UI
- Per-metric accent colors, card depth, monospace tabular numbers, soft glow on live values
- **Five selectable skins** — pick from the header (`◐`) or the command palette; each has light and dark. These are whole designs, not palette swaps: layout, framing, typography and the *form the graphs take* all change
  - **Bento** — asymmetric tile wall, hero panels for CPU/RAM, borderless and rounded. Area charts
  - **Ops** — monitoring rig; every card is a titled panel over a ruled plot area. Column charts
  - **CRT** — amber phosphor terminal with scanlines; graphs are drawn in block characters, not vectors
  - **Paper** — editorial print; serif, hairline rules, no boxes. Bare stroke charts, no fills
  - **Classic** — the original, kept for comparison
- **30-minute sparklines** on CPU / RAM / swap / load / temperature / power / disk — backfilled from the server's history, so the window is real the moment the page opens
- **Mirrored network graph** — download above the baseline, upload below, on a shared scale
- **Click any stat card** for the full graph over 30m / 6h / 24h, with peak/avg/min, live detail, and the alerts recorded in that window
- **Disk fill projection** — a least-squares fit over 7 days of history gives percent-per-day drift and an estimate of when the volume hits 95%
- **Command palette** — press <kbd>/</kbd> or <kbd>⌘K</kbd> to fuzzy-jump to any service, download, or device
- Header **clock + greeting**; light/dark as before
- **Installable PWA** — add to your phone home screen, offline app shell, real favicon

### 🔗 Project Links
- Quick access to all your self-hosted projects (GitHub repos, documentation, media servers, etc.)
- Auto health-checks via configurable URLs
- Public and private project visibility
- Status badges: **Online** 🟢 / **Offline** 🔴 / **Warning** 🟡

### ↓ Downloads (auto-synced from GitHub)
- A self-updating grid of your downloadable GitHub projects — **no config editing, ever**
- Fetched client-side from the GitHub API; push a new repo and it appears on its own
- Each card shows language, star count, last-updated date, plus **Code** / **ZIP** / **Releases** links
- Forks and website repos (already shown as Project Links) are filtered out via a small ignore-list in `app.js`
- Response cached in `localStorage` (3 h) with a graceful fallback when GitHub is rate-limited or unreachable
- Header shows how old the cached list is, with a **↻** button to force a fresh fetch right after pushing a repo

### 📡 Service Status Dashboard
- Real-time CPU, RAM, Disk, Swap, and Network stats from your Mac mini
- Disk usage reads the real data volume (`/System/Volumes/Data`), not the sealed macOS system snapshot
- **Storage Volumes**: per-volume breakdown (internal drive + any external drives under `/Volumes`), each with a usage bar; APFS system plumbing is filtered out
- **Live CPU / GPU temperature** via [macmon](https://github.com/vladkens/macmon) — reads Apple Silicon sensors through the private IOReport API (no sudo), so the M4 finally reports a real °C
- **Power / Energy**: real measured system power plus a cumulative kWh total that persists across restarts (see below)
- **Memory** figure matches Activity Monitor (from macmon), with the % and GB always consistent
- **Load average** (1/5/15-min + core count), **Network total** (GB since boot), and **Docker** (running / total containers) cards
- Service uptime and performance metrics
- Individual service health checks via TCP port or HTTP URL

#### Temperature & power (macmon)
Apple Silicon M4 exposes no CPU die temperature via `powermetrics` or psutil. [`macmon`](https://github.com/vladkens/macmon) reads the SoC sensors through the private IOReport API — **without sudo** — so the server shells out to `macmon pipe` for live CPU/GPU temperature, an Activity-Monitor-accurate memory figure, and real measured system power. The Power/Energy card integrates macmon's `sys_power` into a running Wh total, sampled every 60 s and persisted in `energy.json` (git-ignored) so it survives restarts. Downtime isn't counted — the gap is capped so sleep/off periods don't spike the total.

> `sys_power` is the SoC/system power reported by the PMU — measured, and far more realistic than the old estimate, but still **not** a PSU wall-plug reading (it excludes SSD, USB, fans, and PSU losses). If macmon is missing, the server degrades gracefully: thermal-pressure level instead of °C, psutil memory, and a flat `IDLE_BASE_W` fallback for energy.

### 📋 Multi-Container Log Viewer
- View logs from any Docker container in real-time
- Per-service container selector (e.g., Immich shows Server, Database, ML, Redis separately)
- Last 50 log lines with timestamps and severity levels
- Auto-refresh every 10 seconds
- Fully configurable from the browser

### ⚙️ Dynamic Settings Modal
Three tabs for web-based configuration (no code edits needed):
- **🔗 Projects** — add/edit/delete projects with icons, descriptions, and URLs
- **📡 Services** — manage services, ports, and Docker containers
- **📋 Logs** — configure which Docker containers appear in the log viewer

Changes are saved to the Mac mini's `config.json` and persist across restarts. Tick **Remember** next
to the write-token field to store it in this browser so you don't retype it on every edit (opt-in;
untick to forget it immediately).

### 🌓 Theme Support
- Light and Dark modes with smooth transitions
- Theme preference saved in browser localStorage
- Color-coded status badges and charts

### 🔒 Security
- API protected by random read token (included in config)
- Separate write token from `HOMEPAGE_WRITE_TOKEN` env var (never committed to Git)
- 401 Unauthorized responses for invalid tokens
- CORS restricted to whitelisted origins

---

## Architecture

### 📦 Components

```
┌─ GitHub Pages (Homepage) ──────────────────────────────┐
│  index.html          (Dashboard UI)                    │
│  app.js              (Client-side logic)               │
│  style.css           (Styling & theming)               │
│                                                        │
│  Talks to Mac mini API via Tailscale Funnel →          │
└────────────────────────────────────────────────────────┘

┌─ Mac mini (API Server) ────────────────────────────────┐
│  server.py           (Python HTTP API)                 │
│  config.json         (Projects & services config)      │
│                                                        │
│  Exposed publicly via Tailscale Funnel TLS             │
│  https://my-biggest-beefsteak.tail437237.ts.net:8443/  │
└────────────────────────────────────────────────────────┘

┌─ Laptop (Windows) ─────────────────────────────────────┐
│  laptop-agent/agent.py  (pushes samples + top apps)    │
│  → POST /api/laptop/push on the Mac's API              │
└────────────────────────────────────────────────────────┘
```

### 🔄 Data Flow

1. **Initial Load**: Browser fetches `/api/config` → services and projects rendered
2. **Status Updates**: Background thread (every 30s) checks service health via TCP/HTTP
3. **Live Stats**: Dashboard polls `/api/stats` every ~5 seconds → CPU, RAM, disk, temp updated
4. **Logs**: Log viewer polls `/api/logs` every 10 seconds → real-time Docker logs displayed
5. **Alerts**: A server background loop samples metrics every ~20s and records overload episodes to `alerts.json`; the dashboard polls `/api/alerts` every ~30s to show the history
6. **History**: The same loop records every sample into a fine in-memory ring (~1h) and 5-minute min/avg/max buckets persisted to `history.json` (7 days). The dashboard fetches `/api/history` on load for the 30-minute sparklines and on demand for the expanded 6h/24h/7d views
7. **Laptop**: The agent on the laptop samples every 30 s (60 s on battery) and pushes a batch every 1–2 minutes; the server keeps the same history tiers for it plus hourly per-app totals. The dashboard polls `/api/laptop` every 30 s
8. **Config Changes**: User saves settings → `PUT /api/config` → server writes `config.json` → services re-rendered

---

## Quick Start

### Prerequisites
- **Mac mini** running macOS with Docker installed
- **Tailscale** installed (for remote access)
- **Python 3.7+** with `psutil` and `docker` packages
- **[macmon](https://github.com/vladkens/macmon)** (`brew install macmon`) — for live CPU/GPU temperature, accurate memory, and measured power on Apple Silicon (no sudo). Optional; the server falls back gracefully without it.
- **Git** (optional, for cloning this repo)

### 1. Set Up Mac Mini API Server

#### Install Dependencies
```bash
pip install psutil docker
brew install macmon   # live temperature / memory / power (Apple Silicon, no sudo)
```

#### Download and Run Server
```bash
# Navigate to your projects directory
cd ~/Projects

# Download the server
curl -o server.py https://raw.githubusercontent.com/Dao-Xuan-Thinh/Simple-Homepage/main/mac-api/server.py
curl -o config.json https://raw.githubusercontent.com/Dao-Xuan-Thinh/Simple-Homepage/main/mac-api/config.json

# Optional: sudoers rule for the powermetrics fallback (only used if macmon is absent)
sudo sh -c 'echo "YOUR_USERNAME ALL=(ALL) NOPASSWD: /usr/bin/powermetrics" > /etc/sudoers.d/powermetrics'

# Start the server (runs on port 9000)
python3 server.py
```

The server will output:
```
Mac Mini Stats API running on port 9000 (plain HTTP - TLS handled by Tailscale Funnel)
  API token: 3df484b5a0a1fd711ba4438c1c6d8b79cc66444375e0da80
  Local:    http://127.0.0.1:9000/api/stats?token=3df484b5a0a1fd711ba4438c1c6d8b79cc66444375e0da80
  Public URL (via Tailscale Funnel on :8443):
  https://my-biggest-beefsteak.tail437237.ts.net:8443/api/stats?token=3df484b5a0a1fd711ba4438c1c6d8b79cc66444375e0da80
```

#### Set Up Tailscale Funnel
```bash
# Enable Tailscale Funnel on port 8443 → 9000
sudo tailscale funnel 8443 http://127.0.0.1:9000
```

### 2. Configure the Dashboard

Edit `app.js` and update these variables:
```javascript
const API_BASE = 'https://your-tailscale-hostname.ts.net:8443';
const API_TOKEN = 'your-api-token-from-server-output';
```

The default `WRITE_TOKEN` is read from the server's `HOMEPAGE_WRITE_TOKEN` env var:
```bash
export HOMEPAGE_WRITE_TOKEN="your-secret-write-token"
python3 server.py
```

### 3. Access the Dashboard

1. Open https://dao-xuan-thinh.github.io/Simple-Homepage/ (or your fork)
2. Stats and logs should appear within a few seconds
3. Click **⚙️ Settings** to manage projects and services

---

## Configuration

### config.json Schema

```json
{
  "projects": [
    {
      "id": "project-id",
      "name": "Project Name",
      "icon": "🔗",
      "desc": "Description",
      "url": "https://example.com",
      "check_url": "https://example.com/health",
      "visibility": "public"
    }
  ],
  "services": [
    {
      "id": "immich",
      "name": "Immich",
      "detail": ":2283",
      "port": 2283,
      "docker": "immich_server",
      "containers": [
        {"label": "Server", "docker": "immich_server"},
        {"label": "Database", "docker": "immich-database"},
        {"label": "ML", "docker": "immich_machine_learning"},
        {"label": "Redis", "docker": "redis"}
      ],
      "log_file": null,
      "check_url": null
    }
  ]
}
```

**Fields:**
- `id`: Unique identifier (URL-safe, no spaces)
- `name`: Display name in the dashboard
- `icon`: Emoji icon (projects only)
- `detail`: Subtitle (e.g., port number)
- `url`: Project URL (projects only)
- `check_url`: Health check URL (optional — defaults to `url` for projects)
- `port`: TCP port for health checks (services only)
- `docker`: Primary Docker container name (logs will use this by default)
- `containers`: Array of additional containers to expose in the log viewer
- `visibility`: "public" or "private" (projects only — private hidden on dashboard)

### Downloads Section (GitHub auto-sync)

The Downloads grid is driven entirely client-side — no `config.json`, no write token. Configure it via
constants near the top of `app.js`:

```javascript
const GITHUB_USER = 'Dao-Xuan-Thinh';          // whose public repos to list
const DOWNLOAD_IGNORE = new Set([              // repos to hide (websites, this dashboard, …)
  'Simple-Homepage', 'Study-Portal', 'Simple-StandBy', 'Prototype_Web',
]);
```

Forks are dropped automatically. Everything else appears on its own — make a new tool repo and it shows
up on the next load. Results are cached in `localStorage` for 3 hours to stay under GitHub's
unauthenticated rate limit (60 requests/hour per IP).

### Environment Variables

**Mac Mini Server:**
- `HOMEPAGE_WRITE_TOKEN`: Secret token required for config mutations (required for production)
- `PYTHONUNBUFFERED=1`: Recommended for Docker containers running the server

---

## API Reference

### Base URL
```
https://your-tailscale-hostname.ts.net:8443
```

All requests require `?token=<API_TOKEN>` query parameter (read token).

### Endpoints

#### GET /api/stats
System statistics from the Mac mini.

**Response:**
```json
{
  "cpu": 35,
  "ram": 62,
  "ram_used_gb": 8.2,
  "ram_total_gb": 16,
  "swap": 10,
  "swap_used_gb": 0.5,
  "disk": 75,
  "disk_used_gb": 450,
  "disk_total_gb": 600,
  "disk_read_mbs": 15.2,
  "disk_write_mbs": 8.5,
  "uptime": 345600,
  "net_tx": 512,
  "net_rx": 256,
  "temp": 43.2,
  "gpu_temp": 37.6,
  "thermal_pressure": null,
  "cpu_freq_ghz": 3.2,
  "load_1": 2.75,
  "load_5": 3.46,
  "load_15": 3.17,
  "cpu_cores": 10,
  "net_total_up_gb": 1.05,
  "net_total_down_gb": 3.14,
  "docker_running": 7,
  "docker_total": 14,
  "volumes": [
    { "name": "Macintosh HD", "mount": "/System/Volumes/Data", "used_gb": 168.0, "total_gb": 228.3, "percent": 83.0, "internal": true },
    { "name": "Backup", "mount": "/Volumes/Backup", "used_gb": 245.2, "total_gb": 952.2, "percent": 25.8, "internal": false }
  ],
  "power_w": 8.74,
  "energy_wh": 578.9,
  "energy_since": 1783603292
}
```

`temp` / `gpu_temp` are live °C from macmon (Apple Silicon); when macmon is unavailable, `temp` may be `null` and `thermal_pressure` carries the Nominal/Moderate/Heavy level instead. `power_w` is macmon's measured `sys_power`; `energy_wh` is the cumulative total since `energy_since` (epoch). `docker_*` are `null` when Docker isn't running. `volumes` lists the internal data volume plus external drives mounted under `/Volumes` (system/recovery volumes are filtered out).

---

#### GET /api/config
Fetch the current configuration.

**Response:** Returns the entire `config.json` object with projects and services.

---

#### GET /api/services
Service status overview with health checks.

**Response:**
```json
{
  "services": [
    {
      "id": "immich",
      "name": "Immich",
      "status": "online",
      "last_check": "2026-07-08T17:10:15.234Z"
    }
  ]
}
```

**Status Values:** `online`, `offline`, `warning`

---

#### GET /api/logs
Docker container or log file contents.

**Query Parameters:**
- `service`: Service ID (required)
- `lines`: Number of lines to return (default: 50, max: 500)
- `container`: Docker container name (optional — overrides default)

**Example:**
```
GET /api/logs?service=immich&lines=50&container=immich-database&token=...
```

**Response:**
```json
{
  "service": "immich",
  "lines": [
    {
      "timestamp": "2026-07-08T17:10:15.234Z",
      "level": "INFO",
      "msg": "Starting Immich server...",
      "raw": "[2026-07-08 17:10:15] INFO: Starting Immich server..."
    }
  ]
}
```

---

#### GET /api/alerts
The overload event log — episodes where a stat crossed a "dangerous" threshold, detected server-side 24/7.

**Query Parameters:**
- `limit`: Max episodes to return, newest first (default 100, max 200)

**Response:**
```json
{
  "events": [
    { "id": 178400268400, "metric": "cpu", "label": "CPU", "unit": "%", "level": "critical",
      "threshold": 80, "peak": 98.4,
      "started_at": 1784002600, "updated_at": 1784003080, "ended_at": 1784003100 }
  ],
  "rules": { "cpu": { "label": "CPU", "unit": "%", "warn": 80, "crit": 95 } },
  "ts": 1784003200
}
```

`ended_at` is `null` while an episode is ongoing. See [mac-api/API.md](mac-api/API.md#get-apialerts) for the full field list and detection semantics.

---

#### GET /api/laptop, /api/laptop/apps
Laptop status (latest sample, info, top apps, 30-minute series) and per-app CPU/RAM averages over a
window. Add `host=laptop` to `/api/history` for the laptop's graphs. See
[mac-api/API.md](mac-api/API.md#get-apilaptop).

#### GET /api/history
Metric history from the same 24/7 loop that feeds `/api/alerts`, in two tiers: **fine** (every ~20s
sample, ~1h, in memory) and **bucket** (5-minute min/avg/max, 7 days, persisted to `history.json`).
Windows of 60 minutes or less return `fine`; longer windows return `bucket`.

**Query Parameters:**
- `minutes`: How far back to return samples (default 30, max 10080 = 7 days)
- `step`: Bucket tier only — merge 5-minute buckets into groups of this many seconds (the 7-day view uses 1800)

**Response:**
```json
{
  "points": [
    { "t": 1784966650, "cpu": 10.7, "ram": 75.4, "swap": 50.2, "temp": 51.0,
      "load": 3.05, "disk": 85.1, "power": 13.93, "net_rx": 22.6, "net_tx": 67.8 }
  ],
  "res": "fine",
  "interval": 20,
  "minutes": 30,
  "ts": 1784966660
}
```

Oldest first. **Branch on `res`** — `bucket` points hold `{min, avg, max}` objects rather than scalars.
Any metric key may be absent if that sensor was unavailable for the sample.

---

#### PUT /api/config
Update configuration (requires `WRITE_TOKEN`).

**Query Parameters:**
- `token`: Write token from `HOMEPAGE_WRITE_TOKEN` env var (required)

**Request Body:**
```json
{
  "projects": [...],
  "services": [...]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Config saved successfully"
}
```

**Errors:**
- `401`: Invalid or missing write token
- `400`: Invalid JSON or validation error

---

## Troubleshooting

### API returns 401 Unauthorized
- **Check**: Token is correct in `app.js` and `server.py`
- **Check**: Token is passed as `?token=...` query param
- **For writes**: Ensure `HOMEPAGE_WRITE_TOKEN` env var is set before running server

### No stats displayed
- **Check**: Mac mini API is running (`python3 server.py`)
- **Check**: Tailscale Funnel is active (`sudo tailscale funnel`)
- **Check**: URL in `app.js` matches your actual Tailscale hostname
- **Check**: Network connectivity — can you ping the Mac mini?

### Logs show "Can't connect to API"
- Same checks as above
- **Check**: Docker is running (`docker ps`)
- **Check**: Container name in `config.json` is exact (case-sensitive)

### Thermal pressure shows "Nominal" but you expected higher
- **Apple Silicon M4 limitation**: CPU temperature is not exposed by any macOS API
- Thermal pressure (Nominal / Moderate / Heavy) is the only available signal
- "Heavy" = throttling may occur
- If you see "Moderate" or "Heavy" under load, your Mac mini is still healthy

### Can't edit config in settings modal
- **Check**: Write token is entered in the "Write token" field
- **Check**: Write token matches `HOMEPAGE_WRITE_TOKEN` on the Mac mini
- **Check**: Server is running and API is reachable

---

## Deployment

### Fork This Repository
1. Go to https://github.com/Dao-Xuan-Thinh/Simple-Homepage
2. Click **Fork**
3. Update `app.js` with your Mac mini's Tailscale hostname and tokens
4. GitHub Pages will auto-deploy to `https://YOUR_USERNAME.github.io/Simple-Homepage/`

### Use with Your Own Domain
Add a CNAME file pointing to your domain, then update DNS records to GitHub Pages.

---

## Development

### Local Testing
```bash
# Serve locally
python3 -m http.server 8000

# Open in browser
open http://localhost:8000
```

### Keeping the config in sync
The running server reads a **live** `config.json` that lives outside this repo (the settings modal
writes to it). To pull that live copy back into the committed template so they don't drift:
```bash
cd mac-api
./sync-config.sh                 # or: ./sync-config.sh /path/to/live/config.json
git diff -- mac-api/config.json  # review, then commit
```
The script validates the JSON before copying and no-ops if they already match.

### Project Structure
```
├── index.html              # Dashboard UI
├── app.js                  # Frontend logic (settings, logs, stats)
├── style.css               # Styling & themes
├── pages/
│   └── changelog/
│       └── changelog.html  # Feature history
├── laptop-agent/
│   ├── agent.py            # Runs on the Windows laptop, pushes stats to the API
│   └── README.md           # Install / update / remove
├── mac-api/
│   ├── server.py           # Python API server
│   ├── laptop.py           # Laptop history + per-app store (imported by server.py)
│   ├── config.json         # Config template (keep in sync with the live copy)
│   └── sync-config.sh      # Copy the live config into this repo copy
└── README.md               # This file
```

### Code Style
- **JavaScript**: Modern ES6+, no external dependencies
- **Python**: PEP 8 style, `psutil` and `docker` for system access
- **CSS**: Custom properties (CSS variables) for theming

---

## Cool Features to Add

- 🔔 Offline alert badges on service cards
- 🔍 Real-time log search/filter
- 📌 Pin favourite services to top
- 📱 PWA manifest for "Add to Home Screen"
- ⌨️ Keyboard shortcuts (R = refresh logs, G = settings)
- 🕐 "Went offline 3 min ago" last-seen timestamps
- 📊 Historical stats charts (24h, 7d, 30d)
- 🔔 Browser push notifications for service downtime
- 🏠 Custom dashboard themes and card layouts

---

## License

MIT — Feel free to fork, modify, and use for personal projects.

---

## Support

- **Issues**: GitHub Issues in this repository
- **Questions**: Check the Changelog for what's been done
- **Mac Mini Setup Help**: See the "Quick Start" section above

---

**Last Updated**: 2026-07-25  
**Current Version**: Batch 8 (skin prototypes, expandable cards, 7-day history, downtime log)
