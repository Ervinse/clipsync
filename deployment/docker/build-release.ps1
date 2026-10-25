<#
.SYNOPSIS
  在开发机上构建 ClipSync 的 Docker 镜像，打包成可以离线导入服务器的文件。

.DESCRIPTION
  只打包已提交到 git 的代码（git archive），工作区里未提交的改动不会进入镜像。
  开始前显示要打包的分支与提交；不是 master 的最新提交、或工作区有未提交改动时，要求确认。

  镜像标签：
    <提交号>   每次都打
    latest     只有打包的是 master 的最新提交时才打。服务器 .env 默认 CLIPSYNC_TAG=latest，
               所以测试分支的镜像导入服务器后不会被误用，要用时需把 CLIPSYNC_TAG 改成提交号。

  产物放在项目根目录的 release\<提交号>\（已 gitignore）：
    clipsync-images-<提交号>[-app].tar.gz   镜像包，服务器上用 docker load -i 导入
    clipsync-deploy-<提交号>.tar.gz         部署包：compose、Nginx 配置、运维脚本、DEPLOYMENT.md、VERSION
  后端镜像里另有 /app/BUILD_INFO（提交号、分支、构建时间），管理后台「系统信息」据此显示。
  服务器上的步骤见 deployment/DEPLOYMENT.md。测试通过后用 publish-release.ps1 晋级为正式版本。

.PARAMETER Ref
  要打包的 git 提交、分支或标签，默认 HEAD（当前检出的提交）。

.PARAMETER AppOnly
  镜像包不含 MySQL 镜像，只含 clipsync-backend / clipsync-frontend。
  服务器上已有 docker-compose.yml 指定版本的 MySQL 镜像时（日常更新）使用，镜像包更小。

.PARAMETER WithCertbot
  镜像包额外包含 certbot 镜像（cert.sh 申请 HTTPS 证书用），服务器拉取不到 Docker Hub 时使用。

.PARAMETER Yes
  跳过确认提示（非 master 最新提交、工作区有未提交改动时）。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deployment\docker\build-release.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deployment\docker\build-release.ps1 -AppOnly
#>
param(
    [string]$Ref = "HEAD",
    [switch]$AppOnly,
    [switch]$WithCertbot,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"

# 服务器为 x86_64：显式指定平台，避免在 ARM 电脑上构建出服务器无法运行的镜像
$Platform = "linux/amd64"
# 只有这个分支的最新提交会打 latest 标签
$MainBranch = "master"
# 部署包内容：deployment/docker 下的文件，加上 deployment/DEPLOYMENT.md 和生成的 VERSION
$DeployFiles = @(
    "docker-compose.yml", "docker-compose.https.yml", "docker-compose.build.yml",
    "nginx-docker.conf", "nginx-https.conf", "nginx-common.conf",
    ".env.example", "backup.sh", "health_check.sh", "cert.sh",
    "clipsync.cron", "clipsync.logrotate"
)
# Windows 10 1803 起自带的 bsdtar，不依赖 Git Bash 等第三方 tar
$Tar = Join-Path $env:SystemRoot "System32\tar.exe"
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false

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

function Get-GitValue {
    # 取 git 命令的单行输出；命令失败时返回 $null（如分支不存在）
    param([string[]]$Arguments)
    try {
        return ("" + (Invoke-Native git ($Arguments + @()) 2>$null)).Trim()
    } catch {
        return $null
    }
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-ImageFromFile {
    # 从文件里按正则取镜像名（第一个捕获组），找不到时报错
    param([string]$Path, [string]$Pattern, [string]$What)
    $match = Select-String -Path $Path -Pattern $Pattern | Select-Object -First 1
    if (-not $match) {
        throw "没有在 $Path 里找到 $What 镜像"
    }
    return $match.Matches[0].Groups[1].Value
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
    Write-Step "检查要打包的版本"
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "未找到 git 命令"
    }
    if (-not (Test-Path $Tar)) {
        throw "未找到 $Tar（需要 Windows 10 1803 或更新版本）"
    }
    $FullCommit = Get-GitValue @("rev-parse", "--verify", "$Ref^{commit}")
    if (-not $FullCommit) {
        throw "找不到要打包的提交：$Ref（检查分支名或提交号是否写对，git branch 可列出本地分支）"
    }
    $Commit = $FullCommit.Substring(0, 12)
    $Subject = Get-GitValue @("log", "-1", "--format=%s", $FullCommit)
    if ($Ref -eq "HEAD") {
        $Branch = Get-GitValue @("rev-parse", "--abbrev-ref", "HEAD")
        if ($Branch -eq "HEAD") { $Branch = "（不在任何分支上）" }
    } else {
        $Branch = $Ref
    }
    $MainCommit = Get-GitValue @("rev-parse", "--verify", "$MainBranch^{commit}")
    $IsLatest = ($MainCommit -eq $FullCommit)
    $dirty = ($Ref -eq "HEAD") -and [bool](Invoke-Native git @("status", "--porcelain"))

    Write-Host "  分支：  $Branch"
    Write-Host "  提交：  $Commit  $Subject"
    if ($IsLatest) {
        Write-Host "  标签：  $Commit 和 latest（$MainBranch 的最新提交）" -ForegroundColor Green
    } else {
        Write-Host "  标签：  只有 $Commit（不是 $MainBranch 的最新提交，不打 latest）" -ForegroundColor Yellow
        Write-Host "          服务器要用这个版本时，需把 .env 的 CLIPSYNC_TAG 改成 $Commit"
    }
    $warnings = @()
    if (-not $IsLatest) {
        $warnings += "打包的不是 $MainBranch 的最新提交（正式部署一般用 $MainBranch）"
    }
    if ($dirty) {
        $warnings += "工作区有未提交的改动，这些改动不会进入镜像（只打包已提交的 $Commit）"
    }
    foreach ($w in $warnings) {
        Write-Warning $w
    }
    if ($warnings.Count -gt 0 -and -not $Yes) {
        $answer = Read-Host "确认继续打包？输入 y 继续，其他任意键取消"
        if ($answer -ne "y") {
            Write-Host "已取消"
            return
        }
    }

    Write-Step "检查 Docker"
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "未找到 docker 命令：请先安装 Docker Desktop"
    }
    try {
        $osType = ("" + (Invoke-Native docker @("info", "--format", "{{.OSType}}") 2>$null)).Trim()
    } catch {
        throw "无法连接 Docker：请先启动 Docker Desktop，等它显示 Engine running 后重试"
    }
    if ($osType -ne "linux") {
        throw "Docker 当前不是 Linux 容器模式（OSType=$osType）：在 Docker Desktop 托盘菜单里选择 Switch to Linux containers"
    }

    Write-Step "导出已提交的代码"
    $Src = Join-Path $Work "src"
    New-Item -ItemType Directory -Path $Src | Out-Null
    $srcTar = Join-Path $Work "src.tar"
    # core.autocrlf=false：导出的文件保持仓库里的 LF 换行，不受 Windows 工作区 CRLF 影响
    Invoke-Native git @("-c", "core.autocrlf=false", "archive", "--format=tar", "-o", $srcTar, $FullCommit)
    Invoke-Native $Tar @("-xf", $srcTar, "-C", $Src)
    $DockerDir = Join-Path $Src "deployment\docker"
    # BUILD_INFO：随代码进入后端镜像（/app/BUILD_INFO），后台「系统信息」据此显示提交号、分支与构建时间。
    # 版本号不写在这里：正式版本晋级不重新构建，版本号由服务器 .env 的 CLIPSYNC_TAG 传给后端
    $builtUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [System.Globalization.CultureInfo]::InvariantCulture)
    $buildInfoText = @(
        "commit=$Commit",
        "branch=$Branch",
        "built=$builtUtc"
    ) -join "`n"
    [System.IO.File]::WriteAllText((Join-Path $Src "backend\BUILD_INFO"), "$buildInfoText`n", $Utf8NoBom)

    $images = @()
    $apps = @(
        @{ Name = "clipsync-backend"; Context = "backend"; Dockerfile = "Dockerfile.backend" },
        @{ Name = "clipsync-frontend"; Context = "frontend"; Dockerfile = "Dockerfile.frontend" }
    )
    foreach ($app in $apps) {
        Write-Step "构建 $($app.Name)"
        $buildArgs = @(
            "build", "--platform", $Platform,
            "-f", (Join-Path $DockerDir $app.Dockerfile),
            # health_check.sh 读这个标签，显示服务器上正在运行的是哪个提交
            "--label", "org.opencontainers.image.revision=$Commit",
            "-t", "$($app.Name):$Commit"
        )
        $images += "$($app.Name):$Commit"
        if ($IsLatest) {
            $buildArgs += @("-t", "$($app.Name):latest")
            $images += "$($app.Name):latest"
        }
        Invoke-Native docker ($buildArgs + @((Join-Path $Src $app.Context)))
    }

    # 第三方镜像的版本以打包的提交里的文件为准
    $thirdParty = @()
    if (-not $AppOnly) {
        $thirdParty += Get-ImageFromFile (Join-Path $DockerDir "docker-compose.yml") '^\s*image:\s*(mysql:\S+)' "MySQL"
    }
    if ($WithCertbot) {
        $thirdParty += Get-ImageFromFile (Join-Path $DockerDir "cert.sh") '^CERTBOT_IMAGE="([^"]+)"' "certbot"
    }
    foreach ($image in $thirdParty) {
        Write-Step "下载 $image"
        Invoke-Native docker @("pull", "--platform", $Platform, $image)
        $images += $image
    }

    # 每个提交一个子目录；正式版本由 publish-release.ps1 输出到 release\<版本号>\
    $ReleaseDir = Join-Path $ProjectRoot "release\$Commit"
    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
    $suffix = if ($AppOnly) { "$Commit-app" } else { $Commit }

    Write-Step "导出镜像并压缩（需要几分钟）"
    $imagesTar = Join-Path $Work "images.tar"
    # 启用 containerd 镜像存储时（新版 Docker Desktop 默认），docker save 默认导出镜像的所有平台，
    # 而第三方镜像只下载了 amd64，会因缺少其他平台的数据而失败；CLI 支持时用 --platform 只导出 amd64
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
    $Stage = Join-Path $Work "deploy"
    New-Item -ItemType Directory -Path $Stage | Out-Null
    foreach ($name in $DeployFiles) {
        Copy-Item -LiteralPath (Join-Path $DockerDir $name) -Destination $Stage
    }
    Copy-Item -LiteralPath (Join-Path $Src "deployment\DEPLOYMENT.md") -Destination $Stage
    # VERSION：服务器上 cat VERSION 或 health_check.sh 可以看到部署的是哪个分支、哪个提交
    $versionText = @(
        "commit=$Commit",
        "branch=$Branch",
        "latest=$(if ($IsLatest) { 'yes' } else { 'no' })",
        "built=$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'))"
    ) -join "`n"
    [System.IO.File]::WriteAllText((Join-Path $Stage "VERSION"), "$versionText`n", $Utf8NoBom)
    $deployOut = Join-Path $ReleaseDir "clipsync-deploy-$Commit.tar.gz"
    $packNames = @($DeployFiles + @("DEPLOYMENT.md", "VERSION"))
    Invoke-Native $Tar (@("-czf", $deployOut, "-C", $Stage) + $packNames)

    Write-Host ""
    Write-Host "完成：分支 $Branch，提交 $Commit" -ForegroundColor Green
    Write-Host "镜像包含：$($images -join ', ')"
    foreach ($file in @($imagesOut, $deployOut)) {
        Write-Host ("  {0}  ({1:N1} MB)" -f $file, ((Get-Item $file).Length / 1MB))
    }
    if (-not $IsLatest) {
        Write-Host ""
        Write-Host "注意：这不是 $MainBranch 的最新提交，镜像没有 latest 标签。" -ForegroundColor Yellow
        Write-Host "      服务器导入后，把 .env 的 CLIPSYNC_TAG 改成 $Commit 才会使用这个版本。" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "上传到服务器："
    Write-Host "  scp `"$imagesOut`" `"$deployOut`" root@服务器IP:/root/"
} finally {
    Pop-Location
    Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue
}
