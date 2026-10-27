$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $projectRoot "requirements.txt"
$dependencyStamp = Join-Path $projectRoot ".venv\requirements-installed.txt"
$bridge = Join-Path $projectRoot "powergrid_pipeline\bridge_server.py"
$reportEnv = Join-Path $projectRoot "dianwang_report_gen\.env"
$reportEnvExample = Join-Path $projectRoot "dianwang_report_gen\.env.example"

if (-not (Test-Path -LiteralPath $venvPython)) {
    $pythonVersion = "3.11"
    & py -3.11 --version *> $null
    if ($LASTEXITCODE -ne 0) {
        $pythonVersion = "3.12"
        & py -3.12 --version *> $null
    }
    if ($LASTEXITCODE -ne 0) { throw "Install Python 3.11 or 3.12 (64-bit), then retry." }
    Write-Host "Creating Python $pythonVersion environment..." -ForegroundColor Cyan
    & py "-$pythonVersion" -m venv (Join-Path $projectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }
}

if (-not (Test-Path -LiteralPath $dependencyStamp) -or
    (Get-Item -LiteralPath $requirements).LastWriteTime -gt (Get-Item -LiteralPath $dependencyStamp).LastWriteTime) {
    Write-Host "Installing project dependencies..." -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed. Check the Python and network setup, then retry." }
    & $venvPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Check the Python and network setup, then retry." }
    Set-Content -LiteralPath $dependencyStamp -Value "Installed from requirements.txt" -Encoding utf8
}

if (-not (Test-Path -LiteralPath $reportEnv)) {
    Copy-Item -LiteralPath $reportEnvExample -Destination $reportEnv
    Write-Host "Created dianwang_report_gen\.env. Add model credentials to enable real report generation." -ForegroundColor Yellow
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Set-Location -LiteralPath (Join-Path $projectRoot "powergrid_pipeline")
Write-Host "Opening http://127.0.0.1:8080/ (Mock demo mode)" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor Yellow
& $venvPython -X utf8 $bridge
exit $LASTEXITCODE
