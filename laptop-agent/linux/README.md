# Laptop agent (Linux side)

The G14 also boots CachyOS. `agent.py` here is the agent for that OS: it pushes the same payload as
`../agent.py` to `POST /api/laptop/push`, so it fills the same **Laptop** tab. Only one OS runs at a time.
`info.os` says which one sent the data; its first word ("CachyOS") becomes the OS key `cachyos`.

It uses the Python standard library only and reads everything from `/proc` and `/sys`, so nothing needs
installing.

## What it sends

The same fields as the Windows agent, every 30 s on AC (60 s on battery), pushed two at a time:

- CPU %
- RAM % and GB used (total - available)
- swap % (zram on CachyOS)
- root filesystem %
- network KB/s (interfaces with a device behind them, so not Tailscale or VPN tunnels)
- battery %, plugged in or not, time left
- battery drain or charge rate in W (`power_now`, or `current_now` x `voltage_now`)
- CPU temperature (`k10temp` Tctl, else the hottest ACPI thermal zone)
- the top 10 apps by CPU and by RAM

Apps are grouped by the program file they run, so browser and Electron helpers count toward their app.
For interpreters (python, node, ...) the script name is used, and for Wine/Proton the Windows program.
RAM is each process's own memory (resident - shared, i.e. RssAnon). Kernel threads are one row, `kernel`.

Cost: two samples took ~0.13 s of CPU including Python start-up; about 11 MB of RAM.

## Files on the laptop

| File | |
|------|---|
| `/usr/local/lib/homepage-agent/agent.py` | the agent |
| `/etc/homepage-agent.json` | root 0600: `{"url": "…/api/laptop/push", "token": "…"}` |
| `/etc/systemd/system/homepage-agent.service` | runs it as root (to see every process) at idle CPU/IO priority |

Errors go to the journal: `journalctl -u homepage-agent`.

## Install, test, update

Copy `agent.py`, `homepage-agent.service`, `install.sh` (and `agent.json` the first time) into one folder, then:

```sh
python3 -I agent.py --once        # one sample as JSON, no push (sudo to see root's process names)
sudo sh install.sh                # installs or updates, then restarts the service
```

Remove: `sudo systemctl disable --now homepage-agent`, then delete the files above.
