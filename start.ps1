param([switch]$Install)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建运行环境失败。' }
    $Install = $true
}
if ($Install) {
    $requirementsPath = if (Test-Path -LiteralPath 'requirements.lock.txt') { 'requirements.lock.txt' } else { 'requirements.txt' }
    & $pythonPath -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络。' }
    Push-Location frontend
    try {
        npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
    } finally { Pop-Location }
}
& $pythonPath -X utf8 run.py
