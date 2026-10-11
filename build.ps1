param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonPath = if ([System.IO.Path]::IsPathRooted($Python)) { $Python } else { Join-Path $projectRoot $Python }
if (-not (Test-Path -LiteralPath $pythonPath)) { throw "Python environment not found: $pythonPath" }

Push-Location $projectRoot
try {
    if (-not $SkipInstall) {
        & $pythonPath -m pip install -e . -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    }
    & $pythonPath -m PyInstaller --noconfirm --clean `
        --distpath dist --workpath build\work packaging\MT5Workbench.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $exePath = Join-Path $projectRoot "dist\MT5Workbench.exe"
    $readmePath = Join-Path $projectRoot "dist\README-package.txt"
    Copy-Item -LiteralPath (Join-Path $projectRoot "README-package.txt") -Destination $readmePath
    & $pythonPath scripts\export_branding.py
    if ($LASTEXITCODE -ne 0) { throw "Branding export failed." }
    $logoZipPath = Join-Path $projectRoot "dist\MT5Workbench-Logo.zip"
    Compress-Archive -LiteralPath (Join-Path $projectRoot "build\branding") -DestinationPath $logoZipPath -Force
    $zipPath = Join-Path $projectRoot "dist\MT5Workbench-Windows-x64.zip"
    Compress-Archive -LiteralPath @($exePath, $readmePath) -DestinationPath $zipPath -Force
    $hashLines = foreach ($artifact in @($exePath, $zipPath, $logoZipPath)) {
        $hash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $([System.IO.Path]::GetFileName($artifact))"
    }
    $hashLines | Set-Content -LiteralPath (Join-Path $projectRoot "dist\SHA256SUMS.txt") -Encoding ascii
    Write-Output "Single-file EXE ready: $exePath"
    Write-Output "Package ready: $zipPath"
    Write-Output "Logo package ready: $logoZipPath"
}
finally { Pop-Location }
