# Console launcher: runs at sign-in on the mini PC (Startup shortcut made by setup_minipc.ps1).
#   1. pulls the latest version from GitHub (skipped quietly when offline)
#   2. makes sure the DroidCam PC client isn't running (it would take the phone's only video connection)
#   3. runs the game fullscreen, and restarts it if it crashes
# The game itself connects to the phone over USB (adb), opening the DroidCam app if needed.
# Press Esc in the game to quit to the desktop for maintenance. Log: logs\console.log

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$Logs = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force $Logs | Out-Null
$Log = Join-Path $Logs 'console.log'
function Log($msg) { "$(Get-Date -Format 's')  $msg" | Add-Content -Path $Log -Encoding utf8 }
Set-Location $Root
Log '---- console start ----'

# 1. Update. GIT_TERMINAL_PROMPT=0 so a login problem fails fast instead of waiting for input.
$env:GIT_TERMINAL_PROMPT = '0'
$reqBefore = (Get-FileHash requirements.txt).Hash
$updated = $false
for ($try = 1; $try -le 5 -and -not $updated; $try++) {
    $out = git pull --ff-only 2>&1
    if ($LASTEXITCODE -eq 0) { $updated = $true; Log "update: $($out -join ' ')" }
    else { Log "update try $try failed: $($out -join ' ')"; Start-Sleep -Seconds 3 }
}
if ((Get-FileHash requirements.txt).Hash -ne $reqBefore) {
    Log 'requirements.txt changed: installing packages'
    & "$Root\.venv\Scripts\python.exe" -m pip install -q -r requirements.txt 2>&1 | ForEach-Object { Log "pip: $_" }
}

# 2. The DroidCam phone app serves one connection at a time; the PC client (if installed)
#    reconnects every 2 s and would take it, so stop it. The game talks to the phone directly.
$client = Get-Process droidcam -ErrorAction SilentlyContinue
if ($client) {
    $client | Stop-Process -Force
    Log 'stopped the DroidCam PC client (the game connects to the phone directly)'
}

# 3. Game loop. pythonw = no console window. Exit code 0 means Esc: stop and show the desktop.
$Python = Join-Path $Root '.venv\Scripts\pythonw.exe'
while ($true) {
    Log 'starting game'
    $game = Start-Process -FilePath $Python -ArgumentList 'prototype\fruit_slice.py' -WorkingDirectory $Root `
        -RedirectStandardError (Join-Path $Logs 'game_errors.log') -PassThru -Wait
    Log "game exited with code $($game.ExitCode)"
    if ($game.ExitCode -eq 0) { break }
    Start-Sleep -Seconds 3
}
Log '---- console stopped (Esc pressed) ----'
