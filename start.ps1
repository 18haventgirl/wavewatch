# Start Guanlan.
#   .\start.ps1               run in this window (Ctrl+C to stop)
#   .\start.ps1 -Background   run hidden in the background, restarted automatically if it exits
#   .\start.ps1 -Install      (re)install Python and front-end dependencies first
param([switch]$Install, [switch]$Background)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$pythonw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'Creating the Python environment (.venv) ...'
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv. Install Python 3.11+ and add it to PATH.' }
    $Install = $true
}

# Python packages: reinstall when the lock file changed.
$lock = Join-Path $PSScriptRoot 'requirements.lock.txt'
$marker = Join-Path $PSScriptRoot '.venv\guanlan-requirements.sha256'
$lockHash = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash
$installed = if (Test-Path -LiteralPath $marker) { (Get-Content -LiteralPath $marker -Raw).Trim() } else { '' }
if ($Install -or $installed -ne $lockHash) {
    Write-Host 'Installing Python packages ...'
    & $python -m pip install --disable-pip-version-check -r $lock
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed. Check the network and run again.' }
    Set-Content -LiteralPath $marker -Value $lockHash -Encoding ascii
}

# Front end: build when missing or older than its sources.
$dist = Join-Path $PSScriptRoot 'frontend\dist\index.html'
$frontend = Join-Path $PSScriptRoot 'frontend'
$newestSource = @(Get-ChildItem -LiteralPath (Join-Path $frontend 'src') -Recurse -File) +
    @(Get-ChildItem -LiteralPath $frontend -File) |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$needBuild = $Install -or -not (Test-Path -LiteralPath $dist) -or ($newestSource.LastWriteTime -gt (Get-Item -LiteralPath $dist).LastWriteTime)
if ($needBuild) {
    Push-Location (Join-Path $PSScriptRoot 'frontend')
    try {
        if ($Install -or -not (Test-Path -LiteralPath 'node_modules')) {
            Write-Host 'Installing front-end packages ...'
            npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. Install Node.js 20.19+ and check the network.' }
        }
        Write-Host 'Building the front end ...'
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Front-end build failed.' }
    } finally { Pop-Location }
}

$url = 'http://127.0.0.1:8840'
if ($Background) {
    $supervisor = Join-Path $PSScriptRoot 'scripts\supervise.py'
    Start-Process -FilePath $pythonw -ArgumentList @('-X', 'utf8', "`"$supervisor`"") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    Write-Host "Guanlan is starting in the background: $url"
    Start-Sleep -Seconds 4
    Start-Process $url
} else {
    & $python -X utf8 run.py
}
