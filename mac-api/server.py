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
    GET  /api/alerts?limit=100                - overload event log (stats that went dangerously high)
    GET  /api/history?minutes=30[&step=1800]  - metric history (fine samples / 5-min buckets)
         [&host=laptop]                       - ... of the laptop instead (pushed by laptop-agent)
    GET  /api/laptop                          - laptop status, latest sample, top apps, 30-min series
    GET  /api/laptop/apps?minutes=1440        - which apps used the most CPU / RAM over a window
    POST /api/laptop/push                     - laptop-agent upload (X-Push-Token header)
    GET  /api/logs?service=<id>&lines=50      - last N log lines

CORS is pre-configured for dao-xuan-thinh.github.io and localhost.
"""

import calendar
import collections
import json
import re
import socket
import ssl
import subprocess
import threading
import time
import os
import secrets
import shutil
import signal
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from laptop import Laptop

try:
    import psutil
except ImportError:
    print("ERROR: psutil not installed. Run:  pip3 install psutil")
    raise


def log(msg):
    """print() for the background threads. stdout is api.log, so a full disk makes
    print itself raise OSError - inside an except handler that escapes and kills the
    thread for good (that is how history, alerts and status froze on 2026-09-27).
    A lost log line is fine; a dead sampler is not."""
    try:
        print(msg, flush=True)
    except Exception:
        pass

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

# macmon (https://github.com/vladkens/macmon) reads Apple Silicon sensors via the
# private IOReport API - no sudo. We use it for live CPU/GPU temperature, a memory
# figure that matches Activity Monitor, and real measured system power.
MACMON_BIN    = shutil.which("macmon") or "/opt/homebrew/bin/macmon"
TAILSCALE_BIN = shutil.which("tailscale") or "/usr/local/bin/tailscale"

# ── Energy tracking ───────────────────────────────────────────────────────────
# Integrate measured system power (macmon sys_power) into a running kWh total that
# persists across restarts in energy.json. sys_power is the SoC/system power from
# the PMU - more realistic than compute-only power, though still not a PSU wall
# reading. IDLE_BASE_W is only a last-resort fallback if macmon is unavailable.
IDLE_BASE_W     = 6.0
ENERGY_INTERVAL = 60  # seconds between power samples
ENERGY_FILE     = os.path.join(os.path.dirname(CONFIG_FILE), "energy.json")

_energy      = {"total_wh": 0.0, "since": int(time.time()), "power_w": 0.0}
_energy_lock = threading.Lock()

# ── Alert / overload event log ──────────────────────────────────────────────────
# A background loop samples key metrics and records "episodes" - continuous stretches
# where a metric stays above a warn threshold - so the dashboard can show WHEN the
# machine was under stress even while nobody was watching a browser tab. Episodes are
# edge-triggered with hysteresis (see alert_loop) and persisted to alerts.json.
ALERT_INTERVAL = 20    # seconds between samples
ALERT_MARGIN   = 5     # default hysteresis; each rule can override it with "margin"
ALERT_CONSEC   = 2     # consecutive breaching samples required before an episode opens
ALERT_MAX      = 200   # keep at most this many episodes (oldest dropped)
ALERTS_FILE    = os.path.join(os.path.dirname(CONFIG_FILE), "alerts.json")

# metric -> rule. warn/crit are absolute thresholds, except "load" whose warn/crit are
# multipliers against the core count (resolved per-sample). `margin` is that rule's
# hysteresis: an open episode only closes below (warn - margin), in the metric's own
# units. unit is display-only.
#
# Swap is measured in absolute GB, NOT as a percentage of the swap file. macOS sizes
# its swapfiles dynamically - it adds another when the current one fills - so
# used/total is a sawtooth that sits in a 50-90% band by design and says nothing about
# memory pressure. (Observed here: the same ~1.5 GB of swap read as 94% one day and
# 50% the next, purely because the total grew from 2 GB to 3 GB.) The percentage is
# still recorded for the graphs; it just isn't something to alert on.
ALERT_RULES = {
    "cpu":     {"label": "CPU",      "unit": "%",   "warn": 80,  "crit": 95,  "margin": 5},
    "ram":     {"label": "RAM",      "unit": "%",   "warn": 85,  "crit": 95,  "margin": 5},
    "swap_gb": {"label": "Swap",     "unit": " GB", "warn": 4,   "crit": 8,   "margin": 0.75},
    "temp":    {"label": "CPU temp", "unit": "°C",  "warn": 75,  "crit": 88,  "margin": 5},
    "load":    {"label": "Load",     "unit": "",    "warn": 1.0, "crit": 2.0, "margin": 0.25,
                "per_core": True},
    "disk":    {"label": "Disk",     "unit": "%",   "warn": 85,  "crit": 95,  "margin": 5},
}

_alerts        = []    # list of episode dicts, oldest-first (active ones mutate in place)
_alerts_active = {}    # metric -> the currently-open episode dict for that metric
_alerts_lock   = threading.Lock()

# ── Metric history (sparkline backfill) ─────────────────────────────────────────
# The same loop that feeds the alert machine also records each sample, so the dashboard's
# graphs show a real time window the instant a browser tab opens instead of only what that
# tab has watched live. Two tiers:
#
#   fine   - every sample, ~1 h. Full resolution for the 30-minute sparklines. Saved to
#            history-live.json every HISTORY_LIVE_EVERY samples, together with the bucket
#            still filling, so a restart only loses the last minute or so.
#   bucket - 5-minute min/avg/max aggregates, persisted to history.json, 7 days. Backs the
#            expanded card views (6 h / 24 h / 7 d) and the disk-usage trend projection.
# Both files are also written on a clean stop (SIGTERM / Ctrl-C).
HISTORY_MAX     = 200    # fine samples kept; at ALERT_INTERVAL=20 s that's ~66 min
BUCKET_SECONDS  = 300    # 5-minute aggregation buckets
BUCKET_MAX      = 2016   # 7 days of 5-minute buckets
BUCKET_FINE_MAX = 60     # /api/history windows <= this many minutes use the fine tier
HISTORY_FILE    = os.path.join(os.path.dirname(CONFIG_FILE), "history.json")
HISTORY_LIVE_FILE  = os.path.join(os.path.dirname(CONFIG_FILE), "history-live.json")
HISTORY_LIVE_EVERY = 3    # samples between history-live.json saves (~1 min)
RESUME_GAP         = 300  # an episode still open at shutdown resumes if we're back within this

_history      = collections.deque(maxlen=HISTORY_MAX)
_buckets      = collections.deque(maxlen=BUCKET_MAX)  # closed buckets, oldest first
_bucket_open  = {}       # metric -> list of values in the bucket currently filling
_bucket_start = 0        # epoch of the bucket currently filling (0 = none yet)
_history_lock = threading.Lock()

# Metrics carried through the history tiers. Superset of ALERT_RULES: power and network
# throughput are recorded for the graphs but have no alert thresholds attached.
HISTORY_METRICS = list(ALERT_RULES) + ["swap", "power", "net_rx", "net_tx"]

# ── Service downtime episodes ───────────────────────────────────────────────────
# refresh_statuses() already probes every service every 30 s; feeding those booleans
# through the same episode machinery gives a record of WHEN something was down, logged
# alongside the metric alerts in alerts.json so the dashboard has one event log.
DOWN_CONSEC = 2  # consecutive failed checks before an outage is recorded

_down_active  = {}   # service id -> the currently-open outage episode
_down_pending = {}   # service id -> consecutive failed checks so far

_net_last = None     # (epoch, bytes_recv, bytes_sent) from the previous alert-loop sample

# ── Config helpers ────────────────────────────────────────────────────────────

def load_config():
    """Load config.json. Returns the parsed dict (never raises - returns {} on error)."""
    try:
        with _config_lock:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        log(f"[config] Failed to load {CONFIG_FILE}: {exc}")
        return {"projects": [], "services": []}


def save_config(data):
    """Atomically write config.json. Raises on error."""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = CONFIG_FILE + ".tmp"
    with _config_lock:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, CONFIG_FILE)


# ── Energy tracking helpers ────────────────────────────────────────────────────

def load_energy():
    """Load the persisted energy total into _energy. Starts fresh if absent/corrupt."""
    try:
        with open(ENERGY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _energy_lock:
            _energy["total_wh"] = float(data.get("total_wh", 0.0))
            _energy["since"]    = int(data.get("since", int(time.time())))
    except FileNotFoundError:
        pass
    except Exception as exc:
        log(f"[energy] Failed to load {ENERGY_FILE}: {exc}")


def save_energy(last_update):
    """Atomically persist the running energy total."""
    with _energy_lock:
        data = {
            "total_wh":    round(_energy["total_wh"], 4),
            "since":       _energy["since"],
            "last_update": int(last_update),
        }
    tmp = ENERGY_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, ENERGY_FILE)
    except Exception as exc:
        log(f"[energy] Failed to save {ENERGY_FILE}: {exc}")


def get_macmon(interval_ms=200, samples=1):
    """
    Sample Apple Silicon sensors via macmon (IOReport - no sudo). Returns a
    normalized dict, or None on failure (not installed, timeout, bad JSON).
    A short interval is fine for point-in-time temp/memory; use ~1000 ms when the
    power reading matters (it needs a sampling window).
    """
    try:
        result = subprocess.run(
            [MACMON_BIN, "pipe", "-s", str(samples), "-i", str(interval_ms)],
            capture_output=True, text=True, timeout=8,
        )
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        if not lines:
            return None
        d = json.loads(lines[-1])
        temp = d.get("temp", {}) or {}
        mem  = d.get("memory", {}) or {}
        pcpu = d.get("pcpu_usage") or [None]   # [MHz, usage] of the performance cluster
        return {
            "cpu_temp":   temp.get("cpu_temp_avg"),
            "gpu_temp":   temp.get("gpu_temp_avg"),
            "ram_used":   mem.get("ram_usage"),
            "ram_total":  mem.get("ram_total"),
            "swap_used":  mem.get("swap_usage"),
            "swap_total": mem.get("swap_total"),
            "sys_power":  d.get("sys_power"),
            "all_power":  d.get("all_power"),
            "pcpu_mhz":   pcpu[0],
        }
    except Exception:
        return None


def energy_loop():
    """
    Background thread: every ENERGY_INTERVAL seconds, sample measured system power
    (macmon sys_power) and integrate it into the persisted kWh total. Downtime is
    not counted - dt is capped so sleep/off gaps don't spike the total.
    """
    load_energy()
    last_update = time.time()
    while True:
        time.sleep(ENERGY_INTERVAL)
        try:
            mac = get_macmon(interval_ms=1000)  # 1 s window for an accurate power read
            now = time.time()
            dt = min(now - last_update, 5 * ENERGY_INTERVAL)  # cap gaps (sleep/downtime)
            if mac and mac.get("sys_power") is not None:
                watts = mac["sys_power"]
            elif mac and mac.get("all_power") is not None:
                watts = mac["all_power"]
            else:
                watts = IDLE_BASE_W  # last-resort fallback if macmon is unavailable
            with _energy_lock:
                _energy["total_wh"] += watts * (dt / 3600.0)
                _energy["power_w"]   = round(watts, 2)
            save_energy(now)
            last_update = now
        except Exception as exc:
            log(f"[energy] loop error: {exc}")


# ── Alert / overload event log helpers ──────────────────────────────────────────

def load_alerts():
    """Load persisted episodes into _alerts. An episode still marked ongoing at the last
    shutdown resumes if it was updated within RESUME_GAP - a quick restart shouldn't split
    one incident into two entries; if the condition cleared meanwhile, the next sample
    closes it. Older ones are finalized to their last-known time."""
    try:
        with open(ALERTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    except Exception as exc:
        log(f"[alerts] Failed to load {ALERTS_FILE}: {exc}")
        return
    events = data.get("events", []) if isinstance(data, dict) else data
    now = int(time.time())
    with _alerts_lock:
        _alerts.clear()
        _alerts_active.clear()
        _down_active.clear()
        for ev in events:
            if ev.get("ended_at") is None:
                last = ev.get("updated_at") or ev.get("started_at")
                active = _down_active if ev.get("kind") == "service" else _alerts_active
                if now - last <= RESUME_GAP and ev.get("metric") not in active:
                    active[ev["metric"]] = ev
                else:
                    ev["ended_at"] = last
            _alerts.append(ev)


def save_alerts():
    """Atomically persist the alert episode list (capped to the most recent ALERT_MAX)."""
    with _alerts_lock:
        data = {"events": _alerts[-ALERT_MAX:]}
    tmp = ALERTS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, ALERTS_FILE)
    except Exception as exc:
        log(f"[alerts] Failed to save {ALERTS_FILE}: {exc}")


def _sample_alert_metrics():
    """A lightweight metric snapshot for the alert loop: {cpu, ram, swap, swap_gb, temp, load,
    disk, power, net_rx, net_tx}. Deliberately leaner than get_stats() (no docker/volumes)
    so the loop stays cheap. Any value may be None if unavailable; the loop skips None
    metrics. `swap` (percent), `power` and the net_* pair have no alert rules - they are
    sampled purely to feed the history tiers; swap is alerted on as swap_gb instead."""
    out = {"cpu": None, "ram": None, "swap": None, "swap_gb": None, "temp": None,
           "load": None, "disk": None, "power": None, "net_rx": None, "net_tx": None}

    try:
        out["cpu"] = round(psutil.cpu_percent(interval=0.5), 1)
    except Exception:
        pass

    # One macmon sample for temp + memory + power (matches get_stats); fall back to
    # psutil. A 1 s window is needed for sys_power to mean anything.
    mac = get_macmon(interval_ms=1000)
    if mac and mac.get("cpu_temp") is not None:
        out["temp"] = round(mac["cpu_temp"], 1)
    if mac:
        watts = mac.get("sys_power")
        if watts is None:
            watts = mac.get("all_power")
        if watts is not None:
            out["power"] = round(watts, 2)
    try:
        if mac and mac.get("ram_used") and mac.get("ram_total"):
            out["ram"] = round(mac["ram_used"] / mac["ram_total"] * 100, 1)
            su = mac.get("swap_used") or 0
            st = mac.get("swap_total") or 0
            out["swap"]    = round(su / st * 100, 1) if st else 0.0
            out["swap_gb"] = round(su / 1024 ** 3, 2)
        else:
            vm = psutil.virtual_memory()
            sw = psutil.swap_memory()
            out["ram"]     = round((vm.total - vm.available) / vm.total * 100, 1)
            out["swap"]    = round(sw.percent, 1)
            out["swap_gb"] = round(sw.used / 1024 ** 3, 2)
    except Exception:
        pass

    try:
        out["load"] = round(os.getloadavg()[0], 2)
    except Exception:
        pass

    for mount in ("/System/Volumes/Data", "/"):
        try:
            out["disk"] = round(psutil.disk_usage(mount).percent, 1)
            break
        except Exception:
            continue

    # Network throughput in KB/s, from the counter delta since the previous sample.
    # The first call has no baseline, so net_rx/net_tx stay None for one interval.
    global _net_last
    try:
        io  = psutil.net_io_counters()
        now = time.time()
        if _net_last:
            dt = now - _net_last[0]
            if dt > 0:
                out["net_rx"] = round(max(0, io.bytes_recv - _net_last[1]) / dt / 1024, 1)
                out["net_tx"] = round(max(0, io.bytes_sent - _net_last[2]) / dt / 1024, 1)
        _net_last = (now, io.bytes_recv, io.bytes_sent)
    except Exception:
        pass

    return out


_ALERT_METRICS = list(ALERT_RULES)

def _step_alerts(sample, now, cores, pending):
    """Advance the alert state machine by one sample. Each metric is its own machine:
      - opens an episode after ALERT_CONSEC consecutive samples above `warn`
      - while open, tracks the peak and escalates warning -> critical at `crit`
      - closes (sets ended_at) once the value drops below `warn - ALERT_MARGIN`
    The hysteresis + consecutive-sample gate keep a metric hovering at the line from
    spawning a flood of tiny entries. Mutates the module-level _alerts / _alerts_active
    (under _alerts_lock) and the caller's `pending` dict; returns True if anything
    changed. `now` is passed in (not read from the clock) so the logic is deterministic
    and unit-testable."""
    changed = False
    with _alerts_lock:
        for metric, rule in ALERT_RULES.items():
            value = sample.get(metric)
            if value is None:
                continue
            mult  = cores if rule.get("per_core") else 1
            warn  = rule["warn"] * mult
            crit  = rule["crit"] * mult
            # Hysteresis is per-rule and in the metric's own units — a flat margin
            # would never let a small-scale rule (swap in GB) close again.
            close = warn - rule.get("margin", ALERT_MARGIN) * mult
            active = _alerts_active.get(metric)

            if active is not None:
                if value > active["peak"]:
                    active["peak"] = round(value, 1)
                if value >= crit and active["level"] != "critical":
                    active["level"] = "critical"
                if value >= close:
                    active["updated_at"] = now      # still elevated
                else:
                    active["ended_at"] = now        # dropped clear of the band
                    _alerts_active.pop(metric, None)
                changed = True
            elif value >= warn:
                pending[metric] = pending.get(metric, 0) + 1
                if pending[metric] >= ALERT_CONSEC:
                    pending[metric] = 0
                    ep = {
                        "id":         now * 100 + _ALERT_METRICS.index(metric),
                        "kind":       "metric",
                        "metric":     metric,
                        "label":      rule["label"],
                        "unit":       rule["unit"],
                        "level":      "critical" if value >= crit else "warning",
                        "threshold":  round(warn, 1),
                        "peak":       round(value, 1),
                        "started_at": now,
                        "updated_at": now,
                        "ended_at":   None,
                    }
                    _alerts.append(ep)
                    _alerts_active[metric] = ep
                    if len(_alerts) > ALERT_MAX:
                        del _alerts[:len(_alerts) - ALERT_MAX]
                    changed = True
            else:
                pending[metric] = 0
    return changed


def _step_downtime(services, now):
    """Advance the service-outage state machine by one status refresh. Mirrors
    _step_alerts, but the input is a boolean (reachable / not) rather than a threshold:
      - opens an outage after DOWN_CONSEC consecutive failed checks
      - closes it on the first successful check
    Outages land in the same _alerts list as the metric episodes - one event log, one
    file, one endpoint - tagged with kind="service". Returns True if anything changed."""
    changed = False
    with _alerts_lock:
        for svc in services:
            sid = svc.get("id")
            if not sid:
                continue
            active = _down_active.get(sid)

            if svc.get("online"):
                _down_pending[sid] = 0
                if active is not None:
                    active["ended_at"] = now
                    _down_active.pop(sid, None)
                    changed = True
            elif active is not None:
                active["updated_at"] = now
                changed = True
            else:
                _down_pending[sid] = _down_pending.get(sid, 0) + 1
                if _down_pending[sid] >= DOWN_CONSEC:
                    _down_pending[sid] = 0
                    # 90+ namespace keeps service ids clear of the metric ones (which use
                    # the metric's index); bump on collision if two drop in one second.
                    eid = now * 100 + 90
                    while any(e["id"] == eid for e in _alerts[-20:]):
                        eid += 1
                    ep = {
                        "id":         eid,
                        "kind":       "service",
                        "metric":     sid,
                        "label":      svc.get("name", sid),
                        "unit":       "",
                        "level":      "critical",
                        "started_at": now,
                        "updated_at": now,
                        "ended_at":   None,
                    }
                    _alerts.append(ep)
                    _down_active[sid] = ep
                    if len(_alerts) > ALERT_MAX:
                        del _alerts[:len(_alerts) - ALERT_MAX]
                    changed = True

        # A service that was archived or deleted mid-outage is no longer checked, so
        # nothing would ever close its episode - end it here instead.
        checked = {svc.get("id") for svc in services}
        for sid in [s for s in _down_active if s not in checked]:
            _down_active.pop(sid)["ended_at"] = now
            _down_pending.pop(sid, None)
            changed = True
    return changed


def load_history():
    """Load persisted 5-minute buckets. Never raises - a missing or corrupt file just
    means the long-window graphs start empty and refill as samples arrive."""
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        buckets = data.get("buckets", [])
        cutoff = int(time.time()) - BUCKET_MAX * BUCKET_SECONDS
        with _history_lock:
            _buckets.clear()
            _buckets.extend(b for b in buckets if isinstance(b, dict) and b.get("t", 0) >= cutoff)
    except FileNotFoundError:
        pass
    except Exception as exc:
        log(f"[history] Failed to load {HISTORY_FILE}: {exc}")

    global _bucket_start
    try:
        with open(HISTORY_LIVE_FILE, "r", encoding="utf-8") as f:
            live = json.load(f)
        cutoff = int(time.time()) - HISTORY_MAX * ALERT_INTERVAL
        with _history_lock:
            _history.clear()
            _history.extend(p for p in live.get("fine", []) if isinstance(p, dict) and p.get("t", 0) >= cutoff)
            # Restore the bucket that was filling. If its slot has passed, the next
            # sample closes it into _buckets as usual.
            if live.get("open_start") and isinstance(live.get("open"), dict):
                _bucket_open.clear()
                _bucket_open.update(live["open"])
                _bucket_start = live["open_start"]
    except FileNotFoundError:
        pass
    except Exception as exc:
        log(f"[history] Failed to load {HISTORY_LIVE_FILE}: {exc}")


def save_history_live():
    """Atomically persist the fine tier and the bucket still filling - small (~30 KB),
    so it can be written every minute."""
    with _history_lock:
        data = {"fine": list(_history), "open": _bucket_open, "open_start": _bucket_start}
        data = json.dumps(data, separators=(",", ":"))
    tmp = HISTORY_LIVE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, HISTORY_LIVE_FILE)
    except Exception as exc:
        log(f"[history] Failed to save {HISTORY_LIVE_FILE}: {exc}")


def save_history():
    """Atomically persist the closed buckets. Called once per closed bucket (every 5 min),
    not per sample, so this stays cheap."""
    with _history_lock:
        data = {"buckets": list(_buckets), "bucket_seconds": BUCKET_SECONDS}
    tmp = HISTORY_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, HISTORY_FILE)
    except Exception as exc:
        log(f"[history] Failed to save {HISTORY_FILE}: {exc}")


def _close_bucket():
    """Fold the values accumulated in the open bucket into a min/avg/max aggregate and
    move it into the ring. Caller must hold _history_lock. Returns True if one was
    appended (i.e. there is something new worth persisting)."""
    global _bucket_start
    if not _bucket_open or not _bucket_start:
        return False
    agg = {"t": _bucket_start}
    for metric, vals in _bucket_open.items():
        if vals:
            agg[metric] = {
                "min": round(min(vals), 2),
                "avg": round(sum(vals) / len(vals), 2),
                "max": round(max(vals), 2),
            }
    _bucket_open.clear()
    if len(agg) > 1:            # more than just the timestamp
        _buckets.append(agg)
        return True
    return False


def _coarsen(buckets, step):
    """Merge consecutive 5-minute buckets into step-second groups (min of mins, max of
    maxes, mean of avgs), aligned to wall-clock step boundaries. A 7-day window is 2016
    buckets - far more points than a chart is wide - so long views ask for e.g. 30 min.
    Laptop buckets carry "os"; a group never spans two OSes."""
    out, cur, slot, start, group_os = [], {}, None, None, None

    def flush():
        agg = {"t": start}
        if group_os:
            agg["os"] = group_os
        for metric, parts in cur.items():
            agg[metric] = {
                "min": min(p["min"] for p in parts),
                "avg": round(sum(p["avg"] for p in parts) / len(parts), 2),
                "max": max(p["max"] for p in parts),
            }
        out.append(agg)

    for b in buckets:
        s = b["t"] - (b["t"] % step)
        if s != slot or b.get("os") != group_os:
            if cur:
                flush()
            # An OS switch mid-group starts the new group at its first bucket.
            start = s if s != slot else b["t"]
            cur, slot, group_os = {}, s, b.get("os")
        for metric, val in b.items():
            if metric != "t" and isinstance(val, dict):
                cur.setdefault(metric, []).append(val)
    if cur:
        flush()
    return out


def _history_push(sample, now):
    """Record one sample in both tiers. Returns True when a bucket just closed (the
    caller then persists). Buckets are aligned to wall-clock BUCKET_SECONDS boundaries so
    they line up across restarts."""
    global _bucket_start
    point = {"t": now}
    point.update({k: v for k, v in sample.items() if v is not None})
    slot = now - (now % BUCKET_SECONDS)
    with _history_lock:
        _history.append(point)
        closed = False
        if _bucket_start and slot != _bucket_start:
            closed = _close_bucket()
        _bucket_start = slot
        for metric in HISTORY_METRICS:
            val = sample.get(metric)
            if val is not None:
                _bucket_open.setdefault(metric, []).append(val)
    return closed


def alert_loop():
    """Background thread: every ALERT_INTERVAL seconds, sample metrics, feed them to
    _step_alerts (persisting to alerts.json whenever the event log changes) and record
    them in the history tiers that back the dashboard graphs. Persisted state is loaded in
    main() before any thread starts - load_alerts() clears the list, so it must not race
    the status loop, which appends downtime episodes to the same list."""
    pending = {m: 0 for m in ALERT_RULES}
    cores = psutil.cpu_count() or 1
    n = 0
    while True:
        time.sleep(ALERT_INTERVAL)
        try:
            sample = _sample_alert_metrics()
        except Exception as exc:
            log(f"[alerts] sample error: {exc}")
            continue
        now = int(time.time())
        try:
            if _history_push(sample, now):   # a 5-minute bucket just closed
                save_history()
            if _step_alerts(sample, now, cores, pending):
                save_alerts()
            n += 1
            if n % HISTORY_LIVE_EVERY == 0:
                save_history_live()
        except Exception as exc:
            log(f"[alerts] loop error: {exc}")


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
    """Check all services and projects in parallel; update _status_cache. Archived
    entries are skipped - they are only listed on the page, never probed."""
    config = load_config()
    services  = [s for s in config.get("services", []) if not s.get("archived")]
    projects  = [p for p in config.get("projects", []) if not p.get("archived")]

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
                log(f"[status] Error checking {item.get('id', '?')}: {exc}")

    # Preserve ordering from config
    svc_order  = {s["id"]: i for i, s in enumerate(services)}
    proj_order = {p["id"]: i for i, p in enumerate(projects)}
    svc_results.sort(key=lambda x: svc_order.get(x["id"], 999))
    proj_results.sort(key=lambda x: proj_order.get(x["id"], 999))

    with _status_lock:
        _status_cache["services"]  = svc_results
        _status_cache["projects"]  = proj_results
        _status_cache["ts"]        = int(time.time())

    # Feed the same results through the outage machine so downtime is logged alongside
    # the metric alerts.
    if _step_downtime(svc_results, int(time.time())):
        save_alerts()


def status_refresh_loop():
    """Background thread: refresh statuses every 30 seconds."""
    while True:
        try:
            refresh_statuses()
        except Exception as exc:
            log(f"[status] refresh error: {exc}")
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


def get_docker_counts():
    """Return (running, total) Docker container counts, or (None, None) if unavailable."""
    def _count(args):
        result = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=5)
        return len([l for l in result.stdout.splitlines() if l.strip()])
    try:
        return _count(["ps", "-q"]), _count(["ps", "-aq"])
    except Exception:
        return None, None


# ── Tailscale + Docker stats (subprocess-heavy → short TTL cache) ────────────────

_ttl_cache = {}          # name -> {"data": ..., "ts": float}
_ttl_lock  = threading.Lock()

def _cached(name, ttl, producer):
    """Return producer()'s result, memoized for `ttl` seconds (per name)."""
    now = time.time()
    with _ttl_lock:
        entry = _ttl_cache.get(name)
        if entry and now - entry["ts"] < ttl:
            return entry["data"]
    data = producer()
    with _ttl_lock:
        _ttl_cache[name] = {"data": data, "ts": now}
    return data


def _get_tailscale_uncached():
    """Parse `tailscale status --json` into a list of real devices (funnel nodes filtered)."""
    try:
        result = subprocess.run(
            [TAILSCALE_BIN, "status", "--json"],
            capture_output=True, text=True, timeout=6,
        )
        data = json.loads(result.stdout)
    except Exception:
        return None

    def entry(node, is_self):
        ips = node.get("TailscaleIPs") or []
        # Prefer the 100.x IPv4 address for display
        ip = next((a for a in ips if a.startswith("100.")), (ips[0] if ips else None))
        return {
            "name":      node.get("HostName") or node.get("DNSName", "").split(".")[0] or "?",
            "os":        node.get("OS", ""),
            "online":    bool(node.get("Online")),
            "ip":        ip,
            "last_seen": node.get("LastSeen"),
            "is_self":   is_self,
        }

    devices = []
    self_node = data.get("Self")
    if self_node and self_node.get("OS"):
        devices.append(entry(self_node, True))
    for node in (data.get("Peer") or {}).values():
        # Real devices report an OS; funnel-ingress-node peers do not.
        if node.get("OS"):
            devices.append(entry(node, False))

    # self first, then online before offline, then by name
    devices.sort(key=lambda d: (not d["is_self"], not d["online"], d["name"].lower()))
    return devices


def get_tailscale():
    return _cached("tailscale", 15, _get_tailscale_uncached)


def _get_docker_stats_uncached():
    """Per-container CPU/MEM via `docker stats --no-stream`. None if Docker is unavailable."""
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
    except Exception:
        return None

    containers = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            c = json.loads(line)
        except ValueError:
            continue

        def pct(v):
            try:
                return round(float(str(v).replace("%", "").strip()), 1)
            except ValueError:
                return None

        containers.append({
            "name":    c.get("Name", "?"),
            "cpu_pct": pct(c.get("CPUPerc")),
            "mem_pct": pct(c.get("MemPerc")),
            "mem":     c.get("MemUsage", ""),
        })
    containers.sort(key=lambda x: (x["cpu_pct"] is None, -(x["cpu_pct"] or 0)))
    return containers


def get_docker_stats():
    return _cached("docker_stats", 12, _get_docker_stats_uncached)


# Internal APFS plumbing / recovery to hide from the per-volume breakdown.
_HIDDEN_VOLUMES = {"/Volumes/Recovery"}
# Real user-facing filesystems (skip devfs/nullfs/autofs and other pseudo mounts).
_REAL_FSTYPES   = {"apfs", "hfs", "hfsplus", "exfat", "msdos", "ntfs", "ufsd_ntfs"}

def _volume_entry(name, mount, internal):
    u = psutil.disk_usage(mount)
    return {
        "name":     name,
        "mount":    mount,
        "used_gb":  round(u.used  / 1024**3, 1),
        "total_gb": round(u.total / 1024**3, 1),
        "percent":  round(u.percent, 1),
        "internal": internal,
    }

def get_disk_volumes():
    """
    Per-volume disk usage: the internal data volume plus any external drives
    mounted under /Volumes. Skips the sealed system volumes and APFS plumbing.
    """
    vols = []

    # Internal data volume ("/" is the sealed read-only snapshot, so prefer Data)
    for mount in ("/System/Volumes/Data", "/"):
        try:
            vols.append(_volume_entry("Macintosh HD", mount, True))
            break
        except Exception:
            continue

    # External / other real volumes mounted under /Volumes
    try:
        for p in psutil.disk_partitions(all=False):
            mp = p.mountpoint
            if not mp.startswith("/Volumes/") or mp in _HIDDEN_VOLUMES:
                continue
            if p.fstype.lower() not in _REAL_FSTYPES:
                continue
            try:
                vols.append(_volume_entry(os.path.basename(mp) or mp, mp, False))
            except Exception:
                continue
    except Exception:
        pass

    return vols


def get_stats():
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # One macmon sample (no sudo), reused below for temp, memory, and current power.
    mac = get_macmon()

    # Memory: prefer macmon (matches Activity Monitor); else psutil with a single
    # consistent formula (used = total - available) so the % and the GB agree.
    GB = 1024**3
    if mac and mac.get("ram_used") and mac.get("ram_total"):
        ram_total_gb = round(mac["ram_total"] / GB, 2)
        ram_used_gb  = round(mac["ram_used"]  / GB, 2)
        ram_pct      = round(mac["ram_used"] / mac["ram_total"] * 100, 1)
        swap_total_b = mac.get("swap_total") or 0
        swap_used_b  = mac.get("swap_used") or 0
        swap_used_gb = round(swap_used_b / GB, 2)
        swap_pct     = round(swap_used_b / swap_total_b * 100, 1) if swap_total_b else 0.0
    else:
        ram_used_b   = ram.total - ram.available
        ram_total_gb = round(ram.total / GB, 2)
        ram_used_gb  = round(ram_used_b / GB, 2)
        ram_pct      = round(ram_used_b / ram.total * 100, 1)
        swap_used_gb = round(swap.used / GB, 2)
        swap_pct     = round(swap.percent, 1)

    # On macOS, "/" is the sealed read-only system snapshot (~26% used); the real
    # user data lives on the Data volume. Fall back to "/" on Intel / non-APFS.
    try:
        disk = psutil.disk_usage("/System/Volumes/Data")
    except Exception:
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

    # CPU frequency. psutil reports a meaningless constant on Apple Silicon (4 "MHz"
    # on macOS 27), so prefer macmon's performance-cluster frequency.
    cpu_freq = None
    if mac and mac.get("pcpu_mhz"):
        cpu_freq = round(mac["pcpu_mhz"] / 1000, 2)  # GHz
    else:
        try:
            freq = psutil.cpu_freq()
            if freq and freq.current >= 100:
                cpu_freq = round(freq.current / 1000, 2)  # GHz
        except Exception:
            pass

    # Temperature - macmon gives real CPU/GPU temp on Apple Silicon (no sudo).
    # Only if macmon is unavailable, fall back to osx-cpu-temp / powermetrics /
    # psutil for temp plus the thermal-pressure level.
    gpu_temp = None
    if mac and mac.get("cpu_temp") is not None:
        temp = round(mac["cpu_temp"], 1)
        gpu_temp = round(mac["gpu_temp"], 1) if mac.get("gpu_temp") is not None else None
        thermal_pressure = None
    else:
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
        # Thermal pressure - works on Apple Silicon M4 even when temp is None
        thermal_pressure = get_thermal_pressure()

    # Load average + core count
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = None
    cpu_cores = psutil.cpu_count()

    # Cumulative network totals since boot (reuse net_after, no extra syscall)
    net_total_up_gb   = round(net_after.bytes_sent / 1024**3, 2)
    net_total_down_gb = round(net_after.bytes_recv / 1024**3, 2)

    # Docker container counts (None if Docker isn't running)
    docker_running, docker_total = get_docker_counts()

    # Per-volume disk breakdown (internal + external drives)
    volumes = get_disk_volumes()

    # Energy snapshot (accumulated by energy_loop); prefer the fresh macmon
    # sys_power reading for the displayed current power when available.
    with _energy_lock:
        power_w      = _energy["power_w"]
        energy_wh    = round(_energy["total_wh"], 1)
        energy_since = _energy["since"]
    if mac and mac.get("sys_power") is not None:
        power_w = round(mac["sys_power"], 2)

    return {
        "cpu":          round(cpu, 1),
        "ram":          ram_pct,
        "ram_used_gb":  ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "swap":         swap_pct,
        "swap_used_gb": swap_used_gb,
        "disk":         round(disk.percent, 1),
        "disk_used_gb": round(disk.used  / 1024**3, 1),
        "disk_total_gb":round(disk.total / 1024**3, 1),
        "disk_read_mbs": disk_r,
        "disk_write_mbs":disk_w,
        "uptime":       uptime_seconds,
        "net_tx":       net_tx,
        "net_rx":       net_rx,
        "temp":         temp,
        "gpu_temp":     gpu_temp,
        "thermal_pressure": thermal_pressure,
        "cpu_freq_ghz": cpu_freq,
        "load_1":       round(load1, 2)  if load1  is not None else None,
        "load_5":       round(load5, 2)  if load5  is not None else None,
        "load_15":      round(load15, 2) if load15 is not None else None,
        "cpu_cores":    cpu_cores,
        "net_total_up_gb":   net_total_up_gb,
        "net_total_down_gb": net_total_down_gb,
        "docker_running": docker_running,
        "docker_total":   docker_total,
        "volumes":      volumes,
        "power_w":      power_w,
        "energy_wh":    energy_wh,
        "energy_since": energy_since,
    }


def get_logs(service_key, lines=50, container=None):
    config = load_config()
    svc = next((s for s in config.get("services", []) if s["id"] == service_key), None)
    if not svc:
        return {"error": f"Unknown service: {service_key}"}

    raw_lines = []

    # `container` param overrides the service's default docker container name
    docker_name = container or svc.get("docker")

    # Try Docker first
    if docker_name:
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(lines), "--timestamps", docker_name],
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


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def parse_log_line(line):
    """
    Attempt to extract timestamp, level, and message from a log line.
    Handles Docker timestamped format and plain text logs.
    """
    line = ANSI_RE.sub("", line).strip()   # Immich v3 colours its output
    if not line:
        return None

    # Docker timestamp format: 2024-01-15T14:23:01.123456789Z  rest of log
    if len(line) > 30 and line[10] == "T" and "Z" in line[:35]:
        parts = line.split(" ", 1)
        ts_str = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        # Docker timestamps are UTC - show HH:MM:SS in the server's local time
        try:
            utc = calendar.timegm(time.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S"))
            ts_part = time.strftime("%H:%M:%S", time.localtime(utc))
        except ValueError:
            ts_part = ts_str.split("T")[1][:8] if "T" in ts_str else "??:??:??"
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
        log(f"[{self.log_date_time_string()}] {self.address_string()} - {fmt % args}")

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

        elif path == "/api/tailscale":
            try:
                json_response(self, {"devices": get_tailscale() or [], "ts": int(time.time())})
            except Exception as e:
                json_response(self, {"error": str(e)}, 500)

        elif path == "/api/docker":
            try:
                json_response(self, {"containers": get_docker_stats() or [], "ts": int(time.time())})
            except Exception as e:
                json_response(self, {"error": str(e)}, 500)

        elif path == "/api/alerts":
            try:
                limit = int(qs.get("limit", ["100"])[0])
                limit = max(1, min(limit, ALERT_MAX))
                with _alerts_lock:
                    events = list(reversed(_alerts[-limit:]))  # newest first
                json_response(self, {"events": events, "rules": ALERT_RULES, "ts": int(time.time())})
            except Exception as e:
                json_response(self, {"error": str(e)}, 500)

        elif path == "/api/history":
            try:
                minutes = int(qs.get("minutes", ["30"])[0])
                minutes = max(1, min(minutes, BUCKET_MAX * BUCKET_SECONDS // 60))
                cutoff = int(time.time()) - minutes * 60
                # Short windows get full-resolution samples; longer ones get the
                # persisted 5-minute min/avg/max buckets, which have a different point
                # shape - hence "res" so the client knows what it is drawing.
                if qs.get("host", [""])[0] == "laptop":
                    points, res, interval = LAPTOP.history(minutes, BUCKET_FINE_MAX)
                elif minutes <= BUCKET_FINE_MAX:
                    with _history_lock:
                        points = [p for p in _history if p["t"] >= cutoff]
                    res, interval = "fine", ALERT_INTERVAL
                else:
                    with _history_lock:
                        points = [b for b in _buckets if b["t"] >= cutoff]
                    res, interval = "bucket", BUCKET_SECONDS
                if res == "bucket":
                    # Optional coarser buckets: a whole multiple of BUCKET_SECONDS, max 1 day.
                    step = int(qs.get("step", [str(BUCKET_SECONDS)])[0])
                    step = max(1, min(step // BUCKET_SECONDS, 288)) * BUCKET_SECONDS
                    if step > BUCKET_SECONDS:
                        points, interval = _coarsen(points, step), step
                json_response(self, {
                    "points": points, "res": res, "interval": interval,
                    "minutes": minutes, "ts": int(time.time()),
                })
            except Exception as e:
                json_response(self, {"error": str(e)}, 500)

        elif path == "/api/laptop":
            json_response(self, LAPTOP.status())

        elif path == "/api/laptop/apps":
            try:
                minutes = max(60, min(int(qs.get("minutes", ["1440"])[0]), 10080))
                json_response(self, LAPTOP.apps(minutes))
            except ValueError:
                json_response(self, {"error": "minutes must be an integer"}, 400)

        elif path == "/api/logs":
            service = qs.get("service", ["immich"])[0]
            container = qs.get("container", [None])[0]
            lines = int(qs.get("lines", ["50"])[0])
            lines = max(1, min(lines, 500))  # clamp 1-500
            try:
                data = get_logs(service, lines, container=container)
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

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        if path != "/api/laptop/push":
            json_response(self, {"error": "Not found"}, 404)
            return
        if not secrets.compare_digest(self.headers.get("X-Push-Token", "").encode(), LAPTOP.token.encode()):
            json_response(self, {"error": "Unauthorized"}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 4 * 1024 * 1024:
                json_response(self, {"error": "Bad length"}, 413)
                return
            ok, msg = LAPTOP.ingest(json.loads(self.rfile.read(length).decode("utf-8")))
            json_response(self, {"ok": ok, "message": msg}, 200 if ok else 400)
        except (json.JSONDecodeError, ValueError) as e:
            json_response(self, {"error": f"Bad JSON: {e}"}, 400)
        except Exception as e:
            log(f"[laptop] push error: {e}")
            json_response(self, {"error": str(e)}, 500)

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
    # Threaded: /api/stats and /api/docker take ~2 s each, and served one at a time
    # they queued past the page's 5 s timeout, so the Mac flickered "offline".
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True

    print(f"Mac Mini Stats API running on port {PORT} (plain HTTP - TLS handled by Tailscale Funnel)")
    print(f"  API token:   {API_TOKEN}")
    print(f"  Write token: {WRITE_TOKEN}")
    print(f"  Local:    http://{TAILSCALE_HOSTNAME}:{PORT}/api/stats?token={API_TOKEN}")
    print(f"")
    print(f"  Public URL (via Tailscale Funnel on :{FUNNEL_PORT}):")
    print(f"  https://{TAILSCALE_HOSTNAME}:{FUNNEL_PORT}/api/stats?token={API_TOKEN}")
    print("Press Ctrl+C to stop.")

    # Restore persisted event log + metric history before any thread can touch them.
    load_alerts()
    load_history()
    LAPTOP = Laptop(os.path.dirname(CONFIG_FILE), log)

    # Initial status check + background refresh loop
    print("[status] Running initial status check...")
    threading.Thread(target=refresh_statuses, daemon=True).start()
    threading.Thread(target=status_refresh_loop, daemon=True).start()
    threading.Thread(target=energy_loop, daemon=True).start()
    threading.Thread(target=alert_loop, daemon=True).start()

    # AdminPanel and `kill` stop us with SIGTERM - route it through the same path as
    # Ctrl-C so the history and open episodes are written before exiting.
    def _on_sigterm(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("\nStopped.")
    finally:
        save_history_live()
        save_history()
        save_alerts()
        LAPTOP.save_all()
