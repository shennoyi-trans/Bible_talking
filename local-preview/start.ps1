param([switch]$Offline)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if ($Offline) { $env:HF_HUB_OFFLINE = '1' }
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$nodePath = (Get-Command node).Source
if (!(Test-Path $pythonPath)) { throw '请先按照 README 安装 Python 依赖。' }
foreach ($port in @(8000, 5173)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "端口 $port 已被占用，请使用现有预览，或先停止它。"
    }
}
$backendProcess = Start-Process -FilePath $pythonPath -ArgumentList '-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'backend.log') -RedirectStandardError (Join-Path $PSScriptRoot 'backend-error.log') -PassThru
$backendProcess.Id | Set-Content (Join-Path $PSScriptRoot 'backend.pid')
$vitePath = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
$frontendProcess = Start-Process -FilePath $nodePath -ArgumentList $vitePath,'--host','127.0.0.1','--port','5173' -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'frontend.log') -RedirectStandardError (Join-Path $PSScriptRoot 'frontend-error.log') -PassThru
$frontendProcess.Id | Set-Content (Join-Path $PSScriptRoot 'frontend.pid')
Write-Output '预览：http://127.0.0.1:5173/ · 后端：http://127.0.0.1:8000/'
Write-Output '首次启动会建立索引；在语料库页面查看进度。'
