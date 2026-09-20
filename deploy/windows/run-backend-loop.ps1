# Keeps the DalalSight backend running: restarts it a few seconds after any exit (crash, or a manual
# `python -m cc` you stopped for a moment), forever. Registered as a Scheduled Task (see setup-windows.ps1),
# so it starts automatically when you log in to Windows and keeps itself alive after that.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)  # .../command_center
$python = Join-Path $root ".venv\Scripts\python.exe"
$log = Join-Path $root "data\backend-loop.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

while ($true) {
    "$(Get-Date -Format o)  starting backend" | Add-Content -Path $log
    Push-Location $root
    & $python -m cc *>> $log
    Pop-Location
    "$(Get-Date -Format o)  backend exited (code $LASTEXITCODE), restarting in 5s" | Add-Content -Path $log
    Start-Sleep -Seconds 5
}
