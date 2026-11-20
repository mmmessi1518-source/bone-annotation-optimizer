param([string]$Python = 'python', [switch]$Labelme)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & $Python -s -m unittest discover -s tests -p 'test_*.py' -v
    if ($LASTEXITCODE -ne 0) { throw '自动测试未通过，停止发布。' }
    if ($Labelme) {
        & $Python -s tests/verify_labelme.py
        if ($LASTEXITCODE -ne 0) { throw 'Labelme 兼容性检查未通过。' }
    }
} finally { Pop-Location }
