$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (Test-Path release\Bible_talking\data) { throw '发布目录中已存在 data，请先保留整个旧版目录，再重新构建，避免覆盖语料。' }
    npm --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
    if (!(Test-Path build\seed-verification.json)) {
        & .venv\Scripts\python.exe desktop\prepare_seed.py
        if ($LASTEXITCODE -ne 0) { throw '发布索引准备失败。' }
    }
    & .venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath release --workpath build\desktop desktop\Bible_talking.spec
    if ($LASTEXITCODE -ne 0) { throw 'EXE 构建失败。' }
    & .venv\Scripts\python.exe desktop\assemble.py
    if ($LASTEXITCODE -ne 0) { throw '便携包组装失败。' }
    Write-Output '已生成 release/Bible_talking。请用独立测试目录执行 --smoke-test 验证，然后压缩该文件夹。'
} finally { Pop-Location }
