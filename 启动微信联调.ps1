$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv-v2\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先按 backend/README.md 安装服务器开发环境。' }
& $pythonPath -X utf8 (Join-Path $PSScriptRoot 'scripts\start_wechat_dev.py')
