# Start Wavewatch THVS in the background whenever you sign in to Windows.
#   .\scripts\autostart.ps1            enable
#   .\scripts\autostart.ps1 -Disable   disable
# Creates or removes a shortcut in your Startup folder; no administrator rights needed.
param([switch]$Disable)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$startup = [Environment]::GetFolderPath('Startup')
$link = Join-Path $startup 'Wavewatch THVS.lnk'
# Remove the shortcut name used by earlier versions.
$legacy = Join-Path $startup 'Guanlan Monitor.lnk'
if (Test-Path -LiteralPath $legacy) { Remove-Item -LiteralPath $legacy }
if ($Disable) {
    if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link }
    Write-Host 'Autostart disabled.'
    exit 0
}
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'Run start.ps1 once first to create the Python environment.' }
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '-X utf8 "' + (Join-Path $root 'scripts\supervise.py') + '"'
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7
$shortcut.Description = 'Wavewatch THVS export-control monitor'
$shortcut.Save()
Write-Host "Autostart enabled: $link"
