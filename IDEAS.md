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

## Monitoring / stats (backlog)

- [ ] Top processes — highest CPU/RAM process names (psutil.process_iter)
- [ ] GPU / ANE usage % — macmon already reports `gpu_usage`, `ecpu`/`pcpu`
- [ ] Internet health — public IP, ping/latency to gateway, quick down/up check
- [ ] Per-service uptime % / availability history (needs lightweight persistence)
- [ ] Disk SMART health / temperature per drive
- [ ] Longer stat history with real charts (24h/7d) — needs a small time-series store
- [ ] Sparklines for more metrics (network, load) + hover tooltips

## Interaction / UX (backlog)

- [ ] Browser notifications when a service drops offline
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
