# API Documentation

Complete reference for the Mac Mini Stats API.

**Base URL**: `https://your-tailscale-hostname.ts.net:8443`  
**Authentication**: Query parameter `?token=<API_TOKEN>` on all requests  
**Server**: Python 3.7+ with `psutil` and `docker` libraries

---

## Table of Contents

1. [Authentication](#authentication)
2. [Rate Limits](#rate-limits)
3. [Error Handling](#error-handling)
4. [Endpoints](#endpoints)
   - [GET /api/stats](#get-apistats)
   - [GET /api/config](#get-apiconfig)
   - [PUT /api/config](#put-apiconfig)
   - [GET /api/services](#get-apiservices)
   - [GET /api/tailscale](#get-apitailscale)
   - [GET /api/docker](#get-apidocker)
   - [GET /api/alerts](#get-apialerts)
   - [GET /api/logs](#get-apilogs)
5. [Response Formats](#response-formats)
6. [Examples](#examples)

---

## Authentication

All endpoints require a valid API token passed as a query parameter:

```
GET /api/stats?token=3df484b5a0a1fd711ba4438c1c6d8b79cc66444375e0da80
```

### Token Types

| Token | Purpose | Source | Required in Code |
|-------|---------|--------|-------------------|
| **Read Token** | Query stats, config, logs | Generated on server start | `app.js` (public) |
| **Write Token** | Modify config via PUT | `HOMEPAGE_WRITE_TOKEN` env var | User enters in settings modal |

### Missing or Invalid Token

```
HTTP 401 Unauthorized

{
  "error": "Invalid or missing token"
}
```

---

## Rate Limits

- **Stats polling**: 5-10 second intervals (set in `app.js`)
- **Status checks**: Every 30 seconds (background thread on server)
- **Log refresh**: Every 10 seconds
- **Config save**: No limit, but `PUT /api/config` triggers a one-shot health check

*No hard rate limiting — use reasonable poll intervals to avoid overwhelming the server.*

---

## Error Handling

All errors return JSON with `error` key and appropriate HTTP status:

### HTTP Status Codes

| Status | Meaning |
|--------|---------|
| `200` | Success |
| `400` | Bad Request (invalid parameters, missing required fields) |
| `401` | Unauthorized (invalid/missing token) |
| `404` | Not Found (unknown service ID) |
| `500` | Server Error (exception during processing) |

### Example Error Response

```json
{
  "error": "Invalid service: unknown_service"
}
```

---

## Endpoints

### GET /api/stats

Fetch current system statistics from the Mac Mini.

**URL**: `/api/stats?token=<TOKEN>`

**Query Parameters**: None (token required)

**Response (200 OK):**

```json
{
  "cpu": 35,
  "ram": 62,
  "ram_used_gb": 8.2,
  "ram_total_gb": 16,
  "swap": 10,
  "swap_used_gb": 0.5,
  "swap_total_gb": 4,
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
  "power_w": 6.13,
  "energy_wh": 142.6,
  "energy_since": 1783603292
}
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `cpu` | int | CPU usage percentage (0–100) |
| `ram` | int | RAM usage percentage (0–100) |
| `ram_used_gb` | float | RAM used in gigabytes |
| `ram_total_gb` | float | Total RAM in gigabytes |
| `swap` | int | Swap usage percentage (0–100), or `null` if unavailable |
| `swap_used_gb` | float | Swap used in gigabytes |
| `swap_total_gb` | float | Total swap in gigabytes |
| `disk` | int | Disk usage percentage for the data volume (`/System/Volumes/Data` on macOS, 0–100) |
| `disk_used_gb` | float | Disk used in gigabytes |
| `disk_total_gb` | float | Total disk in gigabytes |
| `disk_read_mbs` | float | Disk read speed in MB/s |
| `disk_write_mbs` | float | Disk write speed in MB/s |
| `uptime` | int | System uptime in seconds |
| `net_tx` | int | Network transmit rate in KB/s |
| `net_rx` | int | Network receive rate in KB/s |
| `temp` | float or null | Live CPU temperature in °C (via macmon on Apple Silicon; `null` if macmon unavailable) |
| `gpu_temp` | float or null | Live GPU temperature in °C (via macmon; `null` if unavailable) |
| `thermal_pressure` | string or null | Fallback thermal level ("Nominal"/"Moderate"/"Heavy"/"Sleeping") when macmon can't provide a real temp; `null` on the macmon path |
| `cpu_freq_ghz` | float | Current CPU frequency in GHz |
| `load_1` / `load_5` / `load_15` | float or null | Load average over 1 / 5 / 15 minutes |
| `cpu_cores` | int | Logical CPU core count (context for load average) |
| `net_total_up_gb` / `net_total_down_gb` | float | Cumulative network sent / received in GB since boot |
| `docker_running` / `docker_total` | int or null | Running / total Docker containers (`null` if Docker is down) |
| `volumes` | array | Per-volume disk usage: `{name, mount, used_gb, total_gb, percent, internal}`. Internal data volume + external drives under `/Volumes`; system/recovery volumes filtered out |
| `power_w` | float | Measured system power in watts (macmon `sys_power`) |
| `energy_wh` | float | Cumulative energy in watt-hours since `energy_since`, persisted across restarts |
| `energy_since` | int | Unix epoch when energy tracking began |

**Notes:**
- Live temperature comes from [macmon](https://github.com/vladkens/macmon) (`brew install macmon`), which reads Apple Silicon sensors via the private IOReport API — no sudo. `powermetrics`/psutil cannot read the M4 die temperature.
- Without macmon the server degrades gracefully: `temp`/`gpu_temp` may be `null`, `thermal_pressure` carries the level, memory comes from psutil, and energy falls back to a flat `IDLE_BASE_W`.
- Memory (`ram`, `ram_used_gb`) also comes from macmon (Activity-Monitor-accurate); the percentage and GB are always derived from the same figure so they agree.
- `swap_used_gb` may be 0 on systems with minimal swap
- All KB/s values are instantaneous (not averages)
- `disk` reads the data volume, not `/` (the sealed read-only system snapshot, which misreports as ~26%)
- `power_w` / `energy_wh` come from macmon's measured `sys_power` (SoC/system power from the PMU). More realistic than the old estimate, but still not a PSU wall-plug reading.

**Refresh Rate**: Call every 5–10 seconds for smooth updates

---

### GET /api/config

Fetch the current configuration (projects and services).

**URL**: `/api/config?token=<TOKEN>`

**Query Parameters**: None (token required)

**Response (200 OK):**

```json
{
  "projects": [
    {
      "id": "my-github",
      "name": "My GitHub",
      "icon": "🐙",
      "desc": "GitHub profile",
      "url": "https://github.com/username",
      "check_url": "https://github.com/username",
      "visibility": "public"
    },
    {
      "id": "private-wiki",
      "name": "Private Wiki",
      "icon": "📖",
      "desc": "Internal documentation",
      "url": "http://wiki.local:3000",
      "check_url": "http://wiki.local:3000/health",
      "visibility": "private"
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

**Field Descriptions (Projects):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier, URL-safe (no spaces) |
| `name` | string | Yes | Display name on dashboard |
| `icon` | string | Yes | Emoji icon (1–4 characters) |
| `desc` | string | No | Description/subtitle |
| `url` | string | Yes | Link to the project |
| `check_url` | string | No | Health check URL (defaults to `url` if omitted) |
| `visibility` | string | Yes | "public" (visible) or "private" (hidden) |

**Field Descriptions (Services):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier, URL-safe |
| `name` | string | Yes | Display name on dashboard |
| `detail` | string | No | Subtitle (e.g., port number ":2283") |
| `port` | int | No | TCP port for health checks (1–65535) |
| `docker` | string | No | Primary Docker container name for logs |
| `containers` | array | No | List of `{label, docker}` objects for multi-container support |
| `log_file` | string | No | Path to a log file (fallback if Docker unavailable) |
| `check_url` | string | No | HTTP URL for health checks |

**Refresh Rate**: Call on app startup; cache client-side. Refetch after `PUT /api/config`.

---

### PUT /api/config

Update the configuration (projects and services). Requires write token.

**URL**: `/api/config?token=<WRITE_TOKEN>`

**Query Parameters:**
- `token`: Write token from `HOMEPAGE_WRITE_TOKEN` env var (required)

**Request Body:**

```json
{
  "projects": [
    {
      "id": "new-project",
      "name": "New Project",
      "icon": "✨",
      "desc": "A new project",
      "url": "https://example.com",
      "check_url": "https://example.com/health",
      "visibility": "public"
    }
  ],
  "services": [
    {
      "id": "nginx",
      "name": "Nginx",
      "detail": ":80",
      "port": 80,
      "docker": "nginx",
      "containers": [{"label": "Web", "docker": "nginx"}],
      "log_file": null,
      "check_url": null
    }
  ]
}
```

**Response (200 OK):**

```json
{
  "success": true,
  "message": "Config saved successfully"
}
```

**Validation Rules:**

- `projects` and `services` must be arrays (can be empty)
- Each project must have unique `id`
- Each service must have unique `id`
- `id` must be URL-safe (alphanumeric, hyphens, underscores only)
- `name` must be non-empty
- `icon` must be 1–4 characters (emoji recommended)
- `url` must be a valid URL (projects only)
- `check_url` must be a valid URL if provided
- `port` must be 1–65535 if provided
- `visibility` must be "public" or "private"
- `containers` array items must have non-empty `docker` names

**Error Responses:**

```json
{
  "error": "Invalid token"
}
```
(HTTP 401)

```json
{
  "error": "Invalid project id: contains spaces"
}
```
(HTTP 400)

```json
{
  "error": "Duplicate service id: immich"
}
```
(HTTP 400)

**Side Effects:**
- Config written to `config.json` on disk
- Background status-check thread triggers a one-shot health check for all services
- Any existing service health cache is cleared

---

### GET /api/services

Fetch service status from the last background health check.

**URL**: `/api/services?token=<TOKEN>`

**Query Parameters**: None (token required)

**Response (200 OK):**

```json
{
  "services": [
    {
      "id": "immich",
      "name": "Immich",
      "status": "online",
      "last_check": "2026-07-08T17:10:15.234Z"
    },
    {
      "id": "nginx",
      "name": "Nginx",
      "status": "offline",
      "last_check": "2026-07-08T17:10:10.456Z"
    }
  ]
}
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Service ID from config |
| `name` | string | Service name from config |
| `status` | string | Health status: "online", "offline", "warning", or "unknown" |
| `last_check` | string | ISO 8601 timestamp of last health check |

**Status Meanings:**

| Status | Meaning |
|--------|---------|
| `online` | Service responded successfully to health check |
| `offline` | Service did not respond or connection refused |
| `warning` | Service responded with error (e.g., HTTP 500) but is reachable |
| `unknown` | No health check configured (no `port` or `check_url`) |

**Refresh Rate**: Call every 30 seconds (matches background check interval)

---

### GET /api/tailscale

Tailnet devices and their online status. Runs `tailscale status --json` server-side
(no sudo). `funnel-ingress-node` peers (no `OS`) are filtered out; results are cached ~15 s.

**URL**: `/api/tailscale?token=<TOKEN>`

**Response:**
```json
{
  "devices": [
    { "name": "My Biggest BeefSteak", "os": "macOS", "online": true, "ip": "100.77.158.48", "last_seen": "0001-01-01T00:00:00Z", "is_self": true },
    { "name": "Galaxy J7 Prime", "os": "android", "online": true, "ip": "100.82.98.40", "last_seen": "2026-07-14T04:00:00Z", "is_self": false }
  ],
  "ts": 1784002684
}
```

Sorted self-first, then online, then by name. `last_seen` is Tailscale's zero timestamp
(`0001-...`) for actively-connected devices; the UI only shows it for offline devices.

**Refresh Rate**: Call every ~20 seconds.

---

### GET /api/docker

Per-container CPU/MEM from `docker stats --no-stream`. Cached ~12 s; empty list when Docker is down.

**URL**: `/api/docker?token=<TOKEN>`

**Response:**
```json
{
  "containers": [
    { "name": "immich_server", "cpu_pct": 0.2, "mem_pct": 19.3, "mem": "562.8MiB / 2.844GiB" }
  ],
  "ts": 1784002684
}
```

Sorted by CPU descending. `cpu_pct` can exceed 100 (multi-core). **Refresh Rate**: ~15 seconds.

---

### GET /api/alerts

The **overload event log**: a persistent record of times a stat went dangerously high. Detection
runs entirely server-side in a background loop (every ~20 s), so episodes are captured 24/7 — even
when no browser tab is open. Persisted to `alerts.json` and kept across restarts (last 200 episodes).

**URL**: `/api/alerts?limit=100&token=<TOKEN>`

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 100 | Max episodes to return, newest first (1–200) |
| `token` | string | (required) | API read token |

**Response (200 OK):**

```json
{
  "events": [
    { "id": 178400268400, "metric": "cpu", "label": "CPU", "unit": "%", "level": "critical",
      "threshold": 80, "peak": 98.4,
      "started_at": 1784002600, "updated_at": 1784003080, "ended_at": 1784003100 },
    { "id": 178399910003, "metric": "temp", "label": "CPU temp", "unit": "°C", "level": "warning",
      "threshold": 75, "peak": 84.1,
      "started_at": 1783999100, "updated_at": 1783999260, "ended_at": null }
  ],
  "rules": {
    "cpu":  { "label": "CPU", "unit": "%", "warn": 80, "crit": 95 },
    "load": { "label": "Load", "unit": "", "warn": 1.0, "crit": 2.0, "per_core": true }
  },
  "ts": 1784003200
}
```

**Episode field descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Stable identifier for the episode (`started_at × 100 + metric index`) |
| `metric` | string | One of `cpu`, `ram`, `swap`, `temp`, `load`, `disk` |
| `label` / `unit` | string | Display label and unit for the metric |
| `level` | string | Highest severity reached: `"warning"` or `"critical"` |
| `threshold` | float | The warn threshold that opened the episode (load resolved against core count) |
| `peak` | float | Highest value observed during the episode |
| `started_at` / `updated_at` / `ended_at` | int | Unix epoch (s). `ended_at` is `null` while the episode is still ongoing |

**Detection semantics** (all server-side, see `alert_loop` in `server.py`):
- An episode **opens** after a metric is above its `warn` threshold for 2 consecutive samples (~40 s) — brief spikes are ignored.
- While open, it tracks the `peak` and escalates `warning → critical` if the value crosses `crit`.
- It **closes** (sets `ended_at`) once the value drops below `warn − 5` (hysteresis, so a metric hovering at the line doesn't flap).
- `rules` echoes the current thresholds. `load` warn/crit are multipliers against `psutil.cpu_count()`; the resolved absolute value is stored per-episode in `threshold`.
- On restart, any episode left ongoing is finalized to its last-known time (live state can't be resumed).

**Refresh Rate**: Call every ~30 seconds.

---

### GET /api/logs

Fetch Docker container logs or log file contents.

**URL**: `/api/logs?service=<SERVICE_ID>&lines=50&container=<DOCKER_NAME>&token=<TOKEN>`

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `service` | string | immich | Service ID from config |
| `lines` | int | 50 | Number of log lines to return (1–500) |
| `container` | string | (optional) | Docker container name; overrides service's primary container |
| `token` | string | (required) | API read token |

**Examples:**

```
# Last 50 lines from Immich's primary container (immich_server)
GET /api/logs?service=immich&lines=50&token=TOKEN

# Last 100 lines from Immich's database container
GET /api/logs?service=immich&lines=100&container=immich-database&token=TOKEN

# Last 20 lines from a different service
GET /api/logs?service=nginx&lines=20&token=TOKEN
```

**Response (200 OK):**

```json
{
  "service": "immich",
  "lines": [
    {
      "timestamp": "2026-07-08T17:10:15.234Z",
      "level": "INFO",
      "msg": "Starting Immich server v1.102.1",
      "raw": "[2026-07-08 17:10:15.234] INFO: Starting Immich server v1.102.1"
    },
    {
      "timestamp": "2026-07-08T17:10:16.512Z",
      "level": "INFO",
      "msg": "Connected to database",
      "raw": "[2026-07-08 17:10:16.512] INFO: Connected to database"
    },
    {
      "timestamp": "2026-07-08T17:10:17.001Z",
      "level": "WARN",
      "msg": "High memory usage detected",
      "raw": "[2026-07-08 17:10:17.001] WARN: High memory usage detected"
    }
  ]
}
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `service` | string | Service ID |
| `lines` | array | Array of log entries |
| `timestamp` | string | Extracted timestamp (ISO 8601), or current time if unparseable |
| `level` | string | Log level: INFO, WARN, ERROR, DEBUG, or "UNKNOWN" |
| `msg` | string | Parsed log message (stripped of timestamp/level prefix) |
| `raw` | string | Original log line as received |

**Error Responses:**

```json
{
  "error": "Unknown service: invalid_id"
}
```
(HTTP 404)

```json
{
  "service": "immich",
  "lines": [],
  "warning": "No log source available. Set 'docker' container name or 'log_file' path in config.json."
}
```
(HTTP 200 — no logs available but valid service)

**Log Parsing:**

The server attempts to parse timestamps and log levels from various formats:
- Docker JSON logs: Extracts ISO timestamp and message
- Syslog: Parses `TIMESTAMP LEVEL: MESSAGE` format
- Python/Node.js: Handles `[TIMESTAMP] LEVEL: MESSAGE` format
- Fallback: Uses entire line as message if parsing fails

**Limits:**
- `lines` clamped to 1–500 (default 50)
- Timeout: 10 seconds for Docker logs, 5 seconds for log files
- Max response size: ~10 MB (depends on line length)

**Refresh Rate**: Call every 10 seconds for live log updates

---

### GET /api/health (bonus)

Simple health check endpoint (no token required).

**URL**: `/api/health`

**Response (200 OK):**

```json
{
  "status": "ok",
  "timestamp": "2026-07-08T17:10:15.234Z"
}
```

**Use**: Quick check if API is reachable (useful for monitoring/alerting).

---

## Response Formats

### Pagination

*Not currently implemented.* All endpoints return complete data. For large configs or logs, consider filtering client-side.

### Timestamps

All timestamps are **ISO 8601 format** (e.g., `2026-07-08T17:10:15.234Z`).

```javascript
new Date('2026-07-08T17:10:15.234Z')
```

### Numeric Values

- **Percentages**: 0–100 integer (no % symbol)
- **GB values**: Float (e.g., `8.2`, `16.0`)
- **Rates (KB/s, MB/s)**: Float (e.g., `512.5`, `15.2`)
- **Uptime (seconds)**: Integer (e.g., `345600`)
- **Ports**: Integer 1–65535
- **Frequencies**: Float in GHz (e.g., `3.2`)

---

## Examples

### JavaScript (Fetch API)

```javascript
const BASE_URL = 'https://my-biggest-beefsteak.tail437237.ts.net:8443';
const API_TOKEN = '3df484b5a0a1fd711ba4438c1c6d8b79cc66444375e0da80';

// Fetch stats
async function getStats() {
  const res = await fetch(`${BASE_URL}/api/stats?token=${API_TOKEN}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Fetch logs
async function getLogs(serviceId, containerName = null) {
  let url = `${BASE_URL}/api/logs?service=${serviceId}&lines=50&token=${API_TOKEN}`;
  if (containerName) url += `&container=${encodeURIComponent(containerName)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Update config (requires write token)
async function saveConfig(newConfig, writeToken) {
  const res = await fetch(`${BASE_URL}/api/config?token=${writeToken}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(newConfig)
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

// Usage
try {
  const stats = await getStats();
  console.log('CPU:', stats.cpu, '%');
  console.log('RAM:', stats.ram, '%');
  console.log('Thermal:', stats.thermal_pressure);
} catch (err) {
  console.error('Error fetching stats:', err);
}
```

### Python (requests)

```python
import requests
import json

BASE_URL = 'https://my-biggest-beefsteak.tail437237.ts.net:8443'
API_TOKEN = '3df484b5a0a1fd711ba4438c1c6d8b79cc66444375e0da80'

# Fetch stats
response = requests.get(f'{BASE_URL}/api/stats', params={'token': API_TOKEN})
stats = response.json()
print(f"CPU: {stats['cpu']}%")
print(f"RAM: {stats['ram']}%")

# Fetch logs
response = requests.get(f'{BASE_URL}/api/logs', params={
    'service': 'immich',
    'lines': 50,
    'container': 'immich-database',
    'token': API_TOKEN
})
logs = response.json()
for line in logs['lines'][:5]:
    print(f"[{line['level']}] {line['msg']}")

# Update config
new_config = {
    'projects': [...],
    'services': [...]
}
response = requests.put(
    f'{BASE_URL}/api/config',
    params={'token': WRITE_TOKEN},
    json=new_config,
    headers={'Content-Type': 'application/json'}
)
result = response.json()
print(result['message'])
```

### cURL

```bash
# Fetch stats
curl 'https://my-biggest-beefsteak.tail437237.ts.net:8443/api/stats?token=3df484b5a0a1fd711ba4438c1c6d8b79cc66444375e0da80'

# Fetch logs with container
curl 'https://my-biggest-beefsteak.tail437237.ts.net:8443/api/logs?service=immich&lines=20&container=immich-database&token=3df484b5a0a1fd711ba4438c1c6d8b79cc66444375e0da80'

# Update config
curl -X PUT \
  -H 'Content-Type: application/json' \
  -d '{"projects":[],"services":[]}' \
  'https://my-biggest-beefsteak.tail437237.ts.net:8443/api/config?token=WRITE_TOKEN'
```

---

## Server Implementation Details

### Technologies

- **Language**: Python 3.7+
- **Web Framework**: `http.server.BaseHTTPRequestHandler` (built-in)
- **System Stats**: `psutil` library
- **Docker Access**: `docker` library (requires Docker socket)
- **Background Thread**: `threading.Thread` for periodic health checks

### Performance

- **Startup Time**: ~2 seconds (including Docker connection)
- **Stats Gathering**: ~100–200 ms per `/api/stats` call
- **Health Check**: ~100–500 ms per service (depends on network latency)
- **Log Fetching**: ~500 ms–2 seconds (depends on container size)

### Concurrency

- Server handles concurrent requests via multi-threading
- Stats calls are read-only (no locking required)
- Config updates are serialized (file-level locking)
- Health checks run in background thread (no blocking)

### Storage

- Config saved to `config.json` in the server directory
- No database; everything is JSON
- Changes persist across restarts

---

**Last Updated**: 2026-07-08  
**API Version**: 1.0 (Batch 2)
