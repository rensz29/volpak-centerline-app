<#
.SYNOPSIS
  Proves the Centerline VM and its containers start after a reboot with nobody logged in (DEP-05, O-02).

.DESCRIPTION
  -Register   installs a startup task (runs as SYSTEM, no login needed) that waits,
              then records whether a user is logged on, the VM state, and whether
              the health URL answers. Run elevated.
  -Run        what the task executes; you can also run it by hand.
  -Unregister removes the task.

  Test procedure:
    1. .\Test-BootAutostart.ps1 -Register -VmName centerline-core -HealthUrl http://<vm-ip>:8080/
    2. Restart the PC and do NOT log in. Wait at least 10 minutes.
    3. Log in and read C:\ProgramData\Centerline\boot-check.log
       PASS means: "logged-on user: <none>", VM Running, health HTTP 200.
    4. Repeat after a Windows Update restart. Then -Unregister.
#>
[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [Parameter(ParameterSetName = 'Register', Mandatory)][switch]$Register,
    [Parameter(ParameterSetName = 'Unregister', Mandatory)][switch]$Unregister,
    [Parameter(ParameterSetName = 'Run')][switch]$Run,
    [string]$VmName = 'centerline-core',
    [string]$HealthUrl = '',
    [int]$DelaySeconds = 300
)

$TaskName = 'Centerline-BootCheck'
$LogDir = Join-Path $env:ProgramData 'Centerline'
$Log = Join-Path $LogDir 'boot-check.log'

switch ($PSCmdlet.ParameterSetName) {
    'Register' {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
        $script = Join-Path $LogDir 'Test-BootAutostart.ps1'
        Copy-Item -Force $PSCommandPath $script
        $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Run -VmName `"$VmName`" -DelaySeconds $DelaySeconds"
        if ($HealthUrl) { $arguments += " -HealthUrl `"$HealthUrl`"" }
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
        Write-Host "Registered '$TaskName'. Restart without logging in, wait 10 min, then read $Log"
    }
    'Unregister' {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed '$TaskName'. Log kept at $Log"
    }
    'Run' {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
        Start-Sleep -Seconds $DelaySeconds
        $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
        $user = (Get-CimInstance Win32_ComputerSystem).UserName
        $vmState = try { (Get-VM -Name $VmName -ErrorAction Stop).State } catch { "error: $($_.Exception.Message)" }
        $health = if ($HealthUrl) {
            try { "HTTP $((Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 10).StatusCode)" }
            catch { "failed: $($_.Exception.Message)" }
        } else { 'not configured' }
        $verdict = if (-not $user -and "$vmState" -eq 'Running' -and ($health -eq 'HTTP 200' -or $health -eq 'not configured')) { 'PASS' } else { 'CHECK' }
        $line = "{0:o} | boot {1:o} | +{2}s | logged-on user: {3} | VM {4}: {5} | health: {6} | {7}" -f `
            (Get-Date), $boot, $DelaySeconds, $(if ($user) { $user } else { '<none>' }), $VmName, $vmState, $health, $verdict
        Add-Content -Path $Log -Value $line -Encoding UTF8
    }
}
