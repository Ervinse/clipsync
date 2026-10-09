<#
.SYNOPSIS
  在开发机上构建 ClipSync 的 Docker 镜像，打包成可以离线导入服务器的文件。

.DESCRIPTION
  只打包已提交到 git 的代码（git archive），工作区里未提交的改动不会进入镜像。
  产物放在项目根目录的 release/（已 gitignore）：
    clipsync-images-<提交号>.tar.gz   镜像包，服务器上用 docker load -i 导入
    clipsync-deploy-<提交号>.tar.gz   部署包：docker-compose.yml、nginx-docker.conf、.env.example、README.md
  服务器上的步骤见 deployment/docker/README.md「方式 A」。

.PARAMETER Ref
  要打包的 git 提交、分支或标签，默认 HEAD（当前检出的提交）。

.PARAMETER AppOnly
  镜像包只含 clipsync-backend / clipsync-frontend，不含 mysql:8.0 与 alpine。
  服务器已经导入过这两个基础镜像时（日常更新）使用，镜像包更小。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deployment\docker\build-release.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deployment\docker\build-release.ps1 -AppOnly
#>
param(
    [string]$Ref = "HEAD",
    [switch]$AppOnly
)

$ErrorActionPreference = "Stop"

# 服务器为 x86_64：显式指定平台，避免在 ARM 电脑上构建出服务器无法运行的镜像
$Platform = "linux/amd64"
# mysql:8.0 供 db 服务使用；alpine 供宿主机 cron 备份上传文件时使用
$BaseImages = @("mysql:8.0", "alpine:latest")
# Windows 10 1803 起自带的 bsdtar，不依赖 Git Bash 等第三方 tar
$Tar = Join-Path $env:SystemRoot "System32\tar.exe"

function Invoke-Native {
    # PowerShell 5.1 不会因原生命令失败而停止，这里检查退出码；
    # 执行期间临时放宽 ErrorActionPreference，避免 docker 写到 stderr 的进度信息被当成错误
    param([string]$File, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $File @Arguments
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) {
        throw "命令失败（退出码 $LASTEXITCODE）：$File $($Arguments -join ' ')"
    }
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Compress-Gzip {
    # docker save 输出未压缩的 tar；压成 gzip 减小传输体积，docker load 可以直接读取 .tar.gz
    param([string]$Source, [string]$Destination)
    $in = [System.IO.File]::OpenRead($Source)
    try {
        $out = [System.IO.File]::Create($Destination)
        try {
            $gzip = New-Object System.IO.Compression.GZipStream($out, [System.IO.Compression.CompressionMode]::Compress)
            try {
                $in.CopyTo($gzip)
            } finally {
                $gzip.Dispose()
            }
        } finally {
            $out.Dispose()
        }
    } finally {
        $in.Dispose()
    }
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $ProjectRoot
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ("clipsync-release-" + [guid]::NewGuid().ToString("N"))

try {
    Write-Step "检查 git 与 Docker"
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "未找到 git 命令"
    }
    if (-not (Test-Path $Tar)) {
        throw "未找到 $Tar（需要 Windows 10 1803 或更新版本）"
    }
    $Commit = ("" + (Invoke-Native git @("rev-parse", "--short=12", "$Ref^{commit}"))).Trim()
    $dirty = Invoke-Native git @("status", "--porcelain")
    if ($dirty -and $Ref -eq "HEAD") {
        Write-Warning "工作区有未提交的改动，这些改动不会进入镜像（只打包已提交的 $Commit）"
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "未找到 docker 命令：请先安装 Docker Desktop"
    }
    try {
        $osType = ("" + (Invoke-Native docker @("info", "--format", "{{.OSType}}"))).Trim()
    } catch {
        throw "无法连接 Docker：请先启动 Docker Desktop，等它显示 Engine running 后重试"
    }
    if ($osType -ne "linux") {
        throw "Docker 当前不是 Linux 容器模式（OSType=$osType）：在 Docker Desktop 托盘菜单里选择 Switch to Linux containers"
    }
    Write-Host "打包提交 $Commit，目标平台 $Platform"

    Write-Step "导出已提交的代码"
    $Src = Join-Path $Work "src"
    New-Item -ItemType Directory -Path $Src | Out-Null
    $srcTar = Join-Path $Work "src.tar"
    # core.autocrlf=false：导出的文件保持仓库里的 LF 换行，不受 Windows 工作区 CRLF 影响
    Invoke-Native git @("-c", "core.autocrlf=false", "archive", "--format=tar", "-o", $srcTar, $Commit)
    Invoke-Native $Tar @("-xf", $srcTar, "-C", $Src)

    $images = @()
    $apps = @(
        @{ Name = "clipsync-backend"; Context = "backend"; Dockerfile = "Dockerfile.backend" },
        @{ Name = "clipsync-frontend"; Context = "frontend"; Dockerfile = "Dockerfile.frontend" }
    )
    foreach ($app in $apps) {
        Write-Step "构建 $($app.Name)"
        Invoke-Native docker @(
            "build", "--platform", $Platform,
            "-f", (Join-Path $Src "deployment\docker\$($app.Dockerfile)"),
            "-t", "$($app.Name):$Commit",
            "-t", "$($app.Name):latest",
            (Join-Path $Src $app.Context)
        )
        $images += "$($app.Name):$Commit"
        $images += "$($app.Name):latest"
    }

    if (-not $AppOnly) {
        foreach ($image in $BaseImages) {
            Write-Step "下载 $image"
            Invoke-Native docker @("pull", "--platform", $Platform, $image)
            $images += $image
        }
    }

    $ReleaseDir = Join-Path $ProjectRoot "release"
    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
    $suffix = if ($AppOnly) { "$Commit-app" } else { $Commit }

    Write-Step "导出镜像并压缩（需要几分钟）"
    $imagesTar = Join-Path $Work "images.tar"
    # 启用 containerd 镜像存储时（新版 Docker Desktop 默认），docker save 默认导出镜像的所有平台，
    # 而 mysql、alpine 只下载了 amd64，会因缺少其他平台的数据而失败；CLI 支持时用 --platform 只导出 amd64
    $saveArgs = @("save", "-o", $imagesTar)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $saveHelp = (& docker save --help 2>&1 | Out-String)
    $ErrorActionPreference = $previous
    if ($saveHelp -match "--platform") {
        $saveArgs += @("--platform", $Platform)
    }
    Invoke-Native docker ($saveArgs + $images)
    $imagesOut = Join-Path $ReleaseDir "clipsync-images-$suffix.tar.gz"
    Compress-Gzip $imagesTar $imagesOut

    Write-Step "生成部署包"
    $deployOut = Join-Path $ReleaseDir "clipsync-deploy-$Commit.tar.gz"
    Invoke-Native $Tar @(
        "-czf", $deployOut,
        "-C", (Join-Path $Src "deployment\docker"),
        "docker-compose.yml", "nginx-docker.conf", ".env.example", "README.md"
    )

    Write-Host ""
    Write-Host "完成：提交 $Commit" -ForegroundColor Green
    Write-Host "镜像包含：$($images -join ', ')"
    foreach ($file in @($imagesOut, $deployOut)) {
        Write-Host ("  {0}  ({1:N1} MB)" -f $file, ((Get-Item $file).Length / 1MB))
    }
    Write-Host ""
    Write-Host "上传到服务器："
    Write-Host "  scp `"$imagesOut`" `"$deployOut`" root@服务器IP:/root/"
} finally {
    Pop-Location
    Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue
}
