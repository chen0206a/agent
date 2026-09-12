$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend')
$env:NEXT_TELEMETRY_DISABLED = '1'
& npm run start
exit $LASTEXITCODE
