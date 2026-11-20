param([string]$Python = 'python', [string]$Iscc = '', [switch]$Installer)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & $PSScriptRoot/test.ps1 -Python $Python
    $version = (& $Python -s -c 'from bone_optimizer import __version__; print(__version__)').Trim()
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw '无法读取版本号。' }
    $commit = (& git rev-parse HEAD 2>$null)
    if ($LASTEXITCODE -ne 0) { throw '请先创建源码 Git 提交再打包。' }
    $changes = (& git status --porcelain --untracked-files=normal)
    if ($changes) { throw '源码有未提交修改，请先提交，以保证安装包可追溯。' }
    $destination = Join-Path $projectRoot "releases/$version"
    if (Test-Path -LiteralPath $destination) { throw '此版本发布目录已存在，请升级版本号或归档旧构建后重试。' }
    & $Python -s -m PyInstaller --noconfirm packaging/optimizer.spec
    if ($LASTEXITCODE -ne 0) { throw '独立程序打包失败。' }
    $appFolder = Join-Path $projectRoot 'dist/BoneAnnotationOptimizer'
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    $manifest = [ordered]@{version=$version; source_commit=$commit; built_at=(Get-Date).ToUniversalTime().ToString('o'); platform='windows-x64'}
    $manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $appFolder 'version.json') -Encoding UTF8
    Copy-Item -LiteralPath 'README.md','使用说明.md','CHANGELOG.md','THIRD_PARTY.md' -Destination $appFolder
    $probe = Start-Process -FilePath (Join-Path $appFolder 'BoneAnnotationOptimizer.exe') -ArgumentList '--self-test' -WindowStyle Hidden -Wait -PassThru
    if ($probe.ExitCode -ne 0) { throw '独立程序自检失败，停止发布。' }
    & (Join-Path $appFolder 'BoneAnnotationOptimizer-cli.exe') --help
    if ($LASTEXITCODE -ne 0) { throw '独立 CLI 检查失败。' }
    Compress-Archive -LiteralPath $appFolder -DestinationPath (Join-Path $destination "BoneAnnotationOptimizer-$version-portable-win64.zip")
    if ($Installer) {
        if (-not $Iscc) {
            $found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
            if ($found) { $Iscc = $found.Source }
            foreach ($candidate in @('C:/Program Files (x86)/Inno Setup 6/ISCC.exe','C:/Program Files/Inno Setup 6/ISCC.exe')) {
                if (-not $Iscc -and (Test-Path -LiteralPath $candidate)) { $Iscc = $candidate }
            }
        }
        if (-not $Iscc) { throw '已生成便携版；未找到 Inno Setup。使用 -Iscc 指定 ISCC.exe 后重新构建安装包。' }
        & $Iscc "/DAppVersion=$version" "/DReleaseDir=$destination" packaging/installer.iss
        if ($LASTEXITCODE -ne 0) { throw '安装包编译失败。' }
    }
    $manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $destination 'build-info.json') -Encoding UTF8
    Get-ChildItem -LiteralPath $destination -File | Where-Object Name -ne 'SHA256SUMS.txt' | ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $($_.Name)"
    } | Set-Content -LiteralPath (Join-Path $destination 'SHA256SUMS.txt') -Encoding ASCII
    Write-Output "完成：$destination"
} finally { Pop-Location }
