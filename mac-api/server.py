#!/usr/bin/env python3
"""
Mac Mini Stats & Logs API
=========================
Serves system stats, service status, and logs over HTTP so the GitHub Pages
dashboard can fetch them via Tailscale Funnel (which handles TLS).

Setup:
    pip3 install -r requirements.txt
    tailscale funnel --bg --https=8443 9000   # expose port 9000 publicly
    python3 server.py

Endpoints:
    GET  /api/stats                           - CPU, RAM, Disk, uptime, network
    GET  /api/services                        - live service + project status (cached)
    GET  /api/config                          - full project/service config (read)
    PUT  /api/config?token=<WRITE_TOKEN>      - update config (write, requires write token)
    GET  /api/logs?service=<id>&lines=50      - last N log lines

CORS is pre-configured for dao-xuan-thinh.github.io and localhost.
"""

import json
import re
import socket
import ssl
import subprocess
import threading
import time
import os
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

try:
    import psutil
except ImportError:
    print("ERROR: psutil not installed. Run:  pip3 install psutil")
    raise

# ── Configuration ──────────────────────────────────────────────────────────────

PORT = 9000

TAILSCALE_HOSTNAME = "my-biggest-beefsteak.tail437237.ts.net"

# Tailscale Funnel port (the HTTPS port exposed to the internet/Tailscale).
FUNNEL_PORT = 8443

# Origins allowed to access the API.
ALLOWED_ORIGINS = [
    "https://dao-xuan-thinh.github.io",
    "http://localhost",
    "http://localhost:9000",
    "http://127.0.0.1",
    "null",  # file:// access during local dev
]

# ── Token Auth ────────────────────────────────────────────────────────────────
# READ token - required for all GET /api/* requests.
# This ends up in the public app.js on GitHub Pages (practical barrier, not secret).
API_TOKEN = "3df484b5a0a1fd711ba4438c1c6d8b79cc66444375e0da80"

# WRITE token - required for PUT /api/config (saving settings changes).
# Loaded from the HOMEPAGE_WRITE_TOKEN environment variable so it never lives in code.
# Set it before starting the server:
#   export HOMEPAGE_WRITE_TOKEN="your-secret-token"
#   python3 server.py
_write_token_env = os.environ.get("HOMEPAGE_WRITE_TOKEN", "").strip()
if not _write_token_env:
    print("WARNING: HOMEPAGE_WRITE_TOKEN env var is not set. Settings saves will be rejected.")
    print("  Set it with:  export HOMEPAGE_WRITE_TOKEN=\"your-secret-token\"")
WRITE_TOKEN = _write_token_env

# ── Config file ───────────────────────────────────────────────────────────────
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

_config_lock  = threading.Lock()
_status_cache = {"services": [], "projects": [], "ts": 0}
_status_lock  = threading.Lock()

# ── Config helpers ────────────────────────────────────────────────────────────

def load_config():
    """Load config.json. Returns the parsed dict (never raises - returns {} on error)."""
    try:
        with _config_lock:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        print(f"[config] Failed to load {CONFIG_FILE}: {exc}")
        return {"projects": [], "services": []}


def save_config(data):
    """Atomically write config.json. Raises on error."""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = CONFIG_FILE + ".tmp"
    with _config_lock:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, CONFIG_FILE)


# ── Status checking ────────────────────────────────────────────────────────────

def check_port(port):
    """TCP connect to localhost:port - returns True if something is listening."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def check_url_reachable(url, timeout=4):
    """HTTP GET to url - returns True if we get any response (even 4xx/5xx)."""
    if not url:
        return False
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "HomepageBot/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx):
            return True
    except urllib.error.HTTPError:
        return True   # server replied - it's up
    except Exception:
        return False


def refresh_statuses():
    """Check all services and projects in parallel; update _status_cache."""
    config = load_config()
    services  = config.get("services", [])
    projects  = config.get("projects", [])

    svc_results  = []
    proj_results = []

    def check_service(svc):
        if svc.get("check_url"):
            online = check_url_reachable(svc["check_url"])
        elif svc.get("port"):
            online = check_port(svc["port"])
        else:
            online = False
        return {
            "id":     svc["id"],
            "name":   svc.get("name", svc["id"]),
            "detail": svc.get("detail", ""),
            "port":   svc.get("port"),
            "online": online,
        }

    def check_project(proj):
        online = check_url_reachable(proj.get("check_url") or proj.get("url", ""))
        return {
            "id":         proj["id"],
            "name":       proj.get("name", proj["id"]),
            "icon":       proj.get("icon", "🔗"),
            "desc":       proj.get("desc", ""),
            "url":        proj.get("url", ""),
            "visibility": proj.get("visibility", "public"),
            "online":     online,
        }

    checks = [(check_service, s) for s in services] + [(check_project, p) for p in projects]

    with ThreadPoolExecutor(max_workers=min(16, len(checks) + 1)) as ex:
        futures = {ex.submit(fn, item): (fn, item) for fn, item in checks}
        for fut in as_completed(futures):
            fn, item = futures[fut]
            try:
                result = fut.result()
                if fn is check_service:
                    svc_results.append(result)
                else:
                    proj_results.append(result)
            except Exception as exc:
                print(f"[status] Error checking {item.get('id', '?')}: {exc}")

    # Preserve ordering from config
    svc_order  = {s["id"]: i for i, s in enumerate(services)}
    proj_order = {p["id"]: i for i, p in enumerate(projects)}
    svc_results.sort(key=lambda x: svc_order.get(x["id"], 999))
    proj_results.sort(key=lambda x: proj_order.get(x["id"], 999))

    with _status_lock:
        _status_cache["services"]  = svc_results
        _status_cache["projects"]  = proj_results
        _status_cache["ts"]        = int(time.time())


def status_refresh_loop():
    """Background thread: refresh statuses every 30 seconds."""
    while True:
        try:
            refresh_statuses()
        except Exception as exc:
            print(f"[status] refresh error: {exc}")
        time.sleep(30)


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_cpu_temp():
    """
    Try to read CPU temperature.
    1. osx-cpu-temp (Homebrew) — rejects 0.0 which it returns on M4
    2. powermetrics cpu_power sampler — works on Intel Macs
    Returns float degrees C or None if unavailable (e.g. Apple Silicon M4).
    """
    # Try osx-cpu-temp first (brew install osx-cpu-temp)
    try:
        result = subprocess.run(["osx-cpu-temp"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            m = re.search(r"([\d.]+)", result.stdout)
            if m:
                val = float(m.group(1))
                if val > 0:  # 0.0 means the tool doesn't support this chip
                    return round(val, 1)
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # Fall back to powermetrics (Intel Macs)
    try:
        result = subprocess.run(
            ["sudo", "-n", "powermetrics", "--samplers", "cpu_power", "-n", "1", "-i", "100"],
            capture_output=True, text=True, timeout=10,
        )
        for pattern in [
            r"CPU die temperature:\s*([\d.]+)",
            r"Die Temperature:\s*([\d.]+)",
            r"CPU temperature:\s*([\d.]+)",
        ]:
            m = re.search(pattern, result.stdout, re.IGNORECASE)
            if m:
                return round(float(m.group(1)), 1)
    except Exception:
        pass

    return None


def get_thermal_pressure():
    """
    Read thermal pressure level via powermetrics thermal sampler.
    Works on Apple Silicon M4 even when actual temperature is unavailable.
    Returns one of: "Nominal", "Moderate", "Heavy", "Sleeping", or None.
    """
    try:
        result = subprocess.run(
            ["sudo", "-n", "powermetrics", "--samplers", "thermal", "-n", "1", "-i", "100"],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r"Current pressure level:\s*(\w+)", result.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def get_stats():
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")

    disk_before = psutil.disk_io_counters()
    net_before  = psutil.net_io_counters()
    time.sleep(0.5)
    disk_after  = psutil.disk_io_counters()
    net_after   = psutil.net_io_counters()

    net_tx = round((net_after.bytes_sent  - net_before.bytes_sent)  / 1024, 1)  # KB/s
    net_rx = round((net_after.bytes_recv  - net_before.bytes_recv)  / 1024, 1)
    disk_r = round((disk_after.read_bytes  - disk_before.read_bytes)  / 1024 / 1024, 2)  # MB/s
    disk_w = round((disk_after.write_bytes - disk_before.write_bytes) / 1024 / 1024, 2)

    uptime_seconds = int(time.time() - psutil.boot_time())

    # CPU frequency (not always available on Apple Silicon)
    cpu_freq = None
    try:
        freq = psutil.cpu_freq()
        if freq:
            cpu_freq = round(freq.current / 1000, 2)  # GHz
    except Exception:
        pass

    # Temperature - try osx-cpu-temp / powermetrics (Intel), fall back to psutil
    temp = get_cpu_temp()
    if temp is None:
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                all_temps = [t.current for group in temps.values() for t in group]
                if all_temps:
                    temp = round(sum(all_temps) / len(all_temps), 1)
        except (AttributeError, NotImplementedError):
            pass

    # Thermal pressure - always works on Apple Silicon M4 even when temp is None
    thermal_pressure = get_thermal_pressure()

    return {
        "cpu":          round(cpu, 1),
        "ram":          round(ram.percent, 1),
        "ram_used_gb":  round(ram.used   / 1024**3, 2),
        "ram_total_gb": round(ram.total  / 1024**3, 2),
        "swap":         round(swap.percent, 1),
        "swap_used_gb": round(swap.used  / 1024**3, 2),
        "disk":         round(disk.percent, 1),
        "disk_used_gb": round(disk.used  / 1024**3, 1),
        "disk_total_gb":round(disk.total / 1024**3, 1),
        "disk_read_mbs": disk_r,
        "disk_write_mbs":disk_w,
        "uptime":       uptime_seconds,
        "net_tx":       net_tx,
        "net_rx":       net_rx,
        "temp":         temp,
        "thermal_pressure": thermal_pressure,
        "cpu_freq_ghz": cpu_freq,
    }


def get_logs(service_key, lines=50):
    config = load_config()
    svc = next((s for s in config.get("services", []) if s["id"] == service_key), None)
    if not svc:
        return {"error": f"Unknown service: {service_key}"}

    raw_lines = []

    # Try Docker first
    if svc.get("docker"):
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(lines), "--timestamps", svc["docker"]],
                capture_output=True, text=True, timeout=10,
            )
            # Docker sends logs to stderr by default
            combined = (result.stdout + result.stderr).strip()
            if combined:
                raw_lines = combined.splitlines()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Fall back to log file
    if not raw_lines and svc.get("log_file") and os.path.exists(svc["log_file"]):
        try:
            result = subprocess.run(
                ["tail", "-n", str(lines), svc["log_file"]],
                capture_output=True, text=True, timeout=5,
            )
            raw_lines = result.stdout.strip().splitlines()
        except subprocess.TimeoutExpired:
            pass

    if not raw_lines:
        return {
            "service": service_key,
            "lines": [],
            "warning": "No log source available. Set 'docker' container name or 'log_file' path in config.json.",
        }

    parsed = []
    for line in raw_lines:
        parsed.append(parse_log_line(line))

    return {"service": service_key, "lines": parsed}


def parse_log_line(line):
    """
    Attempt to extract timestamp, level, and message from a log line.
    Handles Docker timestamped format and plain text logs.
    """
    line = line.strip()
    if not line:
        return None

    # Docker timestamp format: 2024-01-15T14:23:01.123456789Z  rest of log
    if len(line) > 30 and line[10] == "T" and "Z" in line[:35]:
        parts = line.split(" ", 1)
        ts_str = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        # Format time as HH:MM:SS
        try:
            ts_part = ts_str.split("T")[1][:8]
        except IndexError:
            ts_part = "??:??:??"
        level, msg = extract_level(rest)
        return {"time": ts_part, "level": level, "msg": msg or rest}

    # Plain line - no timestamp
    level, msg = extract_level(line)
    return {"time": "--", "level": level, "msg": msg or line}


LEVEL_KEYWORDS = {
    "ERROR": ["error", "err ", "exception", "critical", "fatal", "fail"],
    "WARN":  ["warn", "warning"],
    "DEBUG": ["debug", "trace", "verbose"],
    "INFO":  ["info"],
}

def extract_level(text):
    upper = text.upper()
    for level, keywords in LEVEL_KEYWORDS.items():
        for kw in keywords:
            if kw.upper() in upper:
                # Try to strip the level word from the start if present
                stripped = text
                for prefix in [f"[{level}]", f"{level}:", f" {level} "]:
                    if prefix in text.upper():
                        idx = text.upper().find(prefix) + len(prefix)
                        stripped = text[idx:].strip()
                        break
                return level, stripped
    return "INFO", text  # default to INFO


def json_response(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    set_cors(handler)
    handler.end_headers()
    handler.wfile.write(body)


def set_cors(handler):
    origin = handler.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        handler.send_header("Access-Control-Allow-Origin", origin)
    handler.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Vary", "Origin")


# ── Request Handler ────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Compact log format
        print(f"[{self.log_date_time_string()}] {self.address_string()} - {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(204)
        set_cors(self)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        # Token check on all /api/* routes
        if path.startswith("/api/"):
            token = qs.get("token", [None])[0]
            if token != API_TOKEN:
                json_response(self, {"error": "Unauthorized"}, 401)
                return

        if path == "/api/stats":
            try:
                data = get_stats()
                json_response(self, data)
            except Exception as e:
                json_response(self, {"error": str(e)}, 500)

        elif path == "/api/services":
            with _status_lock:
                data = dict(_status_cache)
            json_response(self, data)

        elif path == "/api/config":
            config = load_config()
            json_response(self, config)

        elif path == "/api/logs":
            service = qs.get("service", ["immich"])[0]
            lines = int(qs.get("lines", ["50"])[0])
            lines = max(1, min(lines, 500))  # clamp 1-500
            try:
                data = get_logs(service, lines)
                data["lines"] = [l for l in data.get("lines", []) if l]  # remove None
                json_response(self, data)
            except Exception as e:
                json_response(self, {"error": str(e)}, 500)

        elif path in ("", "/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Mac Mini Stats API - OK\n")

        else:
            json_response(self, {"error": "Not found"}, 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path == "/api/config":
            token = qs.get("token", [None])[0]
            if not WRITE_TOKEN or token != WRITE_TOKEN:
                json_response(self, {"error": "Unauthorized - write token required"}, 401)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                new_config = json.loads(body.decode("utf-8"))
                # Basic validation
                if not isinstance(new_config.get("projects"), list) or \
                   not isinstance(new_config.get("services"), list):
                    json_response(self, {"error": "Invalid config shape"}, 400)
                    return
                save_config(new_config)
                # Trigger a status refresh in the background
                threading.Thread(target=refresh_statuses, daemon=True).start()
                json_response(self, {"ok": True})
            except (json.JSONDecodeError, ValueError) as e:
                json_response(self, {"error": f"Bad JSON: {e}"}, 400)
            except Exception as e:
                json_response(self, {"error": str(e)}, 500)
        else:
            json_response(self, {"error": "Not found"}, 404)


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Bind to 127.0.0.1 - Tailscale Funnel connects from localhost.
    # This blocks direct Tailscale-IP connections that cause TLS noise in the log.
    server = HTTPServer(("127.0.0.1", PORT), Handler)

    print(f"Mac Mini Stats API running on port {PORT} (plain HTTP - TLS handled by Tailscale Funnel)")
    print(f"  API token:   {API_TOKEN}")
    print(f"  Write token: {WRITE_TOKEN}")
    print(f"  Local:    http://{TAILSCALE_HOSTNAME}:{PORT}/api/stats?token={API_TOKEN}")
    print(f"")
    print(f"  Public URL (via Tailscale Funnel on :{FUNNEL_PORT}):")
    print(f"  https://{TAILSCALE_HOSTNAME}:{FUNNEL_PORT}/api/stats?token={API_TOKEN}")
    print("Press Ctrl+C to stop.")

    # Initial status check + background refresh loop
    print("[status] Running initial status check...")
    threading.Thread(target=refresh_statuses, daemon=True).start()
    threading.Thread(target=status_refresh_loop, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
