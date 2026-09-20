# Run once (no admin needed) to make DalalSight start automatically whenever you log in to Windows, and
# keep itself running (auto-restart within 5s of any crash, forever). Uses the Startup folder rather than
# Task Scheduler, because Task Scheduler registration is blocked on this account (tried and denied).
# Undo: delete the two .cmd files this prints, or delete data\STOP to pause the loops without removing them.
$scriptDir = $PSScriptRoot
$startup = [Environment]::GetFolderPath("Startup")

function Install-StartupLauncher($name, $scriptPath) {
    $cmdPath = Join-Path $startup "$name.cmd"
    @"
@echo off
start "" /min powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "$scriptPath"
"@ | Set-Content -Path $cmdPath -Encoding ASCII
    Write-Host "Installed: $cmdPath"
    return $cmdPath
}

$backendCmd = Install-StartupLauncher "dalalsight-backend" (Join-Path $scriptDir "run-backend-loop.ps1")
$tunnelCmd = Install-StartupLauncher "dalalsight-tunnel" (Join-Path $scriptDir "run-tunnel-loop.ps1")

Write-Host ""
Write-Host "Both will start automatically the next time you log in to Windows, and every login after that."
Write-Host "To start them right now without logging out/in:"
Write-Host "  Start-Process `"$backendCmd`""
Write-Host "  Start-Process `"$tunnelCmd`""
