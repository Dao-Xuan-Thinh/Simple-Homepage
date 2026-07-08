# Simple Homepage Dashboard

A personal dashboard hosted on GitHub Pages that provides centralized access to self-hosted services, live system stats from a Mac mini, and real-time Docker logs. No code changes needed — manage everything through a web-based settings modal.

**Live Demo**: https://dao-xuan-thinh.github.io/Simple-Homepage/

---

## Features

### 🔗 Project Links
- Quick access to all your self-hosted projects (GitHub repos, documentation, media servers, etc.)
- Auto health-checks via configurable URLs
- Public and private project visibility
- Status badges: **Online** 🟢 / **Offline** 🔴 / **Warning** 🟡

### 📡 Service Status Dashboard
- Real-time CPU, RAM, Disk, Swap, and Network stats from your Mac mini
- Thermal pressure level (Nominal / Moderate / Heavy) — since Apple Silicon M4 doesn't expose CPU temperature
- Service uptime and performance metrics
- Individual service health checks via TCP port or HTTP URL

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

Changes are saved to the Mac mini's `config.json` and persist across restarts.

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
```

### 🔄 Data Flow

1. **Initial Load**: Browser fetches `/api/config` → services and projects rendered
2. **Status Updates**: Background thread (every 30s) checks service health via TCP/HTTP
3. **Live Stats**: Dashboard polls `/api/stats` every ~5 seconds → CPU, RAM, disk, temp updated
4. **Logs**: Log viewer polls `/api/logs` every 10 seconds → real-time Docker logs displayed
5. **Config Changes**: User saves settings → `PUT /api/config` → server writes `config.json` → services re-rendered

---

## Quick Start

### Prerequisites
- **Mac mini** running macOS with Docker installed
- **Tailscale** installed (for remote access)
- **Python 3.7+** with `psutil` and `docker` packages
- **Git** (optional, for cloning this repo)

### 1. Set Up Mac Mini API Server

#### Install Dependencies
```bash
pip install psutil docker
```

#### Download and Run Server
```bash
# Navigate to your projects directory
cd ~/Projects

# Download the server
curl -o server.py https://raw.githubusercontent.com/Dao-Xuan-Thinh/Simple-Homepage/main/mac-api/server.py
curl -o config.json https://raw.githubusercontent.com/Dao-Xuan-Thinh/Simple-Homepage/main/mac-api/config.json

# Create sudoers rule for powermetrics (thermal pressure monitoring)
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
  "temp": null,
  "thermal_pressure": "Moderate",
  "cpu_freq_ghz": 3.2
}
```

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

### Project Structure
```
├── index.html              # Dashboard UI
├── app.js                  # Frontend logic (settings, logs, stats)
├── style.css               # Styling & themes
├── pages/
│   └── changelog/
│       └── changelog.html  # Feature history
├── mac-api/
│   ├── server.py           # Python API server
│   └── config.json         # Config template
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

**Last Updated**: 2026-07-08  
**Current Version**: Batch 2 (Multi-container logs + Settings modal)
