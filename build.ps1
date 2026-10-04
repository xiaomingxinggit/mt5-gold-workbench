param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath((Join-Path $projectRoot $Python))
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found: $pythonPath"
}

Push-Location $projectRoot
try {
    & $pythonPath -m pip install -r requirements.txt -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

    & $pythonPath -m PyInstaller --noconfirm --clean --onedir --windowed `
        --name MT5Workbench --paths (Join-Path $projectRoot "src") `
        --collect-all MetaTrader5 --collect-data mt5_workbench --hidden-import numpy `
        --distpath dist --workpath build\work --specpath build gui.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $releasePath = Join-Path $projectRoot "dist\MT5Workbench"
    # Qt6Core uses the Windows ICU DLL. PyInstaller may pick an unrelated
    # icuuc.dll from PATH (for example Poppler), which breaks Qt at startup.
    $excludedDllPath = Join-Path $projectRoot "build\excluded-dlls"
    foreach ($name in @("icuuc.dll", "icudt78.dll")) {
        $candidate = Join-Path $releasePath "_internal\$name"
        if (Test-Path -LiteralPath $candidate) {
            New-Item -ItemType Directory -Force -Path $excludedDllPath | Out-Null
            Move-Item -LiteralPath $candidate -Destination (Join-Path $excludedDllPath $name) -Force
        }
    }
    Copy-Item -LiteralPath (Join-Path $projectRoot "README-package.txt") -Destination $releasePath
    New-Item -ItemType Directory -Force -Path (Join-Path $releasePath "state\executions") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $releasePath "state\controls") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $releasePath "state\journal") | Out-Null

    $zipPath = Join-Path $projectRoot "dist\MT5Workbench-Windows-x64.zip"
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            Compress-Archive -Path $releasePath -DestinationPath $zipPath -Force -ErrorAction Stop
            break
        }
        catch {
            if ($attempt -eq 5) { throw }
            Start-Sleep -Seconds 2
        }
    }
    Write-Output "Package ready: $zipPath"
}
finally {
    Pop-Location
}
