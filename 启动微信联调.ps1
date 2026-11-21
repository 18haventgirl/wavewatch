$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv-v2\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Server environment missing. Follow backend/README.md to install it.' }
& $pythonPath -X utf8 (Join-Path $PSScriptRoot 'scripts\start_wechat_dev.py')
