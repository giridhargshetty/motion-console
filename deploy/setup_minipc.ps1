# One-time setup of the mini PC as a motion console. Run in PowerShell on the mini PC:
#
#   powershell -ExecutionPolicy Bypass -File setup_minipc.ps1 -RepoUrl https://github.com/<you>/<repo>.git
#
# It installs Git and Python 3.12 if missing (winget asks you to accept their terms),
# clones the project, installs packages, downloads the pose models, sets fullscreen for
# this machine, and adds a Startup shortcut so the game starts when you sign in.
# Some Windows settings are left for you to change by hand; they are printed at the end.

param(
    [Parameter(Mandatory = $true)][string]$RepoUrl,
    [string]$Dir = "$env:USERPROFILE\motion-console"
)
$ErrorActionPreference = 'Stop'
function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

Step 'Checking Git and Python 3.12'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    winget install -e --id Git.Git
    Refresh-Path
}
if (-not (Get-Command adb -ErrorAction SilentlyContinue) -and
    -not (Test-Path "$env:LOCALAPPDATA\Microsoft\WinGet\Links\adb.exe") -and
    -not (Test-Path 'C:\Program Files\DroidCam\Client\data\obs-plugins\droidcam-obs\adb\adb.exe')) {
    Step "Installing Google's adb (Android platform tools) to talk to the phone over USB"
    winget install -e --id Google.PlatformTools
    Refresh-Path
}
$hasPy = $false
try { $hasPy = (& py -3.12 --version 2>$null) -match '3\.12' } catch { }
if (-not $hasPy) {
    winget install -e --id Python.Python.3.12
    Refresh-Path
}

Step "Getting the code into $Dir"
if (Test-Path (Join-Path $Dir '.git')) {
    git -C $Dir pull --ff-only
} else {
    git clone $RepoUrl $Dir   # a private repo opens a GitHub sign-in window once
}
Set-Location $Dir

Step 'Creating the Python environment (a few minutes)'
if (-not (Test-Path '.venv')) { py -3.12 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Step 'Downloading pose models'
& .\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'prototype'); import player; player.get_model('full'); player.get_model('lite')"

Step 'Settings for this machine (prototype\config.local.toml, not in git)'
$local = 'prototype\config.local.toml'
if (-not (Test-Path $local)) {
    @(
        '# Settings for this machine only. Overrides prototype/config.toml.',
        '[game]',
        'fullscreen = true'
    ) | Set-Content -Path $local -Encoding utf8
}
Get-Content $local

Step 'Adding the Startup shortcut'
$startup = [Environment]::GetFolderPath('Startup')
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $startup 'Motion Console.lnk'))
$lnk.TargetPath = 'powershell.exe'
$lnk.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Dir\deploy\console.ps1`""
$lnk.WorkingDirectory = $Dir
$lnk.Save()
Write-Host "Created: $(Join-Path $startup 'Motion Console.lnk')"

Step 'Done. Now do these by hand (see deploy\README.md for details):'
@'
  1. Phone: plug it in by USB and tap "Allow" (tick "Always allow") when it asks about USB debugging.
     The DroidCam PC client is NOT needed (the game reads the phone directly).
  2. Phone: Developer options -> turn on "Stay awake" (screen stays on while charging).
  3. Windows: sign in automatically (Settings -> Accounts -> Sign-in options, then netplwiz).
  4. Windows: Power -> Screen and sleep -> Never (when plugged in).
  5. BIOS: "AC Recovery" / "Power on after power loss" = On, so the box starts when powered.
  6. Test: restart the mini PC. The game should appear on the TV by itself.
'@ | Write-Host
