# Dashboard Ideas & Backlog

A running list of features/stats to consider. Checked = shipped; unchecked = backlog.
Add anything here as it comes up so it doesn't get lost.

## Shipped

- [x] Live Mac mini stats (CPU, RAM, swap, disk I/O, network, uptime) — Batch 2
- [x] Web-editable projects & services (settings modal, write token) — Phase 4
- [x] Multi-container Docker log viewer — Batch 2
- [x] GitHub Downloads (auto-synced) — Batch 3
- [x] Disk-volume fix, load avg, network total, Docker count, Storage Volumes — Batch 4
- [x] Live CPU/GPU temperature + accurate memory + measured power (macmon) — Batch 5
- [x] **Tailscale device panel** (online/offline, OS, IP, last-seen) — Batch 6
- [x] **"Homelab console" restyle** (per-metric colors, depth, mono numbers, glow) — Batch 6
- [x] **Live sparklines** (CPU/RAM/temp/power recent history) — Batch 6
- [x] **Command palette** (`/` or ⌘K fuzzy jump) — Batch 6
- [x] **PWA** (installable, offline shell, favicon) + header clock/greeting — Batch 6
- [x] **Docker per-container stats** (CPU/MEM) — Batch 6
- [x] **Alert / overload event log** (records when CPU/RAM/swap/temp/load/disk go dangerously high, server-side 24/7) — Batch 7
- [x] **30-minute sparklines** backed by a server-side history ring (`/api/history`), taller + zero-anchored where it makes sense — Batch 8
- [x] **Five selectable skins** (Bento / Ops / CRT / Paper / Classic) as live prototypes — full redesigns incl. graph form, picked from the header — Batch 8
- [x] **Expandable stat cards** — click for the full 30m/6h/24h graph, peak/avg/min, and that metric's alerts — Batch 8
- [x] **7-day persisted history** (5-minute min/avg/max buckets in `history.json`) — Batch 8
- [x] **Disk fill projection** (%/day + days to 95%, least-squares over the bucket history) — Batch 8
- [x] **Service downtime episodes** logged into the same event log as metric alerts — Batch 8
- [x] **Sparklines for swap / load / disk + mirrored network graph** (download up, upload down) — Batch 8

## Monitoring / stats (backlog)

- [ ] Top processes — highest CPU/RAM process names (psutil.process_iter)
- [ ] GPU / ANE usage % — macmon already reports `gpu_usage`, `ecpu`/`pcpu`
- [ ] Internet health — public IP, ping/latency to gateway, quick down/up check
- [ ] Per-service uptime % / availability history — the downtime episodes are recorded now, so this is just aggregation over them
- [ ] Disk SMART health / temperature per drive
- [ ] Charts over the full 7 days retained in `history.json` (the expanded view stops at 24h)
- [ ] Sparkline hover tooltips (value + time at the cursor) — the expanded view has windows now, but no crosshair
- [ ] Per-volume disk history (external drives), not just the internal data volume
- [ ] Prune the skins down to the chosen one once picked (each is a contiguous block in `style.css`)
- [ ] Alert log follow-ups: web-editable thresholds, ack/clear button, per-volume disk alerts

## Interaction / UX (backlog)

- [ ] Browser/OS notifications when a new alert fires or a service drops offline (deferred in Batch 7 — chose in-page highlight only)
- [ ] Command palette actions (not just navigation) — e.g. "open logs for X"
- [ ] Auto light/dark by time of day
- [ ] Weather widget in the header (needs an API key / a free source)
- [ ] Drag-to-reorder sections / collapsible sections

## Control actions (backlog — higher risk, needs write auth)

- [ ] Docker start / stop / restart buttons per container
- [ ] Restart a service / reboot the mini (guarded, confirmation)
- [ ] Run a Tailscale command (e.g. toggle exit node)

## Personal (backlog)

- [ ] Bookmarks / quick-links tile (custom links)
- [ ] Notes / scratchpad (localStorage)
- [ ] P-Cal upcoming events (pull from the calendar container)
- [ ] GitHub contribution/activity graph
- [ ] Now-playing / media widget
