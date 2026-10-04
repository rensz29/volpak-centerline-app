<#
.SYNOPSIS
  Phase 0 readiness check for the Centerline control-room workstation (O-02).

.DESCRIPTION
  Read-only. Checks the Windows edition and support status, virtualisation,
  Hyper-V, memory, disk, a wired network adapter for the external switch,
  sleep settings, time sync and GPU. Prints PASS / WARN / FAIL per check and
  writes a report next to the script.

  Run from an elevated PowerShell for the Hyper-V feature check:
    powershell -ExecutionPolicy Bypass -File .\Test-CenterlineHost.ps1

.PARAMETER DataDrive
  Drive that will hold the VM disk and protected storage. Default: system drive.
#>
[CmdletBinding()]
param(
    [string]$DataDrive = $env:SystemDrive.TrimEnd(':')
)

$ErrorActionPreference = 'Stop'
$results = [System.Collections.Generic.List[object]]::new()

function Add-Result([string]$Check, [ValidateSet('PASS', 'WARN', 'FAIL', 'INFO')][string]$Status, [string]$Detail) {
    $results.Add([pscustomobject]@{ Check = $Check; Status = $Status; Detail = $Detail })
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# --- Windows edition and support ----------------------------------------------
$os = Get-CimInstance Win32_OperatingSystem
$build = [int]$os.BuildNumber
$caption = $os.Caption
if ($caption -match 'Home') {
    Add-Result 'Windows edition' 'FAIL' "$caption - Hyper-V is not available on Home; needs Pro, Enterprise, Education or LTSC"
} else {
    Add-Result 'Windows edition' 'PASS' $caption
}
if ($build -ge 22000) {
    Add-Result 'Windows version' 'PASS' "Windows 11, build $build"
} elseif ($caption -match 'LTSC|LTSB') {
    Add-Result 'Windows version' 'WARN' "Windows 10 LTSC, build $build - confirm the LTSC support end date with IT"
} else {
    Add-Result 'Windows version' 'FAIL' "Windows 10 build $build - out of support since 14 Oct 2025; use Windows 11 or LTSC"
}

# --- Virtualisation -----------------------------------------------------------
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
if ($cs.HypervisorPresent) {
    Add-Result 'Virtualisation' 'PASS' 'Hypervisor already running'
} elseif ($cpu.VirtualizationFirmwareEnabled) {
    Add-Result 'Virtualisation' 'PASS' 'Enabled in firmware'
} else {
    Add-Result 'Virtualisation' 'FAIL' 'Disabled in BIOS/UEFI - enable Intel VT-x / AMD-V'
}

if ($isAdmin) {
    $hv = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -ErrorAction SilentlyContinue
    if ($null -eq $hv) {
        Add-Result 'Hyper-V feature' 'FAIL' 'Feature not offered on this edition'
    } elseif ($hv.State -eq 'Enabled') {
        Add-Result 'Hyper-V feature' 'PASS' 'Enabled'
    } else {
        Add-Result 'Hyper-V feature' 'WARN' "State $($hv.State) - enable with: Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All"
    }
} else {
    Add-Result 'Hyper-V feature' 'WARN' 'Not checked - re-run from an elevated PowerShell'
}

# --- Memory and disk ------------------------------------------------------------
$ramGB = [math]::Round($cs.TotalPhysicalMemory / 1GB)
if ($ramGB -ge 32) { Add-Result 'Memory' 'PASS' "$ramGB GB" }
elseif ($ramGB -ge 16) { Add-Result 'Memory' 'WARN' "$ramGB GB - enough for the core; 32 GB recommended once a local AI model runs" }
else { Add-Result 'Memory' 'FAIL' "$ramGB GB - at least 16 GB needed" }

$vol = Get-Volume -DriveLetter $DataDrive -ErrorAction SilentlyContinue
if ($null -eq $vol) {
    Add-Result 'Disk' 'FAIL' "Drive $DataDrive`: not found"
} else {
    $freeGB = [math]::Round($vol.SizeRemaining / 1GB)
    $sizeGB = [math]::Round($vol.Size / 1GB)
    # SDD section 9: plan ~100 GB protected storage, plus the VM OS and headroom below the 80 % warning.
    if ($freeGB -ge 200) { Add-Result 'Disk' 'PASS' "$DataDrive`: $freeGB GB free of $sizeGB GB" }
    elseif ($freeGB -ge 150) { Add-Result 'Disk' 'WARN' "$DataDrive`: $freeGB GB free - tight; 200 GB free recommended" }
    else { Add-Result 'Disk' 'FAIL' "$DataDrive`: $freeGB GB free - needs about 200 GB" }
    $media = (Get-PhysicalDisk | Where-Object { $_.DeviceId -eq ((Get-Partition -DriveLetter $DataDrive | Get-Disk).Number).ToString() }).MediaType
    if ($media) { Add-Result 'Disk type' ($(if ($media -eq 'HDD') { 'WARN' } else { 'INFO' })) "$media" }
}

# --- Network ---------------------------------------------------------------------
$wired = Get-NetAdapter -Physical -ErrorAction SilentlyContinue |
    Where-Object { $_.Status -eq 'Up' -and $_.PhysicalMediaType -match '802\.3' }
if ($wired) {
    Add-Result 'Wired network' 'PASS' (($wired | ForEach-Object { "$($_.Name) ($($_.LinkSpeed))" }) -join ', ')
} else {
    Add-Result 'Wired network' 'FAIL' 'No connected Ethernet adapter - the VM external switch needs a wired LAN link'
}
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } |
    ForEach-Object { Add-Result 'IPv4 address' 'INFO' "$($_.InterfaceAlias): $($_.IPAddress)/$($_.PrefixLength)" }

# --- Power: a monitoring PC must never sleep -------------------------------------------
$standby = powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 2>$null |
    Select-String 'Current AC Power Setting Index: (0x[0-9a-fA-F]+)'
if ($standby) {
    $seconds = [Convert]::ToInt32($standby.Matches[0].Groups[1].Value, 16)
    if ($seconds -eq 0) { Add-Result 'Sleep on AC' 'PASS' 'Never' }
    else { Add-Result 'Sleep on AC' 'FAIL' "Sleeps after $([math]::Round($seconds / 60)) min - set to Never: powercfg /change standby-timeout-ac 0" }
} else {
    Add-Result 'Sleep on AC' 'WARN' 'Could not read power settings'
}

# --- Time: all records are UTC and ordered by time -----------------------------------
$tz = Get-TimeZone
Add-Result 'Time zone' ($(if ($tz.BaseUtcOffset.TotalHours -eq 8) { 'PASS' } else { 'WARN' })) "$($tz.Id) (UTC$('{0:+0;-0}' -f $tz.BaseUtcOffset.TotalHours))"
$w32 = w32tm /query /status 2>$null
$src = ($w32 | Select-String '^Source:\s*(.+)$').Matches | ForEach-Object { $_.Groups[1].Value.Trim() }
if ($src -and $src -notmatch 'Local CMOS Clock|Free-running') {
    Add-Result 'Time sync' 'PASS' "Source: $src"
} else {
    Add-Result 'Time sync' 'WARN' "Source: $(if ($src) { $src } else { 'unknown' }) - point the PC at the plant NTP server"
}

# --- GPU (input to O-01, AI model choice) -------------------------------------------------
Get-CimInstance Win32_VideoController | ForEach-Object {
    $vramGB = if ($_.AdapterRAM) { [math]::Round($_.AdapterRAM / 1GB, 1) } else { '?' }
    Add-Result 'GPU' 'INFO' "$($_.Name) (reported VRAM $vramGB GB; WMI caps this at 4 GB, check nvidia-smi for NVIDIA)"
}

# --- Output ------------------------------------------------------------------------------
$results | Format-Table -AutoSize -Wrap | Out-String -Width 200 | Write-Host
$fails = @($results | Where-Object Status -eq 'FAIL').Count
$warns = @($results | Where-Object Status -eq 'WARN').Count
$report = Join-Path $PSScriptRoot ("host-check-{0}-{1:yyyyMMdd-HHmm}.txt" -f $env:COMPUTERNAME, (Get-Date))
@(
    "Centerline host check - $env:COMPUTERNAME - $(Get-Date -Format o)"
    "Model: $($cs.Manufacturer) $($cs.Model); CPU: $($cpu.Name)"
    ($results | Format-Table -AutoSize -Wrap | Out-String -Width 200)
    "FAIL: $fails  WARN: $warns"
) | Set-Content -Path $report -Encoding UTF8
Write-Host "FAIL: $fails  WARN: $warns  -> report saved to $report"
if ($fails -gt 0) { exit 1 }
