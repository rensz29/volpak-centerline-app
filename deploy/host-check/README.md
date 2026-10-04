# Host runtime test — O-02 (Phase 0)

This proves on the **actual control-room PC** that the recommended runtime,
a Hyper-V Linux VM running Docker Engine, meets the SDD:

| # | Must prove | URS |
|---|---|---|
| 1 | The PC can run Hyper-V (edition, virtualisation, RAM, disk, wired LAN) | DEP-01 |
| 2 | VM and containers start after a reboot **with nobody logged in** | DEP-05 |
| 3 | The app sees each browser's **real LAN IP address** | SES-04 |
| 4 | The PC never sleeps, and its clock is synced | AVL-01, DEP-06 |

Record the results in [ADR-0003](../../docs/decisions/ADR-0003-host-runtime.md).

## Step 1 — Readiness check (5 min)

From an **elevated** PowerShell on the control-room PC:

```powershell
powershell -ExecutionPolicy Bypass -File .\Test-CenterlineHost.ps1 -DataDrive D   # drive for VM + data
```

Fix every FAIL before continuing. Typical fixes:

| FAIL | Fix |
|---|---|
| Windows edition Home | Upgrade to Pro, Enterprise or LTSC (IT) |
| Windows 10 | Windows 11 or LTSC. Windows 10 support ended on 14 Oct 2025 |
| Virtualisation disabled | BIOS/UEFI → enable Intel VT-x (or AMD-V) |
| Disk | Add a data SSD (about 200 GB free) |
| Sleep on AC | `powercfg /change standby-timeout-ac 0` |

Then enable Hyper-V and reboot:

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
```

## Step 2 — Create the VM (30 min)

Use Ubuntu Server 24.04 LTS (download the ISO first; the rest works offline).

```powershell
# External switch bound to the wired adapter (name from Step 1's "Wired network" line)
New-VMSwitch -Name 'Plant-LAN' -NetAdapterName 'Ethernet' -AllowManagementOS $true

New-VM -Name centerline-core -Generation 2 -MemoryStartupBytes 16GB `
       -NewVHDPath 'D:\Hyper-V\centerline-core.vhdx' -NewVHDSizeBytes 200GB -SwitchName 'Plant-LAN'
Set-VMMemory    -VMName centerline-core -DynamicMemoryEnabled $false
Set-VMProcessor -VMName centerline-core -Count 4
Set-VMFirmware  -VMName centerline-core -SecureBootTemplate MicrosoftUEFICertificateAuthority
Add-VMDvdDrive  -VMName centerline-core -Path 'D:\iso\ubuntu-24.04-live-server-amd64.iso'
Set-VMFirmware  -VMName centerline-core -FirstBootDevice (Get-VMDvdDrive -VMName centerline-core)

# The key setting for DEP-05: start with Windows, shut down cleanly with it
Set-VM -Name centerline-core -AutomaticStartAction Start -AutomaticStartDelay 0 -AutomaticStopAction ShutDown
Start-VM centerline-core
```

Install Ubuntu from the VM console. Ask IT for a **static IP or a DHCP
reservation** for the VM: operators' browsers and the firewall rules depend
on it. Then, inside the VM:

```bash
# Docker Engine (not Docker Desktop) from Docker's apt repository
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable docker containerd

# Test container: echoes the client IP it sees, restarts on every boot
sudo docker run -d --name whoami --restart always -p 8080:80 traefik/whoami
```

## Step 3 — Real client IP (5 min)

From a **different** PC on the plant LAN (ideally the backup operator
workstation), open `http://<vm-ip>:8080/`. The `RemoteAddr` line must show
**that PC's own IP address**. A 172.x or 10.x address that isn't the PC's
own means NAT is in the way, and SES-04 workstation checks would fail.

## Step 4 — Start without login (20 min)

```powershell
.\Test-BootAutostart.ps1 -Register -VmName centerline-core -HealthUrl http://<vm-ip>:8080/
Restart-Computer
```

**Don't log in.** Wait 10 minutes, then log in and open
`C:\ProgramData\Centerline\boot-check.log`. You need a line ending in
`PASS`, which means `logged-on user: <none>`, `VM centerline-core: Running`
and `health: HTTP 200`.

Repeat once after a Windows Update restart. Then clean up with
`.\Test-BootAutostart.ps1 -Unregister`.

## Step 5 — Soak (optional, 1 week)

Leave the VM running for a week with the boot task registered. Any
unexpected restart adds a log line, and each line must be PASS.

## If a step fails

| Failure | Next step |
|---|---|
| Hyper-V can't be enabled | Fallback B: WSL2 + Docker Engine started by a boot task (needs a longer soak test) |
| Step 3 shows a NAT address | Check the switch is **External**, not Default/Internal |
| Step 4 VM Off | `Get-VM centerline-core \| fl AutomaticStartAction`, and check the Hyper-V event log |
| AI model needs a GPU (O-01) | Run Ollama on the Windows host, reachable only from the VM; record it as a DEP-01 deviation |
