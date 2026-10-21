# Laptop agent

`agent.py` runs on the Windows laptop and pushes its stats to the Mac's API
(`POST /api/laptop/push`), which feeds the **Laptop** tab on the dashboard.

## What it sends

Every 30 s on AC, every 60 s on battery:

- CPU %, RAM % and GB used, page file %, C: usage, network KB/s
- Battery %, plugged in or not, Windows' time-left estimate
- Battery drain in watts (from the battery driver; only measurable while on battery), or charge rate while charging
- Hottest ACPI thermal zone (°C)
- The top 10 apps by CPU and by RAM: all of an app's processes summed, CPU as % of the whole processor
  since the previous sample, RAM as private working set (Task Manager's "Memory" column)

Samples are pushed in batches of two (every 1 or 2 minutes). If the Mac can't be reached the batch
stays queued (up to 480 samples) and goes with the next push.

## Cost

- One process, about 30–40 MB of RAM, asleep between ticks
- A sample takes about 30 ms of CPU, including one system-wide process snapshot (~6 ms). That
  snapshot is read in a single `NtQuerySystemInformation` call rather than through psutil: without
  admin rights psutil can't open ~100 system processes, and its fallback for each of them is a
  whole-system query, which made each scan cost about 1 s of CPU
- It runs with EcoQoS (Windows "efficiency mode") and below-normal priority
- After the laptop sleeps, the first sample discards its deltas instead of averaging over the nap

## Network route

The agent looks up the Funnel hostname's public addresses through Cloudflare DNS-over-HTTPS and
posts there, falling back to the normal (tailnet) address. When the laptop's traffic runs through
Cloudflare WARP, full-size Tailscale packets from the laptop to the Mac are dropped. Small requests
still work, but any upload over about 1.2 KB stalls and is reset. The public Funnel route is ordinary
internet TCP and isn't affected. The TLS context also offers only classic key-exchange groups, which
keeps the TLS hello in a single packet.

## Install

Python 3 from python.org, plus `psutil`:

```powershell
py -m pip install --user psutil
mkdir $env:USERPROFILE\homepage-agent
# copy agent.py there, then create agent.json next to it:
#   {"url": "https://my-biggest-beefsteak.tail437237.ts.net:8443/api/laptop/push",
#    "token": "<contents of laptop-token.txt in the API folder on the Mac>"}
```

Test one sample without pushing:

```powershell
py $env:USERPROFILE\homepage-agent\agent.py --once
```

Start it at logon with a scheduled task (no window, allowed on battery, restarted if it dies):

```powershell
$dir = "$env:USERPROFILE\homepage-agent"
$pyw = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$dir\agent.py`"" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "Homepage Laptop Agent" -Action $action -Trigger $trigger `
  -Settings $settings -Principal $principal -Force
Start-ScheduledTask -TaskName "Homepage Laptop Agent"
```

## Update

Copy the new `agent.py` over the old one, then restart it. A second copy exits immediately (named
mutex), so stop the running one first:

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object CommandLine -like "*homepage-agent*" | ForEach-Object { Stop-Process -Id $_.ProcessId }
Start-ScheduledTask -TaskName "Homepage Laptop Agent"
```

## Remove

```powershell
Unregister-ScheduledTask -TaskName "Homepage Laptop Agent" -Confirm:$false
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object CommandLine -like "*homepage-agent*" | ForEach-Object { Stop-Process -Id $_.ProcessId }
Remove-Item -Recurse $env:USERPROFILE\homepage-agent
```

## Files on the laptop

| File | |
|------|---|
| `agent.py` | the agent |
| `agent.json` | push URL and token (not in git) |
| `agent.log` | start-up lines and errors only, rotated at 512 KB |
