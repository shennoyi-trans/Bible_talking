$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
foreach ($kind in @('backend','frontend')) {
    $pidPath = Join-Path $PSScriptRoot "$kind.pid"
    if (!(Test-Path $pidPath)) { continue }
    $ownedProcessId = [int](Get-Content $pidPath)
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ownedProcessId"
    if (!$processInfo) { continue }
    $isOwned = ($kind -eq 'backend' -and $processInfo.ExecutablePath -eq (Join-Path $projectRoot '.venv\Scripts\python.exe')) -or ($kind -eq 'frontend' -and $processInfo.CommandLine -like "*$projectRoot*frontend*node_modules*vite*")
    if (!$isOwned) { throw "PID $ownedProcessId 不属于本项目，未停止。" }
    # The venv launcher can own a child interpreter. Validate each child's command.
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ownedProcessId" | Where-Object { $_.CommandLine -like '*uvicorn backend.main:app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId }
    Stop-Process -Id $ownedProcessId -ErrorAction SilentlyContinue
}
Write-Output '已停止本项目预览。未完成的导入会在下次启动时继续。'
