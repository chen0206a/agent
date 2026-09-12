param(
    [Parameter(Mandatory=$true)][int]$RunId,
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    $Session,
    [string]$CsrfToken = '',
    [string]$OutputPath = ''
)
$ErrorActionPreference = 'Stop'
$headers = @{}
if ($CsrfToken) { $headers['X-CSRF-Token'] = $CsrfToken }
$sessionOptions = @{}
if ($Session) { $sessionOptions['WebSession'] = $Session }
$response = Invoke-WebRequest @sessionOptions -UseBasicParsing -Uri "$BaseUrl/agent/runs/$RunId/trace" -Headers $headers -TimeoutSec 30
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
