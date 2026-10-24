// Homepage laptop agent for the G14's macOS (the hackintosh side of the same laptop). Samples the machine and pushes to
// the Mac's stats API (POST /api/laptop/push) in the same format as ../agent.py, so it feeds the same Laptop tab. Only
// one OS runs at a time, so the two agents never push at once.
//
// C instead of Python: that macOS has no Python (the /usr/bin/python3 shim would pop the Command Line Tools installer).
// The push goes through /usr/bin/curl, which reads the URL and the token from the config file (never argv):
//   /usr/local/etc/homepage-agent.conf (0600, root):  url = "https://.../api/laptop/push"
//                                                     header = "X-Push-Token: <token>"
// Runs as a LaunchDaemon (root, so it sees every process for the top-apps list), asleep between ticks.
//   homepage-agent           run (launchd)
//   homepage-agent --once    print one sample (two ticks 5 s apart) as JSON, do not push
// Build: clang -arch x86_64 -mmacosx-version-min=15.0 -O2 -o homepage-agent agent.c -framework IOKit -framework CoreFoundation
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/ps/IOPowerSources.h>
#include <IOKit/ps/IOPSKeys.h>
#include <libproc.h>
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <net/if.h>
#include <net/if_dl.h>
#include <net/route.h>
#include <fcntl.h>
#include <spawn.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define CONF "/usr/local/etc/homepage-agent.conf"
#define LOGF "/var/log/homepage-agent.log"
#define LOG_MAX (512 * 1024)
#define TICK_AC 30          // seconds between samples on AC power
#define TICK_BATTERY 60     // ... and on battery
#define PUSH_EVERY 2        // samples per push
#define QUEUE_MAX 480       // unsent samples kept while the Mac is unreachable
#define TOP_N 10            // apps per scan, by CPU and by RAM (union)
#define VERSION 1

extern char **environ;

static void logmsg(const char *fmt, ...) {
    struct stat st;
    if (stat(LOGF, &st) == 0 && st.st_size > LOG_MAX) rename(LOGF, LOGF ".1");
    FILE *f = fopen(LOGF, "a");
    if (!f) return;
    char ts[32];
    time_t now = time(NULL);
    strftime(ts, sizeof(ts), "%Y-%m-%d %H:%M:%S ", localtime(&now));
    fputs(ts, f);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

// ---- growable string ----

typedef struct { char *p; size_t n, cap; } buf_t;

static void bput(buf_t *b, const char *fmt, ...) {
    va_list ap;
    for (;;) {
        size_t room = b->cap - b->n;
        va_start(ap, fmt);
        int w = vsnprintf(b->p ? b->p + b->n : NULL, b->p ? room : 0, fmt, ap);
        va_end(ap);
        if (w < 0) return;
        if (b->p && (size_t)w < room) { b->n += (size_t)w; return; }
        size_t cap = b->cap ? b->cap * 2 : 4096;
        while (cap - b->n <= (size_t)w) cap *= 2;
        char *p = realloc(b->p, cap);
        if (!p) return;
        b->p = p; b->cap = cap;
    }
}

static void bstr(buf_t *b, const char *s) {           // a JSON string literal
    bput(b, "\"");
    for (; *s; s++) {
        unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') bput(b, "\\%c", c);
        else if (c < 0x20) bput(b, "\\u%04x", c);
        else bput(b, "%c", c);
    }
    bput(b, "\"");
}

// ---- machine facts ----

static double gib(uint64_t v) { return v / 1073741824.0; }

static void sysstr(const char *name, char *out, size_t len) {
    size_t l = len;
    if (sysctlbyname(name, out, &l, NULL, 0) != 0) out[0] = 0;
    out[len - 1] = 0;
    for (char *e = out + strlen(out); e > out && e[-1] == ' '; ) *--e = 0;   // brand string has trailing blanks
}

static int sysint(const char *name) {
    int v = 0;
    size_t l = sizeof(v);
    return sysctlbyname(name, &v, &l, NULL, 0) == 0 ? v : 0;
}

static uint64_t memsize(void) {
    uint64_t v = 0;
    size_t l = sizeof(v);
    sysctlbyname("hw.memsize", &v, &l, NULL, 0);
    return v;
}

// Disk use the way Finder counts it: the Data volume (the sealed system volume is the same container).
static int volume(const char *path, double *pct, double *free_gb, double *total_gb) {
    struct statfs s;
    if (statfs(path, &s) != 0 || !s.f_blocks) return 0;
    double total = (double)s.f_blocks * s.f_bsize, avail = (double)s.f_bavail * s.f_bsize;
    *pct = (total - avail) / total * 100;
    *free_gb = avail / 1073741824.0;
    *total_gb = total / 1073741824.0;
    return 1;
}

static void info_json(buf_t *b) {
    char host[256] = "", cpu[128], ver[64], build[64];
    gethostname(host, sizeof(host));
    sysstr("machdep.cpu.brand_string", cpu, sizeof(cpu));
    sysstr("kern.osproductversion", ver, sizeof(ver));
    sysstr("kern.osversion", build, sizeof(build));
    struct timeval bt = {0};
    size_t l = sizeof(bt);
    sysctlbyname("kern.boottime", &bt, &l, NULL, 0);
    bput(b, "{\"hostname\":");
    bstr(b, host);
    char os[160];
    snprintf(os, sizeof(os), "macOS %s (%s)", ver, build);
    bput(b, ",\"os\":");
    bstr(b, os);
    bput(b, ",\"cpu_model\":");
    bstr(b, cpu);
    bput(b, ",\"cpu_threads\":%d,\"cpu_cores\":%d,\"ram_total_gb\":%.1f,\"boot_time\":%ld,\"volumes\":[",
         sysint("hw.logicalcpu"), sysint("hw.physicalcpu"), gib(memsize()), (long)bt.tv_sec);
    double pct, fr, tot;
    if (volume("/System/Volumes/Data", &pct, &fr, &tot)) {
        bput(b, "{\"name\":\"Macintosh HD\",\"percent\":%.1f,\"free_gb\":%.1f,\"total_gb\":%.1f}", pct, fr, tot);
    }
    bput(b, "],\"agent_version\":%d}", VERSION);
}

// ---- samples ----

typedef struct { uint64_t busy, total; } cpu_t;

static cpu_t cpu_ticks(void) {
    host_cpu_load_info_data_t d;
    mach_msg_type_number_t n = HOST_CPU_LOAD_INFO_COUNT;
    cpu_t c = {0, 0};
    if (host_statistics(mach_host_self(), HOST_CPU_LOAD_INFO, (host_info_t)&d, &n) != KERN_SUCCESS) return c;
    uint64_t idle = d.cpu_ticks[CPU_STATE_IDLE];
    c.total = idle + d.cpu_ticks[CPU_STATE_USER] + d.cpu_ticks[CPU_STATE_SYSTEM] + d.cpu_ticks[CPU_STATE_NICE];
    c.busy = c.total - idle;
    return c;
}

// RAM used as Activity Monitor shows it: app memory + wired + compressed.
static uint64_t ram_used(void) {
    vm_statistics64_data_t v;
    mach_msg_type_number_t n = HOST_VM_INFO64_COUNT;
    if (host_statistics64(mach_host_self(), HOST_VM_INFO64, (host_info64_t)&v, &n) != KERN_SUCCESS) return 0;
    uint64_t app = v.internal_page_count > v.purgeable_count ? v.internal_page_count - v.purgeable_count : 0;
    return (app + v.wire_count + v.compressor_page_count) * (uint64_t)vm_kernel_page_size;
}

// Bytes in/out over the physical interfaces (64-bit counters). Tunnels (utun = Tailscale), loopback and the AWDL /
// bridge pseudo-interfaces are left out so tunnel traffic is not counted twice.
static int net_bytes(uint64_t *rx, uint64_t *tx) {
    int mib[] = { CTL_NET, PF_ROUTE, 0, 0, NET_RT_IFLIST2, 0 };
    size_t len = 0;
    if (sysctl(mib, 6, NULL, &len, NULL, 0) != 0) return 0;
    char *p = malloc(len);
    if (!p || sysctl(mib, 6, p, &len, NULL, 0) != 0) { free(p); return 0; }
    *rx = *tx = 0;
    for (char *c = p; c < p + len; ) {
        struct if_msghdr *h = (struct if_msghdr *)c;
        if (!h->ifm_msglen) break;
        if (h->ifm_type == RTM_IFINFO2) {
            struct if_msghdr2 *h2 = (struct if_msghdr2 *)h;
            struct sockaddr_dl *sdl = (struct sockaddr_dl *)(h2 + 1);
            char name[IFNAMSIZ + 1] = "";
            if (sdl->sdl_nlen && sdl->sdl_nlen <= IFNAMSIZ) memcpy(name, sdl->sdl_data, sdl->sdl_nlen);
            static const char *skip[] = { "lo", "utun", "gif", "stf", "awdl", "llw", "bridge", "ap", "anpi", "ipsec" };
            int keep = name[0] != 0;
            for (size_t i = 0; keep && i < sizeof(skip) / sizeof(skip[0]); i++)
                if (!strncmp(name, skip[i], strlen(skip[i]))) keep = 0;
            if (keep) { *rx += h2->ifm_data.ifi_ibytes; *tx += h2->ifm_data.ifi_obytes; }
        }
        c += h->ifm_msglen;
    }
    free(p);
    return 1;
}

static double swap_pct(void) {
    struct xsw_usage x;
    size_t l = sizeof(x);
    if (sysctlbyname("vm.swapusage", &x, &l, NULL, 0) != 0 || !x.xsu_total) return 0;
    return (double)x.xsu_used / x.xsu_total * 100;
}

typedef struct { int have, plugged; double pct; int secsleft; double watts; } battery_t;

static double cfnum(CFDictionaryRef d, CFStringRef k, int *ok) {
    CFTypeRef v = d ? CFDictionaryGetValue(d, k) : NULL;
    double r = 0;
    *ok = v && CFGetTypeID(v) == CFNumberGetTypeID() && CFNumberGetValue((CFNumberRef)v, kCFNumberDoubleType, &r);
    return r;
}

static battery_t battery(void) {
    battery_t b = {0};
    CFTypeRef blob = IOPSCopyPowerSourcesInfo();
    CFArrayRef list = blob ? IOPSCopyPowerSourcesList(blob) : NULL;
    for (CFIndex i = 0; list && i < CFArrayGetCount(list); i++) {
        CFDictionaryRef d = IOPSGetPowerSourceDescription(blob, CFArrayGetValueAtIndex(list, i));
        CFStringRef type = d ? CFDictionaryGetValue(d, CFSTR(kIOPSTypeKey)) : NULL;
        if (!type || !CFEqual(type, CFSTR(kIOPSInternalBatteryType))) continue;
        int ok1, ok2, ok3;
        double cur = cfnum(d, CFSTR(kIOPSCurrentCapacityKey), &ok1), max = cfnum(d, CFSTR(kIOPSMaxCapacityKey), &ok2);
        if (!ok1 || !ok2 || max <= 0) continue;
        b.have = 1;
        b.pct = cur / max * 100;
        CFStringRef state = CFDictionaryGetValue(d, CFSTR(kIOPSPowerSourceStateKey));
        b.plugged = state && CFEqual(state, CFSTR(kIOPSACPowerValue));
        double mins = cfnum(d, CFSTR(kIOPSTimeToEmptyKey), &ok3);
        b.secsleft = !b.plugged && ok3 && mins > 0 ? (int)(mins * 60) : -1;
        break;
    }
    if (list) CFRelease(list);
    if (blob) CFRelease(blob);
    // Watts from the battery driver (SMCBatteryManager): Voltage mV x Amperage mA; negative = draining.
    io_service_t s = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("AppleSmartBattery"));
    if (s) {
        CFMutableDictionaryRef p = NULL;
        if (IORegistryEntryCreateCFProperties(s, &p, NULL, 0) == KERN_SUCCESS && p) {
            int okv, oka;
            double mv = cfnum(p, CFSTR("Voltage"), &okv);
            CFTypeRef a = CFDictionaryGetValue(p, CFSTR("InstantAmperage"));
            if (!a) a = CFDictionaryGetValue(p, CFSTR("Amperage"));
            int64_t ma = 0;
            oka = a && CFGetTypeID(a) == CFNumberGetTypeID() && CFNumberGetValue((CFNumberRef)a, kCFNumberSInt64Type, &ma);
            if (okv && oka) b.watts = mv * (double)(int32_t)ma / 1e6;   // the driver stores a signed 32-bit value
            CFRelease(p);
        }
        IOObjectRelease(s);
    }
    return b;
}

// ---- per-app CPU and RAM ----

typedef struct { pid_t pid; uint64_t cpu_ns; char name[64]; } proc_t;
typedef struct { char name[64]; double cpu_ns; uint64_t ram; } app_t;

static proc_t *g_last;
static int g_nlast;
static mach_timebase_info_data_t g_tb;

// An app's name: the outermost .app bundle in its path (so "Safari" also covers its helpers), else the process name.
static void app_name(pid_t pid, char *out, size_t len) {
    char path[PROC_PIDPATHINFO_MAXSIZE];
    out[0] = 0;
    if (proc_pidpath(pid, path, sizeof(path)) > 0) {
        char *dot = strstr(path, ".app/");
        if (dot) {
            char *start = dot;
            while (start > path && start[-1] != '/') start--;
            size_t n = (size_t)(dot - start);
            if (n && n < len) { memcpy(out, start, n); out[n] = 0; return; }
        }
    }
    if (proc_name(pid, out, (uint32_t)len) <= 0) snprintf(out, len, "pid %d", pid);
}

static int cmp_cpu(const void *a, const void *b) {
    double x = ((const app_t *)a)->cpu_ns, y = ((const app_t *)b)->cpu_ns;
    return x < y ? 1 : x > y ? -1 : 0;
}
static int cmp_ram(const void *a, const void *b) {
    uint64_t x = ((const app_t *)a)->ram, y = ((const app_t *)b)->ram;
    return x < y ? 1 : x > y ? -1 : 0;
}

// Appends the top apps as JSON rows; returns how many. elapsed 0 = only remember the CPU times.
static int apps_json(buf_t *b, double elapsed, int ncpu) {
    int cap = proc_listallpids(NULL, 0) + 64;
    pid_t *pids = calloc((size_t)cap, sizeof(pid_t));
    int n = pids ? proc_listallpids(pids, cap * (int)sizeof(pid_t)) : 0;
    proc_t *now = calloc((size_t)(n > 0 ? n : 1), sizeof(proc_t));
    app_t *apps = calloc((size_t)(n > 0 ? n : 1), sizeof(app_t));
    int nnow = 0, napps = 0;
    for (int i = 0; now && apps && i < n; i++) {
        struct rusage_info_v2 ru;
        if (pids[i] <= 0 || proc_pid_rusage(pids[i], RUSAGE_INFO_V2, (rusage_info_t *)&ru) != 0) continue;
        proc_t *p = &now[nnow++];
        p->pid = pids[i];
        p->cpu_ns = (ru.ri_user_time + ru.ri_system_time) * g_tb.numer / g_tb.denom;
        app_name(p->pid, p->name, sizeof(p->name));
        double d = 0;
        for (int j = 0; j < g_nlast; j++)        // the previous scan, same pid and name (pids get reused)
            if (g_last[j].pid == p->pid && !strcmp(g_last[j].name, p->name)) {
                if (p->cpu_ns > g_last[j].cpu_ns) d = (double)(p->cpu_ns - g_last[j].cpu_ns);
                break;
            }
        int k = 0;
        while (k < napps && strcmp(apps[k].name, p->name)) k++;
        if (k == napps) { strlcpy(apps[k].name, p->name, sizeof(apps[k].name)); napps++; }
        apps[k].cpu_ns += d;
        apps[k].ram += ru.ri_phys_footprint;  // Activity Monitor's "Memory" column
    }
    free(g_last);
    g_last = now;
    g_nlast = nnow;
    free(pids);
    int rows = 0;
    if (elapsed > 0 && apps && napps) {
        char (*keep)[64] = calloc(2 * TOP_N, 64);
        int nk = 0;
        qsort(apps, (size_t)napps, sizeof(app_t), cmp_cpu);
        for (int i = 0; keep && i < napps && i < TOP_N; i++) strlcpy(keep[nk++], apps[i].name, 64);
        qsort(apps, (size_t)napps, sizeof(app_t), cmp_ram);
        for (int i = 0; keep && i < napps && i < TOP_N; i++) strlcpy(keep[nk++], apps[i].name, 64);
        for (int i = 0; keep && i < napps; i++) {
            int in = 0;
            for (int j = 0; j < nk && !in; j++) in = !strcmp(keep[j], apps[i].name);
            if (!in) continue;
            bput(b, rows ? ",{\"n\":" : "{\"n\":");
            bstr(b, apps[i].name);
            bput(b, ",\"cpu\":%.2f,\"ram\":%llu}", apps[i].cpu_ns / (elapsed * 1e9 * ncpu) * 100,
                 (unsigned long long)(apps[i].ram / 1048576));
            rows++;
        }
        free(keep);
    }
    free(apps);
    return rows;
}

// ---- sampler ----

static time_t g_last_t;
static cpu_t g_last_cpu;
static uint64_t g_last_rx, g_last_tx;
static int g_have_net;

// One sample object into s, one app scan object into a (empty when there is none).
static void sample(int tick, buf_t *s, buf_t *a) {
    time_t now = time(NULL);
    int fresh = g_last_t && now - g_last_t <= tick * 3;   // after sleep the deltas span the nap: start over
    double elapsed = fresh ? (double)(now - g_last_t) : 0;
    g_last_t = now;

    bput(s, "{\"t\":%ld", (long)now);
    cpu_t c = cpu_ticks();
    if (fresh && c.total > g_last_cpu.total)
        bput(s, ",\"cpu\":%.1f", (double)(c.busy - g_last_cpu.busy) / (c.total - g_last_cpu.total) * 100);
    g_last_cpu = c;
    uint64_t total = memsize(), used = ram_used();
    if (total) bput(s, ",\"ram\":%.1f,\"ram_used_gb\":%.2f", (double)used / total * 100, gib(used));
    bput(s, ",\"swap\":%.1f", swap_pct());
    double pct, fr, tot;
    if (volume("/System/Volumes/Data", &pct, &fr, &tot)) bput(s, ",\"disk\":%.1f", pct);
    uint64_t rx, tx;
    if (net_bytes(&rx, &tx)) {
        if (fresh && g_have_net && elapsed > 0)
            bput(s, ",\"net_rx\":%.1f,\"net_tx\":%.1f", (rx > g_last_rx ? rx - g_last_rx : 0) / 1024.0 / elapsed,
                 (tx > g_last_tx ? tx - g_last_tx : 0) / 1024.0 / elapsed);
        g_last_rx = rx; g_last_tx = tx; g_have_net = 1;
    }
    battery_t bat = battery();
    if (bat.have) {
        bput(s, ",\"battery\":%.1f,\"plugged\":%d", bat.pct, bat.plugged);
        if (bat.secsleft > 0) bput(s, ",\"secsleft\":%d", bat.secsleft);
        if (bat.watts < -0.05) bput(s, ",\"power\":%.2f", -bat.watts);
        else if (bat.watts > 0.05) bput(s, ",\"charge\":%.2f", bat.watts);
    }
    bput(s, "}");

    buf_t rows = {0};
    int n = apps_json(&rows, elapsed, sysint("hw.logicalcpu") ?: 1);
    if (n) bput(a, "{\"t\":%ld,\"dt\":%.0f,\"top\":[%.*s]}", (long)now, elapsed, (int)rows.n, rows.p);
    free(rows.p);
}

static int on_battery(void) {
    CFTypeRef blob = IOPSCopyPowerSourcesInfo();
    CFStringRef t = blob ? IOPSGetProvidingPowerSourceType(blob) : NULL;
    int r = t && CFEqual(t, CFSTR(kIOPSBatteryPowerValue));
    if (blob) CFRelease(blob);
    return r;
}

// ---- push (curl reads the URL + token header from the config file; the body comes on stdin) ----

static int push(const char *body, size_t len) {
    int fd[2];
    if (pipe(fd) != 0) return -1;
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_adddup2(&fa, fd[0], 0);
    posix_spawn_file_actions_addclose(&fa, fd[1]);
    posix_spawn_file_actions_addopen(&fa, 1, "/dev/null", O_WRONLY, 0);
    char *argv[] = { "curl", "-q", "-K", CONF, "-sS", "-f", "-o", "/dev/null", "--max-time", "15",
                     "-H", "Content-Type: application/json", "--data-binary", "@-", NULL };
    pid_t pid;
    int r = posix_spawn(&pid, "/usr/bin/curl", &fa, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&fa);
    close(fd[0]);
    if (r != 0) { close(fd[1]); return -1; }
    for (size_t off = 0; off < len; ) {
        ssize_t w = write(fd[1], body + off, len - off);
        if (w <= 0) break;
        off += (size_t)w;
    }
    close(fd[1]);
    int st = 0;
    if (waitpid(pid, &st, 0) < 0) return -1;
    return WIFEXITED(st) ? WEXITSTATUS(st) : -1;
}

// Queued samples / scans: one JSON object per entry.
typedef struct { char **v; int n; } queue_t;

static void qadd(queue_t *q, buf_t *b) {
    if (!b->n) { free(b->p); return; }
    if (q->n == QUEUE_MAX) { free(q->v[0]); memmove(q->v, q->v + 1, (size_t)(q->n - 1) * sizeof(char *)); q->n--; }
    char **v = realloc(q->v, (size_t)(q->n + 1) * sizeof(char *));
    if (!v) { free(b->p); return; }
    q->v = v;
    q->v[q->n++] = b->p;
}

static void qclear(queue_t *q) {
    for (int i = 0; i < q->n; i++) free(q->v[i]);
    q->n = 0;
}

static void qjson(buf_t *b, queue_t *q) {
    bput(b, "[");
    for (int i = 0; i < q->n; i++) bput(b, i ? ",%s" : "%s", q->v[i]);
    bput(b, "]");
}

int main(int argc, char **argv) {
    mach_timebase_info(&g_tb);
    if (argc > 1 && !strcmp(argv[1], "--once")) {
        buf_t s = {0}, a = {0}, i = {0};
        sample(5, &s, &a);
        free(s.p); free(a.p);
        s = (buf_t){0}; a = (buf_t){0};
        sleep(5);
        sample(5, &s, &a);
        info_json(&i);
        printf("{\"sample\":%s,\"apps\":%s,\"info\":%s}\n", s.p, a.n ? a.p : "null", i.p);
        return 0;
    }
    if (access(CONF, R_OK) != 0) { logmsg("no %s - exiting", CONF); return 1; }
    setpriority(PRIO_DARWIN_PROCESS, 0, PRIO_DARWIN_BG);    // background QoS: efficiency cores, throttled I/O
    logmsg("started, pid %d", getpid());
    queue_t samples = {0}, scans = {0};
    int n = 0, failures = 0;
    for (;;) {
        int tick = on_battery() ? TICK_BATTERY : TICK_AC;
        buf_t s = {0}, a = {0};
        sample(tick, &s, &a);
        qadd(&samples, &s);
        qadd(&scans, &a);
        if (++n % PUSH_EVERY == 0 && samples.n) {
            buf_t body = {0};
            bput(&body, "{\"samples\":");
            qjson(&body, &samples);
            bput(&body, ",\"apps\":");
            qjson(&body, &scans);
            bput(&body, ",\"info\":");
            info_json(&body);
            bput(&body, "}");
            int r = push(body.p, body.n);
            free(body.p);
            if (r == 0) {
                qclear(&samples);
                qclear(&scans);
                if (failures) logmsg("push ok again after %d failures", failures);
                failures = 0;
            } else if (++failures == 1 || failures == 10 || failures % 100 == 0) {
                logmsg("push failed (%d): curl exit %d", failures, r);   // not every time while offline
            }
        }
        sleep((unsigned)tick);
    }
}
