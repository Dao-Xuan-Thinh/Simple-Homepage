#!/usr/bin/env python3
"""
Mac Mini Stats & Logs API
=========================
Serves system stats and service logs over HTTP so the GitHub Pages
dashboard can fetch them over Tailscale.

Usage:
    pip3 install -r requirements.txt
    python3 server.py

Endpoints:
    GET /api/stats                          — CPU, RAM, Disk, uptime, network
    GET /api/services                       — per-service TCP health check
    GET /api/logs?service=immich&lines=50   — last N log lines

CORS is pre-configured for dao-xuan-thinh.github.io and localhost.
"""

import json
import socket
import subprocess
import time
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

try:
    import psutil
except ImportError:
    print("ERROR: psutil not installed. Run:  pip3 install psutil")
    raise

# ── Configuration ──────────────────────────────────────────────────────────────

PORT = 9000

# Origins allowed to access the API.
# Add any extra origins here (e.g. other Tailscale devices you use).
ALLOWED_ORIGINS = [
    "https://dao-xuan-thinh.github.io",
    "http://localhost",
    "http://localhost:9000",
    "http://127.0.0.1",
    "null",  # file:// access during local dev
]

# Per-service config.
# "docker"   : Docker container name (use `docker ps` to find it). Set to None to skip.
# "log_file" : Absolute path to a log file. Used if docker is None or docker logs fail.
# "port"     : Port on localhost to TCP-check for the health endpoint.
SERVICES = {
    "immich": {
        "name": "Immich",
        "docker": "immich_server",   # adjust to your actual container name
        "log_file": None,
        "port": 2283,
    },
    "openclaw": {
        "name": "OpenClaw",
        "docker": "openclaw",        # adjust to your actual container name
        "log_file": None,
        "port": 3000,
    },
    "projects": {
        "name": "Project Sites",
        "docker": None,
        "log_file": None,            # e.g. "/var/log/nginx/access.log"
        "port": 8080,
    },
    "proto": {
        "name": "Prototypes",
        "docker": None,
        "log_file": None,
        "port": 10000,
    },
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def get_stats():
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net_before = psutil.net_io_counters()
    time.sleep(0.5)
    net_after = psutil.net_io_counters()

    net_tx = round((net_after.bytes_sent - net_before.bytes_sent) / 1024, 1)  # KB/s
    net_rx = round((net_after.bytes_recv - net_before.bytes_recv) / 1024, 1)

    uptime_seconds = int(time.time() - psutil.boot_time())

    # Temperature — best effort; macOS M-series often returns empty dict
    temp = None
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            all_temps = [t.current for group in temps.values() for t in group]
            if all_temps:
                temp = round(sum(all_temps) / len(all_temps), 1)
    except (AttributeError, NotImplementedError):
        pass

    return {
        "cpu":    round(cpu, 1),
        "ram":    round(ram.percent, 1),
        "disk":   round(disk.percent, 1),
        "uptime": uptime_seconds,
        "net_tx": net_tx,
        "net_rx": net_rx,
        "temp":   temp,
        "ram_used_gb":  round(ram.used / 1024**3, 2),
        "ram_total_gb": round(ram.total / 1024**3, 2),
    }


def check_service(port):
    """TCP connect to localhost:port — returns True if something is listening."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def get_services_status():
    result = []
    for key, svc in SERVICES.items():
        online = check_service(svc["port"]) if svc["port"] else False
        result.append({
            "id":     key,
            "name":   svc["name"],
            "port":   svc["port"],
            "online": online,
        })
    return result


def get_logs(service_key, lines=50):
    svc = SERVICES.get(service_key)
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
            "warning": "No log source available. Configure 'docker' container name or 'log_file' path in server.py SERVICES dict.",
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

    # Plain line — no timestamp
    level, msg = extract_level(line)
    return {"time": "——", "level": level, "msg": msg or line}


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
    else:
        # Deny — don't send CORS header
        pass
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Vary", "Origin")


# ── Request Handler ────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Compact log format
        print(f"[{self.log_date_time_string()}] {self.address_string()} — {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(204)
        set_cors(self)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path == "/api/stats":
            try:
                data = get_stats()
                json_response(self, data)
            except Exception as e:
                json_response(self, {"error": str(e)}, 500)

        elif path == "/api/services":
            try:
                data = get_services_status()
                json_response(self, data)
            except Exception as e:
                json_response(self, {"error": str(e)}, 500)

        elif path == "/api/logs":
            service = qs.get("service", ["immich"])[0]
            lines = int(qs.get("lines", ["50"])[0])
            lines = max(1, min(lines, 500))  # clamp 1–500
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
            self.wfile.write(b"Mac Mini Stats API — OK\n")

        else:
            json_response(self, {"error": "Not found"}, 404)


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Mac Mini Stats API running on port {PORT}")
    print(f"  Stats:    http://localhost:{PORT}/api/stats")
    print(f"  Services: http://localhost:{PORT}/api/services")
    print(f"  Logs:     http://localhost:{PORT}/api/logs?service=immich&lines=50")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
