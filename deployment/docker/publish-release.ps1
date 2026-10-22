<#
.SYNOPSIS
  把已经测试通过的构建晋级为正式版本，生成发布到 GitHub Release 的文件。

.DESCRIPTION
  不重新构建镜像：给 build-release.ps1 为某个提交构建、已经测试过的 clipsync-backend / clipsync-frontend
  镜像追加版本号标签，再导出镜像包、生成部署包和校验文件。build-release.ps1 的标签规范不变，
  latest 标签不动、也不放进发布包。

  对应关系：Git 标签 v<版本号> → 提交 → 镜像 <镜像名>:<提交号>（build-release.ps1 打的标签）。
  开始前要求：
    - 已在要发布的提交上建好 Git 标签 v<版本号>，且这个提交在 master 上
    - 本机有这个提交的镜像（被清理过时，先用 docker load 导入 release\<提交号>\ 里的测试镜像包）

  产物放在项目根目录的 release\<版本号>\（已 gitignore）：
    clipsync-images-<版本号>.tar.gz   镜像包：backend、frontend（各带 <版本号> 和 <提交号> 两个标签）、MySQL
    clipsync-deploy-<版本号>.tar.gz   部署包：文件与 build-release.ps1 相同，取自标签对应的提交；
                                      .env.example 的 CLIPSYNC_TAG 预填 <版本号>，VERSION 增加 version= 与 published=
    SHA256SUMS                         两个包的 SHA-256，下载后在同一目录执行 sha256sum -c SHA256SUMS 核对
  不做任何远程操作：结束时打印推送标签、发布到 GitHub 的步骤，由人工执行。

.PARAMETER Version
  版本号，不带 v，如 1.0.0、1.0.0-alpha.1。

.PARAMETER Yes
  跳过确认提示（release\<版本号>\ 已存在时直接覆盖）。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deployment\docker\publish-release.ps1 -Version 1.0.0-alpha.1
#>
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"

# 与 build-release.ps1 一致
$Platform = "linux/amd64"
# 正式版本只从这个分支发布
$MainBranch = "master"
# 部署包内容与 build-release.ps1 的 $DeployFiles 保持一致：deployment/docker 下的文件，加上 DEPLOYMENT.md 和 VERSION
$DeployFiles = @(
    "docker-compose.yml", "docker-compose.https.yml", "docker-compose.build.yml",
    "nginx-docker.conf", "nginx-https.conf", "nginx-common.conf",
    ".env.example", "backup.sh", "health_check.sh", "cert.sh",
    "clipsync.cron", "clipsync.logrotate"
)
$Apps = @("clipsync-backend", "clipsync-frontend")
# SemVer：主.次.修订，可带预发布后缀（如 -alpha.1）
$VersionPattern = '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$'
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

function Get-NativeValue {
    # 取原生命令的单行输出；命令失败时返回 $null（如标签、镜像不存在）
    param([string]$File, [string[]]$Arguments)
    try {
        return ("" + (Invoke-Native $File ($Arguments + @()) 2>$null)).Trim()
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
    # 与 build-release.ps1 相同：docker save 的 tar 压成 gzip，docker load 可以直接读取 .tar.gz
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
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ("clipsync-publish-" + [guid]::NewGuid().ToString("N"))

try {
    Write-Step "检查要发布的版本"
    if ($Version.StartsWith("v")) {
        throw "版本号不要带 v：写 $($Version.Substring(1))（Git 标签才带 v）"
    }
    if ($Version -notmatch $VersionPattern) {
        throw "版本号格式不对：$Version（应为 1.0.0 或 1.0.0-alpha.1 这样的格式）"
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "未找到 git 命令"
    }
    if (-not (Test-Path $Tar)) {
        throw "未找到 $Tar（需要 Windows 10 1803 或更新版本）"
    }
    $GitTag = "v$Version"
    $FullCommit = Get-NativeValue git @("rev-parse", "--verify", "$GitTag^{commit}")
    if (-not $FullCommit) {
        throw "找不到 Git 标签 $GitTag：先在要发布的提交上建标签（git tag -a $GitTag <提交号> -m `"说明`"），git tag -l 可列出已有标签"
    }
    $Commit = $FullCommit.Substring(0, 12)
    $Subject = Get-NativeValue git @("log", "-1", "--format=%s", $FullCommit)
    try {
        Invoke-Native git @("merge-base", "--is-ancestor", $FullCommit, $MainBranch) 2>$null
    } catch {
        throw "标签 $GitTag 指向的提交 $Commit 不在 $MainBranch 上：正式版本只从 $MainBranch 发布"
    }
    Write-Host "  版本：  $Version（Git 标签 $GitTag）"
    Write-Host "  提交：  $Commit  $Subject"

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

    Write-Step "核对测试过的镜像"
    foreach ($app in $Apps) {
        $image = "${app}:$Commit"
        $id = Get-NativeValue docker @("image", "inspect", "--format", "{{.Id}}", $image)
        if (-not $id) {
            throw "本机没有镜像 $image：先导入测试时的镜像包（docker load -i release\$Commit\clipsync-images-$Commit.tar.gz；用 -AppOnly 打的包文件名是 clipsync-images-$Commit-app.tar.gz），不要重新构建"
        }
        # build-release.ps1 构建时写入的提交号，确认这个标签下确实是该提交构建的镜像。
        # 用 json 输出再解析：PowerShell 5.1 传给原生命令的参数里的双引号会被去掉，模板里不能带引号
        $labels = Get-NativeValue docker @("image", "inspect", "--format", "{{json .Config.Labels}}", $image)
        $revision = $null
        if ($labels -and $labels -ne "null") {
            $revision = ($labels | ConvertFrom-Json).'org.opencontainers.image.revision'
        }
        if ($revision -ne $Commit) {
            throw "镜像 $image 记录的提交是「$revision」，不是 $Commit：这个镜像不是由 build-release.ps1 为该提交构建的"
        }
        Write-Host "  $image  提交 $revision"
    }

    $ReleaseDir = Join-Path $ProjectRoot "release"
    $OutDir = Join-Path $ReleaseDir $Version
    if ((Test-Path $OutDir) -and -not $Yes) {
        Write-Warning "$OutDir 已存在，继续会覆盖里面的发布文件"
        $answer = Read-Host "确认覆盖？输入 y 继续，其他任意键取消"
        if ($answer -ne "y") {
            Write-Host "已取消"
            return
        }
    }

    Write-Step "导出标签对应的代码"
    $Src = Join-Path $Work "src"
    New-Item -ItemType Directory -Path $Src | Out-Null
    $srcTar = Join-Path $Work "src.tar"
    # core.autocrlf=false：导出的文件保持仓库里的 LF 换行，不受 Windows 工作区 CRLF 影响
    Invoke-Native git @("-c", "core.autocrlf=false", "archive", "--format=tar", "-o", $srcTar, $FullCommit)
    Invoke-Native $Tar @("-xf", $srcTar, "-C", $Src)
    $DockerDir = Join-Path $Src "deployment\docker"

    # MySQL 版本以标签对应提交的 docker-compose.yml 为准；本机没有时才下载
    $Mysql = Get-ImageFromFile (Join-Path $DockerDir "docker-compose.yml") '^\s*image:\s*(mysql:\S+)' "MySQL"
    if (-not (Get-NativeValue docker @("image", "inspect", "--format", "{{.Id}}", $Mysql))) {
        Write-Step "下载 $Mysql"
        Invoke-Native docker @("pull", "--platform", $Platform, $Mysql)
    }

    Write-Step "追加版本号标签"
    $images = @()
    foreach ($app in $Apps) {
        Invoke-Native docker @("tag", "${app}:$Commit", "${app}:$Version")
        Write-Host "  ${app}:$Commit → ${app}:$Version"
        $images += @("${app}:$Version", "${app}:$Commit")
    }
    $images += $Mysql
    $Stage = Join-Path $Work "out"
    New-Item -ItemType Directory -Path $Stage | Out-Null

    Write-Step "导出镜像并压缩（需要几分钟）"
    $imagesTar = Join-Path $Work "images.tar"
    # 与 build-release.ps1 相同：CLI 支持时用 --platform 只导出 amd64（containerd 镜像存储下需要）
    $saveArgs = @("save", "-o", $imagesTar)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $saveHelp = (& docker save --help 2>&1 | Out-String)
    $ErrorActionPreference = $previous
    if ($saveHelp -match "--platform") {
        $saveArgs += @("--platform", $Platform)
    }
    Invoke-Native docker ($saveArgs + $images)
    # 镜像 ID 取自导出包的 manifest.json（镜像配置的摘要）：服务器上 docker images 显示的 IMAGE ID 就是它。
    # 本机启用 containerd 镜像存储时 docker images 显示的是另一种摘要，与服务器对不上，不用于核对
    Invoke-Native $Tar @("-xf", $imagesTar, "-C", $Work, "manifest.json")
    $manifest = [System.IO.File]::ReadAllText((Join-Path $Work "manifest.json"), $Utf8NoBom) | ConvertFrom-Json
    $imageIdLines = @()
    foreach ($entry in $manifest) {
        $configId = ($entry.Config -replace '^.*sha256[:/]', '' -replace '\.json$', '').Substring(0, 12)
        $imageIdLines += ("  {0}  {1}" -f $configId, ($entry.RepoTags -join ", "))
    }
    $imagesName = "clipsync-images-$Version.tar.gz"
    Compress-Gzip $imagesTar (Join-Path $Stage $imagesName)

    Write-Step "生成部署包"
    $Deploy = Join-Path $Work "deploy"
    New-Item -ItemType Directory -Path $Deploy | Out-Null
    foreach ($name in $DeployFiles) {
        Copy-Item -LiteralPath (Join-Path $DockerDir $name) -Destination $Deploy
    }
    Copy-Item -LiteralPath (Join-Path $Src "deployment\DEPLOYMENT.md") -Destination $Deploy
    # 发布包里没有 latest 标签：.env.example 预填版本号，照模板复制出的 .env 直接使用这个版本
    $envPath = Join-Path $Deploy ".env.example"
    $envText = [System.IO.File]::ReadAllText($envPath, $Utf8NoBom)
    $tagLine = [regex]'(?m)^CLIPSYNC_TAG=.*$'
    if ($tagLine.Matches($envText).Count -ne 1) {
        throw ".env.example 里应该恰好有一行 CLIPSYNC_TAG="
    }
    $envText = $tagLine.Replace($envText, "CLIPSYNC_TAG=$Version")
    [System.IO.File]::WriteAllText($envPath, $envText, $Utf8NoBom)
    # VERSION：在 build-release.ps1 的字段上增加 version= 与 published=；
    # latest=no 表示这个发布包里的镜像不带 latest 标签，built= 取镜像的构建时间
    $created = Get-NativeValue docker @("image", "inspect", "--format", "{{.Created}}", "clipsync-backend:$Commit")
    # Docker 的时间带 9 位小数秒，.NET 最多解析 7 位，去掉小数部分再解析
    $built = ([DateTimeOffset]::Parse(($created -replace '\.\d+', ''))).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss zzz")
    $versionText = @(
        "version=$Version",
        "commit=$Commit",
        "branch=$MainBranch",
        "latest=no",
        "built=$built",
        "published=$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'))"
    ) -join "`n"
    [System.IO.File]::WriteAllText((Join-Path $Deploy "VERSION"), "$versionText`n", $Utf8NoBom)
    $deployName = "clipsync-deploy-$Version.tar.gz"
    $packNames = @($DeployFiles + @("DEPLOYMENT.md", "VERSION"))
    Invoke-Native $Tar (@("-czf", (Join-Path $Stage $deployName), "-C", $Deploy) + $packNames)

    Write-Step "生成 SHA256SUMS"
    # sha256sum 的格式（哈希 + 两个空格 + 文件名，LF 换行），Linux 上 sha256sum -c 可以直接核对
    $sums = foreach ($name in @($imagesName, $deployName)) {
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Stage $name)).Hash.ToLower()
        "$hash  $name"
    }
    [System.IO.File]::WriteAllText((Join-Path $Stage "SHA256SUMS"), (($sums -join "`n") + "`n"), $Utf8NoBom)

    # 全部生成成功后才替换 release\<版本号>\，中途失败不会留下不完整的发布文件
    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
    if (Test-Path $OutDir) {
        Remove-Item -Recurse -Force $OutDir
    }
    Move-Item -LiteralPath $Stage -Destination $OutDir

    Write-Host ""
    Write-Host "完成：版本 $Version，提交 $Commit（没有重新构建镜像）" -ForegroundColor Green
    Write-Host "镜像包含：$($images -join ', ')"
    foreach ($name in @($imagesName, $deployName, "SHA256SUMS")) {
        $file = Join-Path $OutDir $name
        Write-Host ("  {0}  ({1:N1} MB)" -f $file, ((Get-Item $file).Length / 1MB))
    }
    foreach ($line in $sums) {
        Write-Host "  $line" -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "镜像 ID（与服务器上测试版本的 docker images clipsync-backend / clipsync-frontend 对照，应完全相同）："
    foreach ($line in $imageIdLines) {
        Write-Host $line
    }
    Write-Host ""
    Write-Host "发布到 GitHub（本脚本不做远程操作，以下步骤请自己执行）：" -ForegroundColor Yellow
    Write-Host "  1. 推送 master 与标签：git push origin $MainBranch $GitTag"
    Write-Host "  2. 在 GitHub 仓库页面 Releases → Draft a new release，Choose a tag 选 $GitTag"
    Write-Host "  3. 标题与正文用 release-notes\$GitTag.md；版本号带 - 后缀（如 -alpha.1）时勾选 Set as a pre-release"
    Write-Host "  4. 上传 $OutDir 里的三个文件，然后 Publish release"
} finally {
    Pop-Location
    Remove-Item -Recurse -Force $Work -ErrorAction SilentlyContinue
}
