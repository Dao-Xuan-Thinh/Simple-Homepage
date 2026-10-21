"""Homepage laptop agent - samples this Windows laptop and pushes to the Mac's stats API.

Runs windowless (pythonw) from a Task Scheduler task at logon. Built to cost next to
nothing on battery:
  - one sample per TICK_AC / TICK_BATTERY seconds, sleeping in between (no polling loops)
  - the per-app scan reuses the same tick and costs ~15 ms of CPU
  - samples are pushed in batches (PUSH_EVERY ticks), so the radio wakes once a minute
    or two, not on every sample; failed pushes are queued and retried with the next one
  - the process asks Windows for EcoQoS (efficiency mode) and below-normal priority

Reads config from agent.json next to this file: {"url": ".../api/laptop/push", "token": "..."}.
Logs errors (not samples) to agent.log next to this file, capped at LOG_MAX bytes.
"""
import ctypes
import http.client
import json
import os
import platform
import socket
import ssl
import struct
import sys
import time
import urllib.parse
import urllib.request
from ctypes import wintypes

import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "agent.json")
LOG_FILE = os.path.join(HERE, "agent.log")
LOG_MAX = 512 * 1024

TICK_AC = 30          # seconds between samples on AC power
TICK_BATTERY = 60     # ... and on battery
PUSH_EVERY = 2        # samples per push (so 60 s on AC, 120 s on battery)
QUEUE_MAX = 480       # unsent samples kept while the Mac is unreachable (4-8 h)
TOP_N = 10            # apps sent per scan, by CPU and by RAM (union)
# Kernel bookkeeping that the snapshot lists as processes but that isn't an app
# (the compressed-memory store alone reads as ~750 MB).
NOT_APPS = {"Memory Compression", "Secure System", "Registry"}
PUSH_TIMEOUT = 15
VERSION = 1


def log(msg):
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > LOG_MAX:
            os.replace(LOG_FILE, LOG_FILE + ".1")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


# ── Windows helpers (ctypes, no extra packages) ────────────────────────────────

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
pdh = ctypes.WinDLL("pdh")
ntdll = ctypes.WinDLL("ntdll")
_H, _P, _D = wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD
# Explicit signatures: without them ctypes passes 64-bit handles as 32-bit ints.
for fn, res, args in [
    (kernel32.CreateMutexW, _H, [_P, wintypes.BOOL, wintypes.LPCWSTR]),
    (kernel32.GetCurrentProcess, _H, []),
    (kernel32.SetProcessInformation, wintypes.BOOL, [_H, ctypes.c_int, _P, _D]),
    (kernel32.SetPriorityClass, wintypes.BOOL, [_H, _D]),
    (kernel32.CreateFileW, _H, [wintypes.LPCWSTR, _D, _D, _P, _D, _D, _H]),
    (kernel32.DeviceIoControl, wintypes.BOOL, [_H, _D, _P, _D, _P, _D, _P, _P]),
    (kernel32.CloseHandle, wintypes.BOOL, [_H]),
    (setupapi.SetupDiGetClassDevsW, _H, [_P, wintypes.LPCWSTR, wintypes.HWND, _D]),
    (setupapi.SetupDiEnumDeviceInterfaces, wintypes.BOOL, [_H, _P, _P, _D, _P]),
    (setupapi.SetupDiGetDeviceInterfaceDetailW, wintypes.BOOL, [_H, _P, _P, _D, _P, _P]),
    (setupapi.SetupDiDestroyDeviceInfoList, wintypes.BOOL, [_H]),
    (pdh.PdhOpenQueryW, _D, [wintypes.LPCWSTR, ctypes.c_size_t, _P]),
    (pdh.PdhAddEnglishCounterW, _D, [_H, wintypes.LPCWSTR, ctypes.c_size_t, _P]),
    (pdh.PdhCollectQueryData, _D, [_H]),
    (pdh.PdhGetFormattedCounterArrayW, _D, [_H, _D, _P, _P, _P]),
    (ntdll.NtQuerySystemInformation, ctypes.c_long, [ctypes.c_ulong, _P, ctypes.c_ulong, _P]),
]:
    fn.restype, fn.argtypes = res, args
INVALID = wintypes.HANDLE(-1).value


def single_instance():
    """Named mutex so a second copy (task re-run, manual start) exits immediately."""
    handle = kernel32.CreateMutexW(None, False, "Local\\HomepageLaptopAgent")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)
    return handle  # kept referenced for the life of the process


def go_efficient():
    """EcoQoS: Windows runs us on efficient cores at low clocks. Plus below-normal priority."""
    class THROTTLE(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG),
                    ("StateMask", wintypes.ULONG)]
    state = THROTTLE(1, 1, 1)  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED on
    proc = kernel32.GetCurrentProcess()
    kernel32.SetProcessInformation(proc, 4, ctypes.byref(state), ctypes.sizeof(state))
    kernel32.SetPriorityClass(proc, 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS


class Battery:
    """Charge/discharge rate in mW straight from the battery driver (IOCTL), which
    psutil does not expose. The device handle is opened once and reused."""

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD),
                    ("d4", ctypes.c_ubyte * 8)]

    class IFACE(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("guid", ctypes.c_byte * 16),
                    ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]

    class WAIT(ctypes.Structure):
        _fields_ = [("Tag", wintypes.ULONG), ("Timeout", wintypes.ULONG),
                    ("PowerState", wintypes.ULONG), ("Low", wintypes.ULONG),
                    ("High", wintypes.ULONG)]

    class STATUS(ctypes.Structure):
        _fields_ = [("PowerState", wintypes.ULONG), ("Capacity", wintypes.ULONG),
                    ("Voltage", wintypes.ULONG), ("Rate", wintypes.LONG)]

    def __init__(self):
        self.handle = None
        self.tag = 0

    def _open(self):
        guid = self.GUID(0x72631E54, 0x78A4, 0x11D0,
                         (ctypes.c_ubyte * 8)(0xBC, 0xF7, 0x00, 0xAA, 0x00, 0xB7, 0xB3, 0x2A))
        devs = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, 0x12)
        if devs in (None, INVALID):
            return False
        try:
            iface = self.IFACE()
            iface.cbSize = ctypes.sizeof(self.IFACE)
            if not setupapi.SetupDiEnumDeviceInterfaces(devs, None, ctypes.byref(guid), 0,
                                                        ctypes.byref(iface)):
                return False
            need = wintypes.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(iface), None, 0,
                                                      ctypes.byref(need), None)
            if not need.value:
                return False
            buf = ctypes.create_string_buffer(need.value)
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8  # cbSize on x64
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(iface), buf,
                                                             need.value, None, None):
                return False
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
        finally:
            setupapi.SetupDiDestroyDeviceInfoList(devs)

        h = kernel32.CreateFileW(path, 0xC0000000, 3, None, 3, 0x80, None)
        if h in (None, INVALID):
            return False
        tag, wait, got = wintypes.ULONG(), wintypes.ULONG(0), wintypes.DWORD()
        if not kernel32.DeviceIoControl(h, 0x294040, ctypes.byref(wait), 4, ctypes.byref(tag), 4,
                                        ctypes.byref(got), None) or not tag.value:
            kernel32.CloseHandle(h)
            return False
        self.handle, self.tag = h, tag.value
        return True

    def rate_w(self):
        """Signed watts: negative while discharging, positive while charging, None if unknown."""
        for _ in range(2):  # a stale tag (battery re-enumerated) gets one reopen
            if self.handle is None and not self._open():
                return None
            wait, st, got = self.WAIT(self.tag, 0, 0, 0, 0), self.STATUS(), wintypes.DWORD()
            if kernel32.DeviceIoControl(self.handle, 0x29404C, ctypes.byref(wait),
                                        ctypes.sizeof(wait), ctypes.byref(st),
                                        ctypes.sizeof(st), ctypes.byref(got), None):
                if st.Rate == -0x80000000:  # BATTERY_UNKNOWN_RATE
                    return None
                return round(st.Rate / 1000, 2)
            kernel32.CloseHandle(self.handle)
            self.handle = None
        return None


class Thermal:
    """Hottest ACPI thermal zone via the PDH perf counter (no admin, no WMI process)."""
    COUNTER = r"\Thermal Zone Information(*)\High Precision Temperature"

    class ITEM(ctypes.Structure):
        _fields_ = [("name", wintypes.LPWSTR), ("status", wintypes.DWORD),
                    ("value", ctypes.c_double)]

    def __init__(self):
        self.pdh = pdh
        self.query, self.counter = wintypes.HANDLE(), wintypes.HANDLE()
        self.ok = (self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query)) == 0 and
                   self.pdh.PdhAddEnglishCounterW(self.query, self.COUNTER, 0,
                                                  ctypes.byref(self.counter)) == 0)

    def read_c(self):
        if not self.ok or self.pdh.PdhCollectQueryData(self.query) != 0:
            return None
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        self.pdh.PdhGetFormattedCounterArrayW(self.counter, 0x200, ctypes.byref(size),
                                              ctypes.byref(count), None)
        if not size.value:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if self.pdh.PdhGetFormattedCounterArrayW(self.counter, 0x200, ctypes.byref(size),
                                                 ctypes.byref(count), buf) != 0:
            return None
        items = ctypes.cast(buf, ctypes.POINTER(self.ITEM))
        temps = [items[i].value / 10 - 273.15 for i in range(count.value) if items[i].status == 0]
        temps = [t for t in temps if 0 < t < 125]
        return round(max(temps), 1) if temps else None


def process_snapshot(state={"buf": None}):
    """Every process's (pid, name, cpu seconds, private working set bytes) from ONE
    NtQuerySystemInformation(SystemProcessInformation) call. psutil instead opens each
    process; a non-elevated agent can't open ~100 system ones, and for each of those
    psutil falls back to a whole-system query, so a scan cost ~1 s of CPU instead of
    a few ms. The private working set is Task Manager's "Memory" column."""
    buf = state["buf"]
    while True:
        if buf is None:
            buf = ctypes.create_string_buffer(1 << 20)
        need = ctypes.c_ulong()
        status = ntdll.NtQuerySystemInformation(5, buf, len(buf), ctypes.byref(need))
        if status == -0x3FFFFFFC:  # STATUS_INFO_LENGTH_MISMATCH: grow (kept for next time)
            buf = ctypes.create_string_buffer(max(need.value + 65536, len(buf) * 2))
            continue
        if status != 0:
            raise OSError(f"NtQuerySystemInformation status {status & 0xFFFFFFFF:#x}")
        break
    state["buf"] = buf
    raw, base, off, out = buf.raw, ctypes.addressof(buf), 0, []
    while True:
        # SYSTEM_PROCESS_INFORMATION (x64): NextEntryOffset @0, WorkingSetPrivateSize @8,
        # UserTime @40, KernelTime @48, ImageName {Length @56, Buffer @64}, PID @80.
        nxt, = struct.unpack_from("<I", raw, off)
        ws_private, = struct.unpack_from("<q", raw, off + 8)
        user, kernel = struct.unpack_from("<qq", raw, off + 40)
        name_len, = struct.unpack_from("<H", raw, off + 56)
        name_ptr, = struct.unpack_from("<Q", raw, off + 64)
        pid, = struct.unpack_from("<Q", raw, off + 80)
        if pid and name_ptr and name_len:
            name = raw[name_ptr - base:name_ptr - base + name_len].decode("utf-16-le", "replace")
            out.append((pid, name, (user + kernel) / 1e7, ws_private))
        if not nxt:
            return out
        off += nxt


def cpu_name():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
    except OSError:
        return platform.processor()


# ── Sampling ──────────────────────────────────────────────────────────────────

class Sampler:
    def __init__(self):
        self.battery = Battery()
        self.thermal = Thermal()
        self.ncpu = psutil.cpu_count() or 1
        self.last_t = None
        self.last_net = None
        self.last_proc = {}   # pid -> (name, cpu seconds)
        psutil.cpu_percent(None)

    def _apps(self, elapsed):
        """CPU% (of the whole machine) and private working set per app name, summed over
        all of an app's processes, from the change in CPU time since the last scan."""
        apps, seen = {}, {}
        for pid, name, cpu_s, mem in process_snapshot():
            if name in NOT_APPS:
                continue
            if name.lower().endswith(".exe"):
                name = name[:-4]
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
        # After sleep/hibernate the deltas span the whole nap - start over instead.
        fresh = self.last_t is not None and now - self.last_t <= tick * 3
        elapsed = now - self.last_t if fresh else 0
        self.last_t = now

        s = {"t": now}
        cpu = psutil.cpu_percent(None)
        if fresh:
            s["cpu"] = round(cpu, 1)
        vm = psutil.virtual_memory()
        s["ram"] = round(vm.percent, 1)
        s["ram_used_gb"] = round((vm.total - vm.available) / 1073741824, 2)
        try:
            s["swap"] = round(psutil.swap_memory().percent, 1)
        except Exception:
            pass
        try:
            s["disk"] = round(psutil.disk_usage("C:\\").percent, 1)
        except OSError:
            pass

        net = psutil.net_io_counters()
        if fresh and self.last_net and elapsed > 0:
            s["net_rx"] = round(max(0, net.bytes_recv - self.last_net.bytes_recv) / 1024 / elapsed, 1)
            s["net_tx"] = round(max(0, net.bytes_sent - self.last_net.bytes_sent) / 1024 / elapsed, 1)
        self.last_net = net

        bat = psutil.sensors_battery()
        if bat:
            s["battery"] = round(bat.percent, 1)
            s["plugged"] = 1 if bat.power_plugged else 0
            if not bat.power_plugged and bat.secsleft not in (psutil.POWER_TIME_UNKNOWN,
                                                              psutil.POWER_TIME_UNLIMITED):
                s["secsleft"] = int(bat.secsleft)
        rate = self.battery.rate_w()
        if rate is not None:
            if rate < 0:
                s["power"] = -rate        # battery drain (W) - the number that matters
            elif rate > 0:
                s["charge"] = rate        # charging rate (W); AC draw itself isn't visible
        temp = self.thermal.read_c()
        if temp is not None:
            s["temp"] = temp

        apps = self._apps(elapsed)
        return s, ({"t": now, "dt": elapsed, "top": apps} if apps else None)


def info():
    vols = []
    for part in psutil.disk_partitions(all=False):
        if "fixed" not in part.opts:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        vols.append({"name": part.mountpoint.rstrip("\\"), "percent": round(u.percent, 1),
                     "free_gb": round(u.free / 1073741824, 1),
                     "total_gb": round(u.total / 1073741824, 1)})
    vm = psutil.virtual_memory()
    return {
        "hostname": socket.gethostname(),
        "os": f"Windows {platform.release()} ({platform.version()})",
        "cpu_model": cpu_name(),
        "cpu_threads": psutil.cpu_count(),
        "cpu_cores": psutil.cpu_count(logical=False),
        "ram_total_gb": round(vm.total / 1073741824, 1),
        "boot_time": int(psutil.boot_time()),
        "volumes": vols,
        "agent_version": VERSION,
    }


# ── Push ──────────────────────────────────────────────────────────────────────

def _tls_context():
    """Classic key-exchange groups only. OpenSSL 3.5 (Python 3.14) adds a post-quantum key
    share that makes the ClientHello larger than one packet, which is exactly what the
    tailnet path below loses; keeping it small makes the fallback route usable too."""
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


# Over Tailscale, packets from this laptop to the Mac that are close to full size get
# dropped when the laptop's own traffic runs through Cloudflare WARP (WireGuard inside
# WARP no longer fits its MTU), so any upload over ~1.2 KB stalls and resets. MagicDNS
# always answers with the tailnet IP, so the agent looks up the Funnel's *public*
# addresses itself and posts there - plain internet TCP, which copes with a small MTU.
# The tailnet route stays as the fallback.
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
    _mutex = single_instance()  # noqa: F841 - held until exit
    go_efficient()
    sampler = Sampler()
    samples, apps, n = [], [], 0
    failures = 0
    log(f"started, pid {os.getpid()}")
    while True:
        bat = psutil.sensors_battery()
        tick = TICK_BATTERY if bat and not bat.power_plugged else TICK_AC
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
                if failures in (1, 10) or failures % 100 == 0:  # don't fill the log while offline
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
        try:
            main()
        except Exception as exc:
            log(f"fatal: {exc!r}")
            raise
