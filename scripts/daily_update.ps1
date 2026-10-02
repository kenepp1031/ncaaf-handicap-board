<#
Daily refresh, run unattended by the "NCAAF Handicap Daily Update" scheduled task
(see scripts/install_daily_task.ps1). Mirrors the sibling MLB app's daily_update.ps1.

One step: main.py --no-open, which does the whole batch pipeline -- ingest the
scoreboard/rankings/lines/weather/priors, refit the ratings, grade last week into the
backtest log, and rewrite dashboard/dashboard.html. main.py auto-detects season and week
from the games already in the database, so nothing here needs to know what week it is.
Then it commits dashboard/dashboard.html and pushes, which redeploys the Streamlit site.
Runs hourly 8 AM - 11 PM through scripts\run_hidden.vbs (no console flash).

Everything lands in logs/update-<date>.log; logs/last_run.json is the at-a-glance status.
Exits non-zero if the run fails, so the task's Last Run Result shows the failure.
#>
[CmdletBinding()]
param(
    # Season to refresh. Default: let main.py auto-detect.
    [int]$Season = 0,
    # Run even outside the season window.
    [switch]$Force,
    # Days of logs to keep.
    [int]$KeepLogs = 30
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs'
$logFile = Join-Path $logDir ("update-{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))
$statusFile = Join-Path $logDir 'last_run.json'

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# Write-Host, not the pipeline: anything written to the output stream would be collected
# into the caller's return value, which silently turns a step's exit code into an array.
function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

# Same launcher order as "Start NCAAF Handicap.cmd": the py launcher first, then the
# Codex runtime's bundled interpreter, then whatever "python" resolves to.
# Returns a hashtable rather than an array: an array whose only element is the exe would
# make the "arguments before main.py" slice below a special case (in PowerShell 1..0
# counts *down*, so a one-element $a[1..($a.Count-1)] silently yields $null plus $a[0]).
function Resolve-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{ Exe = (Get-Command py).Source; Pre = @('-3') }
    }
    $codex = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path $codex) {
        return @{ Exe = $codex; Pre = @() }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{ Exe = (Get-Command python).Source; Pre = @() }
    }
    return $null
}

function Invoke-Step {
    param([string]$Name, [string]$Exe, [string[]]$Arguments)
    Write-Log "--- $Name : starting"
    $started = Get-Date

    # Start-Process rather than the call operator: piping a native exe's stderr in
    # PowerShell 5.1 wraps each line in a NativeCommandError, which $ErrorActionPreference
    # = 'Stop' would turn into a thrown exception even on a clean exit 0.
    $out = [System.IO.Path]::GetTempFileName()
    $err = [System.IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $root `
            -NoNewWindow -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
        $code = $proc.ExitCode
        foreach ($f in @($out, $err)) {
            if ((Get-Item $f).Length -gt 0) {
                Add-Content -Path $logFile -Value (Get-Content $f -Encoding UTF8) -Encoding UTF8
            }
        }
    } finally {
        Remove-Item $out, $err -Force -ErrorAction SilentlyContinue
    }

    $mins = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
    if ($code -eq 0) {
        Write-Log "--- $Name : ok (${mins}m)"
    } else {
        Write-Log "--- $Name : FAILED exit $code (${mins}m)"
    }
    return $code
}

# One git call, output into the log. Start-Process for the same reason as Invoke-Step; the
# caller quotes any argument containing spaces, since 5.1 joins ArgumentList unquoted.
function Invoke-Git {
    param([string[]]$Arguments)
    $out = [System.IO.Path]::GetTempFileName()
    $err = [System.IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath 'git' -ArgumentList $Arguments -WorkingDirectory $root `
            -NoNewWindow -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
        foreach ($f in @($out, $err)) {
            if ((Get-Item $f).Length -gt 0) {
                Add-Content -Path $logFile -Value (Get-Content $f -Encoding UTF8) -Encoding UTF8
            }
        }
        return $proc.ExitCode
    } finally {
        Remove-Item $out, $err -Force -ErrorAction SilentlyContinue
    }
}

# Streamlit Cloud (streamlit_app.py) embeds dashboard/dashboard.html from GitHub and redeploys
# on push, so publishing is: commit that one file, push. Code changes are still committed by
# hand. Pushes even with nothing new, so a commit made while offline goes out with the next run.
function Publish-Dashboard {
    $rel = 'dashboard/dashboard.html'
    Write-Log "--- publish : starting"
    [void](Invoke-Git @('add', '--', $rel))
    if ((Invoke-Git @('diff', '--cached', '--quiet', '--', $rel)) -ne 0) {
        $msg = '"Publish board {0}"' -f (Get-Date -Format 'yyyy-MM-dd HH:mm')
        if ((Invoke-Git @('commit', '-m', $msg, '--', $rel)) -ne 0) {
            Write-Log "--- publish : FAILED at commit"
            return $false
        }
    }
    if ((Invoke-Git @('push', 'origin', 'HEAD')) -ne 0) {
        Write-Log "--- publish : FAILED at push (retried next run)"
        return $false
    }
    Write-Log "--- publish : ok (site redeploys in about a minute)"
    return $true
}

Set-Location $root
$env:GIT_TERMINAL_PROMPT = '0'
# So the child's stdout is UTF-8 rather than the console codepage, matching how the log is
# read back. The dashboard status line carries an R-squared superscript.
$env:PYTHONIOENCODING = 'utf-8'

# Where this run's output starts, so the summary below reads only its own lines and not
# those of an earlier run that shares today's log file.
$logOffset = if (Test-Path $logFile) { @(Get-Content $logFile).Count } else { 0 }

Write-Log "=== daily update starting ==="

$python = Resolve-Python
if ($null -eq $python) {
    Write-Log "FATAL: no Python interpreter found (tried the py launcher, the Codex runtime, and python on PATH)"
    exit 1
}
Write-Log "python: $($python.Exe) $($python.Pre -join ' ')"

# Between late January and August nothing changes: there are no new games to ingest, no
# lines posted, and the ratings fit would be identical every morning. Skipping keeps the
# offseason from rewriting the dashboard -- and from logging a failure every day if a feed
# returns an empty offseason payload.
$today = Get-Date
$seasonYear = if ($today.Month -ge 7) { $today.Year } else { $today.Year - 1 }
$inSeason = $Force -or ($today -ge (Get-Date -Year $seasonYear -Month 8 -Day 1) -and
                        $today -le (Get-Date -Year ($seasonYear + 1) -Month 1 -Day 20))

$failures = @()

if (-not $inSeason) {
    Write-Log "--- pipeline : skipped, outside the $seasonYear season window (use -Force to override)"
} else {
    $pyArgs = @($python.Pre) + @('main.py', '--no-open')
    if ($Season -gt 0) { $pyArgs += @('--season', "$Season") }
    if ((Invoke-Step -Name 'pipeline' -Exe $python.Exe -Arguments $pyArgs) -ne 0) {
        $failures += 'pipeline'
    } elseif (-not (Publish-Dashboard)) {
        $failures += 'publish'
    }
}

# The headline lines from this run, pulled back out of the log for last_run.json.
$summary = @(Get-Content $logFile -Encoding UTF8 | Select-Object -Skip $logOffset) -match '^(Dashboard ready|  Fit on)' |
    ForEach-Object { $_.Trim() }

$dash = Join-Path $root 'dashboard\dashboard.html'
$status = [ordered]@{
    finished  = (Get-Date -Format 'o')
    ok        = ($failures.Count -eq 0)
    failed    = $failures
    summary   = @($summary)
    dashboard = if (Test-Path $dash) { (Get-Item $dash).LastWriteTime.ToString('o') } else { $null }
    log       = $logFile
}
$status | ConvertTo-Json -Depth 3 | Out-File -FilePath $statusFile -Encoding utf8

# Drop logs older than the retention window.
Get-ChildItem $logDir -Filter 'update-*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepLogs) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

if ($failures.Count -gt 0) {
    Write-Log "=== daily update FINISHED WITH FAILURES: $($failures -join ', ') ==="
    exit 1
}

Write-Log "=== daily update ok ==="
exit 0
