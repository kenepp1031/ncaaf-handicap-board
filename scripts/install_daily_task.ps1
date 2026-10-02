<#
Registers (or re-registers) the "NCAAF Handicap Daily Update" scheduled task, which runs
scripts/daily_update.ps1 every morning under the current user.

    powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1 -At 05:30
    powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1 -Uninstall

Runs as the logged-in user with an interactive token, not SYSTEM, so it uses the same user
profile and Python launcher a manual run does. StartWhenAvailable catches up the run if the
machine was asleep at the scheduled time.
#>
[CmdletBinding()]
param(
    # Time of day to run, 24h. Early enough that the dashboard is current before kickoff.
    [string]$At = '06:30',
    [string]$TaskName = 'NCAAF Handicap Daily Update',
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root 'scripts\daily_update.ps1'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'."
    exit 0
}

if (-not (Test-Path $script)) { throw "Missing $script" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $script) `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 30)

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description 'Refreshes the NCAAF handicap database and rewrites dashboard/dashboard.html.' | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "Installed '$TaskName' - daily at $At, state $($task.State)."
Write-Host "Run it now with: Start-ScheduledTask -TaskName '$TaskName'"
