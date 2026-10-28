"""Homepage laptop agent (Linux side) - samples this laptop and pushes to the Mac's stats API.

Same payload as ../agent.py (Windows) and ../macos/agent.c, so it fills the same Laptop
tab; info.os says which OS sent it. Standard library only: everything comes from /proc
and /sys, so there is nothing to pip install.

Runs as a root systemd service (homepage-agent.service) so it can see every process.
Cheap by design:
  - one sample per TICK_AC / TICK_BATTERY seconds, sleeping in between
  - samples are pushed in batches (PUSH_EVERY ticks), failed pushes are queued and retried
  - the unit runs it at idle CPU and IO priority

Reads config from /etc/homepage-agent.json: {"url": ".../api/laptop/push", "token": "..."}.
Errors (not samples) go to stderr, which is the journal: journalctl -u homepage-agent
"""
import http.client
import json
import os
import platform
import re
import socket
import ssl
import sys
import time
import urllib.parse
import urllib.request

CONFIG_FILE = os.environ.get("HOMEPAGE_AGENT_CONFIG", "/etc/homepage-agent.json")

TICK_AC = 30          # seconds between samples on AC power
TICK_BATTERY = 60     # ... and on battery
PUSH_EVERY = 2        # samples per push (so 60 s on AC, 120 s on battery)
QUEUE_MAX = 480       # unsent samples kept while the Mac is unreachable (4-8 h)
TOP_N = 10            # apps sent per scan, by CPU and by RAM (union)
PUSH_TIMEOUT = 15
VERSION = 1

CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")
PF_KTHREAD = 0x00200000
GB = 1073741824


def log(msg):
    try:
        print(msg, file=sys.stderr, flush=True)
    except Exception:
        pass


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def read_num(path):
    v = read(path)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


# ── System readings ───────────────────────────────────────────────────────────

def cpu_times():
    """(busy, total) jiffies from the first line of /proc/stat. iowait counts as idle,
    guest time is already inside user, as psutil does it."""
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:9]]
    total = sum(v)
    return total - v[3] - v[4], total


def meminfo():
    out = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, rest = line.partition(":")
            out[k] = int(rest.split()[0]) * 1024
    return out


def disk_percent(path):
    st = os.statvfs(path)
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    return round(used / (used + avail) * 100, 1) if used + avail else None


def net_bytes():
    """(rx, tx) over physical interfaces only (those with a device behind them), so
    Tailscale, Docker and VPN tunnels don't count the same traffic twice."""
    rx = tx = 0
    with open("/proc/net/dev") as f:
        for line in f.readlines()[2:]:
            name, _, rest = line.partition(":")
            name = name.strip()
            if not os.path.exists(f"/sys/class/net/{name}/device"):
                continue
            v = rest.split()
            rx += int(v[0])
            tx += int(v[8])
    return rx, tx


def power_supplies():
    """(on_ac, battery dir or None). Peripheral batteries (mouse, headset) have scope Device."""
    base = "/sys/class/power_supply"
    on_ac, battery = None, None
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return None, None
    for n in names:
        d = os.path.join(base, n)
        kind = read(d + "/type")
        if kind == "Mains":
            online = read_num(d + "/online")
            if online is not None:
                on_ac = bool(online) or bool(on_ac)
        elif kind == "Battery" and read(d + "/scope") != "Device" and battery is None:
            battery = d
    return on_ac, battery


def battery_reading(d):
    """{battery, status, watts, secsleft}. power_now is in uW; some batteries only report
    current (uA) and voltage (uV)."""
    out = {"battery": read_num(d + "/capacity"), "status": read(d + "/status") or ""}
    pw = read_num(d + "/power_now")
    if pw is None:
        cur, volt = read_num(d + "/current_now"), read_num(d + "/voltage_now")
        if cur is not None and volt is not None:
            pw = cur * volt / 1e6
    out["watts"] = round(abs(pw) / 1e6, 2) if pw else None
    energy = read_num(d + "/energy_now")
    if energy is not None and pw:
        out["secsleft"] = int(energy / abs(pw) * 3600)
    else:
        charge, cur = read_num(d + "/charge_now"), read_num(d + "/current_now")
        if charge is not None and cur:
            out["secsleft"] = int(charge / abs(cur) * 3600)
    return out


def find_temp_sensor():
    """The CPU package sensor: k10temp Tctl on AMD, coretemp on Intel, else None (then
    the hottest ACPI thermal zone is used)."""
    base = "/sys/class/hwmon"
    try:
        for h in sorted(os.listdir(base)):
            name = read(f"{base}/{h}/name")
            if name in ("k10temp", "coretemp", "zenpower"):
                return f"{base}/{h}/temp1_input"
    except OSError:
        pass
    return None


def read_temp(sensor):
    if sensor:
        v = read_num(sensor)
        return round(v / 1000, 1) if v else None
    temps = []
    for i in range(16):
        v = read_num(f"/sys/class/thermal/thermal_zone{i}/temp")
        if v is None:
            break
        if 0 < v / 1000 < 125:
            temps.append(v / 1000)
    return round(max(temps), 1) if temps else None


# ── Processes ─────────────────────────────────────────────────────────────────

# Interpreters and runtimes: the binary says nothing, the script or app it runs does.
RUNTIMES = re.compile(r"^(python[\d.]*|node|java|bash|sh|zsh|fish|perl|ruby|electron\d*|mono|"
                      r"wine.*|.*-preloader)$")


def app_name(pid, comm):
    """Group processes by the program file they run, so browser and Electron helpers
    count toward their app. Cached per pid until the pid is reused (start time changes)."""
    try:
        exe = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
    except OSError:
        return comm
    if exe.endswith(" (deleted)"):
        exe = exe[:-10]
    if not RUNTIMES.match(exe):
        return exe
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return comm
    if exe.startswith("wine") or exe.endswith("-preloader"):
        # Proton/Wine: argv[0] is the Windows program, e.g. Z:\...\Game.exe
        prog = re.split(r"[\\/]", argv[0])[-1] if argv else comm
        return prog[:-4] if prog.lower().endswith(".exe") else prog
    for a in argv[1:]:
        if a.startswith("-"):
            continue
        a = a.rstrip("/")
        if a.endswith(".asar") or a.endswith("/app"):   # Electron: /usr/lib/obsidian/app.asar
            return os.path.basename(os.path.dirname(a)) or comm
        return os.path.basename(a) or comm
    return comm


def process_snapshot(exe_cache):
    """[(pid, name, cpu seconds, private RAM bytes)] for every process. RAM is
    resident - shared from statm, which is RssAnon: the process's own memory."""
    out, live = [], set()
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            with open(f"/proc/{pid}/stat") as f:
                stat = f.read()
            with open(f"/proc/{pid}/statm") as f:
                statm = f.read().split()
        except OSError:
            continue   # exited mid-scan
        # comm is in parentheses and may itself contain spaces or ')'
        lp, rp = stat.index("("), stat.rindex(")")
        comm, fields = stat[lp + 1:rp], stat[rp + 2:].split()
        flags, utime, stime, start = int(fields[6]), int(fields[11]), int(fields[12]), fields[19]
        live.add(pid)
        if flags & PF_KTHREAD:
            name = "kernel"
        else:
            cached = exe_cache.get(pid)
            if cached and cached[0] == start:
                name = cached[1]
            else:
                name = app_name(pid, comm)
                exe_cache[pid] = (start, name)
        mem = (int(statm[1]) - int(statm[2])) * PAGE
        out.append((pid, name, (utime + stime) / CLK_TCK, max(mem, 0)))
    for pid in [p for p in exe_cache if p not in live]:
        del exe_cache[pid]
    return out


# ── Sampling ──────────────────────────────────────────────────────────────────

class Sampler:
    def __init__(self):
        self.ncpu = os.cpu_count() or 1
        self.sensor = find_temp_sensor()
        self.last_t = None
        self.last_cpu = cpu_times()
        self.last_net = None
        self.last_proc = {}   # pid -> (name, cpu seconds)
        self.exe_cache = {}

    def _apps(self, elapsed):
        """CPU% (of the whole machine) and private RAM per app name, summed over all of
        an app's processes, from the change in CPU time since the last scan."""
        apps, seen = {}, {}
        for pid, name, cpu_s, mem in process_snapshot(self.exe_cache):
            seen[pid] = (name, cpu_s)
            a = apps.setdefault(name, [0.0, 0])
            prev = self.last_proc.get(pid)
            if prev and prev[0] == name and elapsed:
                a[0] += max(0.0, cpu_s - prev[1])
            a[1] += mem
        self.last_proc = seen
        if not elapsed:
            return []
        rows = [{"n": n[:64], "cpu": round(c / (elapsed * self.ncpu) * 100, 2),
                 "ram": round(m / 1048576)} for n, (c, m) in apps.items()]
        keep = {r["n"] for r in sorted(rows, key=lambda r: -r["cpu"])[:TOP_N]}
        keep |= {r["n"] for r in sorted(rows, key=lambda r: -r["ram"])[:TOP_N]}
        return [r for r in rows if r["n"] in keep]

    def sample(self, tick):
        now = int(time.time())
        # After suspend the deltas span the whole nap - start over instead.
        fresh = self.last_t is not None and now - self.last_t <= tick * 3
        elapsed = now - self.last_t if fresh else 0
        self.last_t = now

        s = {"t": now}
        busy, total = cpu_times()
        if fresh and total > self.last_cpu[1]:
            s["cpu"] = round((busy - self.last_cpu[0]) / (total - self.last_cpu[1]) * 100, 1)
        self.last_cpu = (busy, total)

        mi = meminfo()
        used = mi["MemTotal"] - mi.get("MemAvailable", mi.get("MemFree", 0))
        s["ram"] = round(used / mi["MemTotal"] * 100, 1)
        s["ram_used_gb"] = round(used / GB, 2)
        if mi.get("SwapTotal"):
            s["swap"] = round((mi["SwapTotal"] - mi["SwapFree"]) / mi["SwapTotal"] * 100, 1)
        try:
            s["disk"] = disk_percent("/")
        except OSError:
            pass

        net = net_bytes()
        if fresh and self.last_net and elapsed > 0:
            s["net_rx"] = round(max(0, net[0] - self.last_net[0]) / 1024 / elapsed, 1)
            s["net_tx"] = round(max(0, net[1] - self.last_net[1]) / 1024 / elapsed, 1)
        self.last_net = net

        on_ac, bat_dir = power_supplies()
        if bat_dir:
            b = battery_reading(bat_dir)
            if b["battery"] is not None:
                s["battery"] = b["battery"]
            discharging = b["status"] == "Discharging"
            plugged = on_ac if on_ac is not None else not discharging
            s["plugged"] = 1 if plugged else 0
            if discharging:
                if b.get("secsleft"):
                    s["secsleft"] = b["secsleft"]
                if b["watts"]:
                    s["power"] = b["watts"]     # battery drain (W) - the number that matters
            elif b["status"] == "Charging" and b["watts"]:
                s["charge"] = b["watts"]        # charging rate (W)
        temp = read_temp(self.sensor)
        if temp is not None:
            s["temp"] = temp

        apps = self._apps(elapsed)
        return s, ({"t": now, "dt": elapsed, "top": apps} if apps else None)


REAL_FS = {"ext4", "ext3", "btrfs", "xfs", "f2fs", "bcachefs", "zfs", "ntfs", "ntfs3",
           "fuseblk", "exfat", "vfat"}


def volumes():
    """One entry per real filesystem. btrfs mounts many subvolumes of one device, so
    each device is listed once, at its shortest mount point."""
    by_dev = {}
    with open("/proc/mounts") as f:
        for line in f:
            dev, mp, fs = line.split()[:3]
            mp = mp.replace("\\040", " ")
            if fs not in REAL_FS or not dev.startswith("/dev/"):
                continue
            if mp.startswith(("/boot", "/efi")):
                continue
            if dev not in by_dev or len(mp) < len(by_dev[dev]):
                by_dev[dev] = mp
    vols = []
    for mp in sorted(by_dev.values()):
        try:
            st = os.statvfs(mp)
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        if not total:
            continue
        free = st.f_bavail * st.f_frsize
        vols.append({"name": mp, "percent": disk_percent(mp),
                     "free_gb": round(free / GB, 1), "total_gb": round(total / GB, 1)})
    return vols


def os_release():
    name = "Linux"
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    name = line.split("=", 1)[1].strip().strip('"') or name
    except OSError:
        pass
    return name


def cpu_info():
    model, cores = platform.processor(), set()
    phys = core = None
    with open("/proc/cpuinfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k == "model name":
                model = v
            elif k == "physical id":
                phys = v
            elif k == "core id":
                core = v
            elif not k and core is not None:
                cores.add((phys, core))
                phys = core = None
    if core is not None:
        cores.add((phys, core))
    return model, len(cores) or None


def boot_time():
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("btime"):
                return int(line.split()[1])
    return None


_static = {}


def info():
    if not _static:
        model, cores = cpu_info()
        # First word is the OS key the server files samples under: "CachyOS" -> "cachyos".
        _static.update({"os": f"{os_release()} (kernel {platform.release()})",
                        "cpu_model": model, "cpu_threads": os.cpu_count(), "cpu_cores": cores,
                        "ram_total_gb": round(meminfo()["MemTotal"] / GB, 1)})
    return {"hostname": socket.gethostname(), **_static, "boot_time": boot_time(),
            "volumes": volumes(), "agent_version": VERSION}


# ── Push (same routes as ../agent.py) ─────────────────────────────────────────

def _tls_context():
    """Classic key-exchange groups only. OpenSSL 3.5 adds a post-quantum key share that
    makes the ClientHello larger than one packet, which is exactly what the tailnet
    path below loses when WARP is on; keeping it small makes the fallback usable too."""
    ctx = ssl.create_default_context()
    try:
        if hasattr(ctx, "set_groups"):
            ctx.set_groups("X25519:P-256")
        else:
            ctx.set_ecdh_curve("prime256v1")
    except (ValueError, ssl.SSLError):
        pass
    return ctx


TLS = _tls_context()

# Over Tailscale, near-full-size packets from this laptop to the Mac get dropped while
# Cloudflare WARP is on, so uploads over ~1.2 KB stall. MagicDNS always answers with
# the tailnet IP, so the agent looks up the Funnel's *public* addresses itself and
# posts there. The tailnet route stays as the fallback.
_dns = {"ips": [], "t": 0}
DNS_TTL = 3600


def _public_ips(host):
    if time.time() - _dns["t"] < DNS_TTL:
        return _dns["ips"]
    url = "https://cloudflare-dns.com/dns-query?" + urllib.parse.urlencode({"name": host, "type": "A"})
    req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=TLS) as r:
            answer = json.load(r).get("Answer", [])
        _dns["ips"] = [a["data"] for a in answer if a.get("type") == 1][:2]
    except Exception as exc:
        log(f"public DNS lookup failed: {exc!r}")
        _dns["ips"] = []
    _dns["t"] = time.time()
    return _dns["ips"]


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a fixed IP while still sending SNI / verifying the cert for the hostname."""
    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def push(cfg, samples, apps):
    body = json.dumps({"samples": samples, "apps": apps, "info": info()},
                      separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "X-Push-Token": cfg["token"]}
    u = urllib.parse.urlsplit(cfg["url"])
    error = None
    for ip in _public_ips(u.hostname) + [None]:   # None = normal resolution (tailnet)
        kw = {"port": u.port or 443, "timeout": PUSH_TIMEOUT, "context": TLS}
        conn = _PinnedHTTPS(u.hostname, ip, **kw) if ip else http.client.HTTPSConnection(u.hostname, **kw)
        try:
            conn.request("POST", u.path, body, headers)
            res = conn.getresponse()
            res.read()
            if res.status == 200:
                return True
            error = RuntimeError(f"HTTP {res.status} via {ip or 'tailnet'}")
            if 400 <= res.status < 500:
                break     # the server answered and refused - another route won't change that
        except OSError as exc:
            error = exc
            if ip:
                _dns["t"] = 0   # look the addresses up again next time
        finally:
            conn.close()
    raise error


def main():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    sampler = Sampler()
    samples, apps, n = [], [], 0
    failures = 0
    log(f"started, pid {os.getpid()}")
    while True:
        on_ac, bat_dir = power_supplies()
        tick = TICK_BATTERY if bat_dir and on_ac is False else TICK_AC
        try:
            s, a = sampler.sample(tick)
            samples.append(s)
            if a:
                apps.append(a)
        except Exception as exc:
            log(f"sample error: {exc!r}")
        n += 1
        if n % PUSH_EVERY == 0 and samples:
            try:
                if push(cfg, samples, apps):
                    samples, apps = [], []
                    if failures:
                        log(f"push ok again after {failures} failures")
                    failures = 0
            except Exception as exc:
                failures += 1
                if failures in (1, 10) or failures % 100 == 0:  # don't flood the journal while offline
                    log(f"push failed ({failures}): {exc!r}")
            del samples[:-QUEUE_MAX]
            del apps[:-QUEUE_MAX]
        time.sleep(tick)


if __name__ == "__main__":
    if "--once" in sys.argv:  # debug: print one sample (two ticks apart) and exit
        smp = Sampler()
        smp.sample(5)
        time.sleep(5)
        s, a = smp.sample(5)
        print(json.dumps({"sample": s, "apps": a, "info": info()}, indent=1))
    else:
        main()
