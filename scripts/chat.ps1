param(
    [string]$Message = 'Cancel my order 1001 and request a refund',
    [Nullable[int]]$OrderId = $null,
    [Nullable[int]]$ParentRunId = $null,
    [string]$IdempotencyKey = ([guid]::NewGuid().ToString()),
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    $Session,
    [string]$CsrfToken = '',
    [string]$OutputPath = '',
    [switch]$EvidenceProvided
)
$ErrorActionPreference = 'Stop'
$headers = @{}
if ($CsrfToken) { $headers['X-CSRF-Token'] = $CsrfToken }
$sessionOptions = @{}
if ($Session) { $sessionOptions['WebSession'] = $Session }
$body = @{ message=$Message; idempotency_key=$IdempotencyKey; evidence_provided=[bool]$EvidenceProvided }
if ($null -ne $OrderId) { $body.order_id = $OrderId }
if ($null -ne $ParentRunId) { $body.parent_run_id = $ParentRunId }
$bytes = [System.Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json))
$response = Invoke-WebRequest @sessionOptions -UseBasicParsing -Method Post -Uri "$BaseUrl/agent/runs" -Headers $headers `
    -ContentType 'application/json; charset=utf-8' -Body $bytes -TimeoutSec 210
# Windows PowerShell 5.1 can decode JSON without a response charset as Latin-1.
# Decode the original response bytes explicitly as UTF-8.
$response.RawContentStream.Position = 0
$reader = [System.IO.StreamReader]::new($response.RawContentStream, [System.Text.Encoding]::UTF8)
try { $result = $reader.ReadToEnd() | ConvertFrom-Json }
finally { $reader.Dispose() }
$json = $result | ConvertTo-Json -Depth 100
if ($OutputPath) {
    [System.IO.File]::WriteAllText($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath), $json, [System.Text.UTF8Encoding]::new($false))
}
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$json
