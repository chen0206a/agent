param([string]$BaseUrl = 'http://127.0.0.1:8000')
$ErrorActionPreference = 'Stop'
$credential = Get-Credential -Message 'AfterSale local account'
if (-not $credential) { throw 'Login cancelled.' }
$body = @{ username=$credential.UserName; password=$credential.GetNetworkCredential().Password }
$bytes = [System.Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json))
try {
    $me = Invoke-RestMethod -Method Post -Uri "$BaseUrl/auth/login" -SessionVariable authSession `
        -ContentType 'application/json; charset=utf-8' -Body $bytes
    [PSCustomObject]@{ Session=$authSession; CsrfToken=$me.csrf_token; Username=$me.username }
} finally {
    $body.Clear()
    [Array]::Clear($bytes, 0, $bytes.Length)
    $credential = $null
}
