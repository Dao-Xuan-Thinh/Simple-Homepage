# Laptop agent (macOS side)

The G14 also boots macOS (the hackintosh). `agent.c` is the same agent for that OS: it pushes the same
payload as `../agent.py` to `POST /api/laptop/push`, so it fills the same **Laptop** tab. Only one OS runs at
a time. `info.os` says which one sent the data.

It is written in C because that macOS has no Python (running `/usr/bin/python3` opens the Command Line
Tools installer).

## What it sends

The same fields as the Windows agent, every 30 s on AC (60 s on battery), pushed two at a time:

- CPU %
- RAM % and GB used (app memory + wired + compressed, as in Activity Monitor)
- swap %
- Data volume %
- network KB/s (physical interfaces only, without Tailscale's utun)
- battery %, plugged in or not, time left
- battery drain or charge rate in W (Voltage x Amperage from SMCBatteryManager)
- the top 10 apps by CPU and by RAM

Apps are grouped by their outermost `.app` bundle, so helpers count toward their app. RAM is the
physical footprint (Activity Monitor's "Memory" column). There is no temperature: the laptop has no CPU
sensor driver.

Cost: about 2.5 MB of RAM, asleep between ticks, background QoS.

## Files on the laptop

| File | |
|------|---|
| `/usr/local/libexec/homepage-agent` | the binary |
| `/usr/local/etc/homepage-agent.conf` | root 0600: `url = "…/api/laptop/push"` and `header = "X-Push-Token: …"` (read by curl, never on argv) |
| `/Library/LaunchDaemons/com.spider.homepage-agent.plist` | runs it as root (to see every process), KeepAlive |
| `/var/log/homepage-agent.log` | start-up lines and push errors only, rotated at 512 KB |

## Build, test, update

```sh
clang -arch x86_64 -mmacosx-version-min=15.0 -O2 -o homepage-agent agent.c -framework IOKit -framework CoreFoundation
codesign -s - -f homepage-agent
sudo ./homepage-agent --once        # one sample as JSON, no push
sudo install -m 755 homepage-agent /usr/local/libexec/homepage-agent
sudo launchctl kickstart -k system/com.spider.homepage-agent
```

Remove: `sudo launchctl bootout system/com.spider.homepage-agent`, then delete the files above.
