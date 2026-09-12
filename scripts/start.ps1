$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Run the installation steps in README.md first.'
}
& $pythonPath -m app.cli init-db
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath -m app.cli seed
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
