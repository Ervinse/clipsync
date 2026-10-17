# 一键启动开发环境：开发库 MySQL 容器 → 升级表结构 → 后端（新窗口）→ 前端（新窗口）→ 打开浏览器。
# 由同目录的 dev-start.bat 调用（双击 .bat 即可）；已在运行的部分会跳过，重复执行不会多开。
# 前提：已按 README 第 16 节建好 clipsync-dev-mysql 容器、backend/.venv、backend/.env 与 frontend/node_modules。

# PowerShell 5.1 在 Stop 模式下会把原生命令写 stderr 当成错误中断脚本，这里统一按退出码判断
$ErrorActionPreference = 'Continue'
$Root = $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$Python = Join-Path $Backend '.venv\Scripts\python.exe'
$DbContainer = 'clipsync-dev-mysql'
$DockerDesktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'

function Fail($msg) {
    Write-Host "`n[失败] $msg" -ForegroundColor Red
    exit 1
}

function Test-Port($port) {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Test-Docker {
    docker info *> $null
    $LASTEXITCODE -eq 0
}

# 先检查本机环境是否齐全，缺什么直接说清楚
if (-not (Test-Path $Python)) { Fail "找不到 backend\.venv，请先按 README 第 16 节创建后端虚拟环境" }
if (-not (Test-Path (Join-Path $Backend '.env'))) { Fail "找不到 backend\.env，请先按 README 第 16 节创建" }
if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) { Fail "找不到 frontend\node_modules，请先在 frontend 目录运行 npm install" }

# 1. Docker
Write-Host '[1/5] 检查 Docker ...'
if (-not (Test-Docker)) {
    if (-not (Test-Path $DockerDesktop)) { Fail 'Docker 没有运行，也找不到 Docker Desktop，请手动启动 Docker' }
    Write-Host '      Docker 没有运行，正在打开 Docker Desktop（首次启动约需 1 分钟）...'
    Start-Process $DockerDesktop
    $deadline = (Get-Date).AddSeconds(180)
    while (-not (Test-Docker)) {
        if ((Get-Date) -gt $deadline) { Fail 'Docker Desktop 3 分钟内没有就绪，请确认它已正常启动后重试' }
        Start-Sleep -Seconds 3
    }
}
Write-Host '      Docker 已就绪'

# 2. 开发库容器
Write-Host "[2/5] 启动数据库容器 $DbContainer ..."
$state = docker inspect -f '{{.State.Status}}' $DbContainer 2>$null
if ($LASTEXITCODE -ne 0) { Fail "找不到容器 $DbContainer，请先按 README 第 16 节「创建数据库」创建" }
if ($state -ne 'running') { docker start $DbContainer | Out-Null }
# mysqladmin ping 在服务可连接时返回 0（无需密码），等它就绪再迁移
$deadline = (Get-Date).AddSeconds(60)
while ($true) {
    docker exec $DbContainer mysqladmin ping -h 127.0.0.1 --silent *> $null
    if ($LASTEXITCODE -eq 0) { break }
    if ((Get-Date) -gt $deadline) { Fail '数据库 60 秒内没有就绪，可用 docker logs clipsync-dev-mysql 查看原因' }
    Start-Sleep -Seconds 2
}
Write-Host '      数据库已就绪'

# 3. 表结构升级到最新（已是最新时什么都不做）
Write-Host '[3/5] 升级数据库表结构 ...'
Push-Location $Backend
try {
    & $Python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { Fail '表结构升级失败，见上方输出' }
} finally {
    Pop-Location
}

# 4. 后端：在 backend 目录运行，代码改动自动重载
Write-Host '[4/5] 启动后端 ...'
if (Test-Port 8000) {
    Write-Host '      8000 端口已在使用，视为后端已在运行，跳过'
} else {
    Start-Process powershell -WorkingDirectory $Backend -ArgumentList @(
        '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command',
        "`$Host.UI.RawUI.WindowTitle = 'ClipSync backend'; & '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
    )
}

# 5. 前端：在 frontend 目录运行 Vite 开发服务器（npm.cmd 避开 npm.ps1 的执行策略限制）
Write-Host '[5/5] 启动前端 ...'
if (Test-Port 3000) {
    Write-Host '      3000 端口已在使用，视为前端已在运行，跳过'
} else {
    Start-Process powershell -WorkingDirectory $Frontend -ArgumentList @(
        '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command',
        "`$Host.UI.RawUI.WindowTitle = 'ClipSync frontend'; npm.cmd run dev"
    )
}

# 等前后端端口都起来再打开浏览器
$deadline = (Get-Date).AddSeconds(60)
while (-not ((Test-Port 8000) -and (Test-Port 3000))) {
    if ((Get-Date) -gt $deadline) { Fail '前端或后端 60 秒内没有启动，请查看 ClipSync backend / ClipSync frontend 窗口里的报错' }
    Start-Sleep -Seconds 1
}
Start-Process 'http://localhost:3000'

Write-Host "`n[完成] 开发环境已启动：http://localhost:3000" -ForegroundColor Green
Write-Host '      后端、前端各在一个窗口里运行，关闭那个窗口即停止对应程序；数据库容器在后台运行。'
