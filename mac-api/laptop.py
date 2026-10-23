"""Laptop telemetry store for the stats API.

The Windows laptop runs laptop-agent/agent.py, which POSTs batches of samples to
/api/laptop/push. This module keeps them in the same two tiers as the Mac's own
history (a fine ring + 5-minute min/avg/max buckets for 7 days) and an hourly log of
which apps used the most CPU and RAM. The laptop sleeps and travels, so every
timestamp comes from the laptop and gaps are normal.

Files (next to config.json, all written atomically):
  laptop-live.json     fine ring, open bucket, latest info/sample/apps - every push
  laptop-history.json  closed 5-minute buckets - whenever one closes
  laptop-apps.json     hourly per-app totals - whenever an hour closes, and on stop
  laptop-token.txt     push token, created on first start (the agent's agent.json holds a copy)
"""
import collections
import json
import os
import secrets
import threading
import time

FINE_MAX = 240           # fine samples kept (2 h at 30 s, 4 h at 60 s)
BUCKET_SECONDS = 300
BUCKET_MAX = 2016        # 7 days
HOUR_MAX = 168           # hourly app records kept (7 days)
APPS_PER_HOUR = 40       # app names kept per hour (the rest are noise)
ONLINE_GRACE = 300       # seconds since the last push before the laptop counts as offline

METRICS = ["cpu", "ram", "swap", "disk", "temp", "battery", "power", "charge", "net_rx", "net_tx"]
EXTRA = ["ram_used_gb", "plugged", "secsleft"]   # kept on fine samples only, not bucketed


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v  # not NaN


def _write_json(path, data, log):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception as exc:
        log(f"[laptop] Failed to save {path}: {exc}")


class Laptop:
    def __init__(self, base_dir, log=print):
        self.log = log
        self.live_file = os.path.join(base_dir, "laptop-live.json")
        self.history_file = os.path.join(base_dir, "laptop-history.json")
        self.apps_file = os.path.join(base_dir, "laptop-apps.json")
        self.token = self._load_token(os.path.join(base_dir, "laptop-token.txt"))
        self.lock = threading.Lock()
        self.fine = collections.deque(maxlen=FINE_MAX)
        self.buckets = collections.deque(maxlen=BUCKET_MAX)
        self.open = {}           # metric -> values in the bucket filling
        self.open_start = 0
        self.hours = {}          # hour epoch (str) -> {app: [cpu_pct_seconds, ram_mb_seconds, ram_max, seconds]}
        self.hour_seconds = {}   # hour epoch (str) -> seconds the laptop was observed in that hour
        self.info = {}
        self.apps_now = None     # latest scan {"t", "dt", "top"}
        self.last_push = 0
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load_token(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                tok = f.read().strip()
            if tok:
                return tok
        except FileNotFoundError:
            pass
        tok = secrets.token_hex(24)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(tok + "\n")
        self.log(f"[laptop] Created push token in {path}")
        return tok

    def _read(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as exc:
            self.log(f"[laptop] Failed to load {path}: {exc}")
            return None

    def _load(self):
        cutoff = int(time.time()) - BUCKET_MAX * BUCKET_SECONDS
        hist = self._read(self.history_file) or {}
        self.buckets.extend(b for b in hist.get("buckets", []) if isinstance(b, dict) and b.get("t", 0) >= cutoff)
        live = self._read(self.live_file) or {}
        self.fine.extend(p for p in live.get("fine", []) if isinstance(p, dict))
        if live.get("open_start") and isinstance(live.get("open"), dict):
            self.open, self.open_start = live["open"], live["open_start"]
        self.info = live.get("info") or {}
        self.apps_now = live.get("apps_now")
        self.last_push = live.get("last_push", 0)
        apps = self._read(self.apps_file) or {}
        self.hours = apps.get("hours", {})
        self.hour_seconds = apps.get("hour_seconds", {})

    def save_live(self):
        with self.lock:
            data = {"fine": list(self.fine), "open": self.open, "open_start": self.open_start,
                    "info": self.info, "apps_now": self.apps_now, "last_push": self.last_push}
        _write_json(self.live_file, data, self.log)

    def save_history(self):
        with self.lock:
            data = {"buckets": list(self.buckets), "bucket_seconds": BUCKET_SECONDS}
        _write_json(self.history_file, data, self.log)

    def save_apps(self):
        with self.lock:
            data = {"hours": self.hours, "hour_seconds": self.hour_seconds}
        _write_json(self.apps_file, data, self.log)

    def save_all(self):
        self.save_live()
        self.save_history()
        self.save_apps()

    # ── ingest ───────────────────────────────────────────────────────────────

    def _close_bucket(self):
        if not self.open_start or not self.open:
            self.open = {}
            return False
        agg = {"t": self.open_start}
        for m, vals in self.open.items():
            if vals:
                agg[m] = {"min": round(min(vals), 2), "avg": round(sum(vals) / len(vals), 2),
                          "max": round(max(vals), 2)}
        self.open = {}
        if len(agg) > 1:
            self.buckets.append(agg)
            return True
        return False

    def _add_sample(self, raw, now):
        """Returns True if a bucket closed. Caller holds the lock."""
        t = raw.get("t")
        if not _num(t) or t > now + 120:
            return False
        t = int(t)
        if self.fine and t <= self.fine[-1]["t"]:
            return False      # duplicate / replayed sample
        point = {"t": t}
        for k in METRICS + EXTRA:
            if _num(raw.get(k)):
                point[k] = raw[k]
        self.fine.append(point)
        closed = False
        slot = t - t % BUCKET_SECONDS
        if self.open_start and slot != self.open_start:
            closed = self._close_bucket()
        self.open_start = slot
        for k in METRICS:
            if k in point:
                self.open.setdefault(k, []).append(point[k])
        return closed

    def _add_apps(self, scan):
        """Fold one scan into its hour. Caller holds the lock. Returns True if a new hour began."""
        t, dt, top = scan.get("t"), scan.get("dt"), scan.get("top")
        if not _num(t) or not _num(dt) or dt <= 0 or dt > 600 or not isinstance(top, list):
            return False
        hour = str(int(t) - int(t) % 3600)
        new_hour = hour not in self.hours
        rec = self.hours.setdefault(hour, {})
        self.hour_seconds[hour] = self.hour_seconds.get(hour, 0) + dt
        for row in top[:60]:
            if not isinstance(row, dict) or not isinstance(row.get("n"), str):
                continue
            cpu = row.get("cpu") if _num(row.get("cpu")) else 0
            ram = row.get("ram") if _num(row.get("ram")) else 0
            a = rec.setdefault(row["n"][:64], [0.0, 0.0, 0, 0])
            a[0] = round(a[0] + cpu * dt, 1)
            a[1] = round(a[1] + ram * dt, 1)
            a[2] = max(a[2], ram)
            a[3] += dt
        if new_hour:
            # Trim the hour just finished to its heaviest apps, and drop hours past retention.
            for h, r in self.hours.items():
                if h != hour and len(r) > APPS_PER_HOUR:
                    keep = set(sorted(r, key=lambda n: -r[n][0])[:APPS_PER_HOUR // 2])
                    keep |= set(sorted(r, key=lambda n: -r[n][2])[:APPS_PER_HOUR // 2])
                    self.hours[h] = {n: r[n] for n in keep}
            for h in sorted(self.hours, key=int)[:-HOUR_MAX]:
                self.hours.pop(h, None)
                self.hour_seconds.pop(h, None)
        return new_hour

    def ingest(self, payload):
        """Apply one push. Returns (ok, message)."""
        if not isinstance(payload, dict):
            return False, "payload must be an object"
        samples = payload.get("samples") or []
        scans = payload.get("apps") or []
        if not isinstance(samples, list) or not isinstance(scans, list):
            return False, "samples and apps must be lists"
        now = int(time.time())
        bucket_closed = hour_changed = False
        with self.lock:
            for s in sorted((s for s in samples[:1000] if isinstance(s, dict)),
                            key=lambda s: s.get("t") if _num(s.get("t")) else 0):
                bucket_closed |= self._add_sample(s, now)
            for scan in sorted((s for s in scans[:1000] if isinstance(s, dict) and _num(s.get("t"))),
                               key=lambda s: s["t"]):
                # A push whose reply got lost is re-sent whole; don't count its scans twice.
                if self.apps_now and scan["t"] <= self.apps_now.get("t", 0):
                    continue
                hour_changed |= self._add_apps(scan)
                self.apps_now = {"t": scan["t"], "dt": scan.get("dt"),
                                 "top": [r for r in scan.get("top", []) if isinstance(r, dict)][:60]}
            if isinstance(payload.get("info"), dict):
                self.info = payload["info"]
            self.last_push = now
        if bucket_closed:
            self.save_history()
        if hour_changed:
            self.save_apps()
        self.save_live()
        return True, "ok"

    # ── queries ──────────────────────────────────────────────────────────────

    def status(self, spark_minutes=30):
        now = int(time.time())
        with self.lock:
            cutoff = (self.fine[-1]["t"] if self.fine else now) - spark_minutes * 60
            return {
                "online": bool(self.last_push) and now - self.last_push <= ONLINE_GRACE,
                "last_push": self.last_push or None,
                "last": self.fine[-1] if self.fine else None,
                "info": self.info,
                "apps_now": self.apps_now,
                "spark": [p for p in self.fine if p["t"] >= cutoff],
                "ts": now,
            }

    def history(self, minutes, fine_max_minutes):
        """(points, res, interval) in the same shapes as the Mac's /api/history."""
        cutoff = int(time.time()) - minutes * 60
        with self.lock:
            if minutes <= fine_max_minutes:
                pts = [{k: v for k, v in p.items() if k in METRICS or k == "t"}
                       for p in self.fine if p["t"] >= cutoff]
                return pts, "fine", 30
            return [b for b in self.buckets if b["t"] >= cutoff], "bucket", BUCKET_SECONDS

    def apps(self, minutes, limit=15):
        """Per-app averages over the window, from the hourly records. cpu = average % of the
        whole machine while the laptop was awake, cpu_run = the same while the app was in the
        top list; ram_avg / ram_max in MB."""
        start = int(time.time()) - minutes * 60
        start -= start % 3600
        totals, seconds = {}, 0
        with self.lock:
            for h, rec in self.hours.items():
                if int(h) < start:
                    continue
                seconds += self.hour_seconds.get(h, 0)
                for name, (cpu_s, ram_s, ram_max, secs) in rec.items():
                    a = totals.setdefault(name, [0.0, 0.0, 0, 0])
                    a[0] += cpu_s
                    a[1] += ram_s
                    a[2] = max(a[2], ram_max)
                    a[3] += secs
        rows = [{"n": n, "cpu": round(c / seconds, 2) if seconds else 0,
                 "cpu_run": round(c / s, 2) if s else 0,
                 "ram_avg": round(r / s) if s else 0, "ram_max": m, "seen_s": s}
                for n, (c, r, m, s) in totals.items()]
        keep = {r["n"] for r in sorted(rows, key=lambda r: -r["cpu"])[:limit]}
        keep |= {r["n"] for r in sorted(rows, key=lambda r: -r["ram_avg"])[:limit]}
        rows = [r for r in rows if r["n"] in keep]
        return {"apps": rows, "awake_s": seconds, "minutes": minutes}
