param([string]$BaseUrl = 'http://127.0.0.1:8000')
$ErrorActionPreference = 'Stop'
Write-Output 'Log in as customer6 for the high-amount demo.'
$customerAuth = & (Join-Path $PSScriptRoot 'login.ps1') -BaseUrl $BaseUrl
Write-Output 'Log in as admin to review and simulate execution.'
$adminAuth = & (Join-Path $PSScriptRoot 'login.ps1') -BaseUrl $BaseUrl
$customerHeaders = @{ 'X-CSRF-Token' = $customerAuth.CsrfToken }
$adminHeaders = @{ 'X-CSRF-Token' = $adminAuth.CsrfToken }
function Invoke-DemoPost([string]$Path, [hashtable]$Body, [hashtable]$Headers) {
    $session = if ($Headers -eq $customerHeaders) { $customerAuth.Session } else { $adminAuth.Session }
    $jsonBytes = [System.Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 10))
    Invoke-RestMethod -WebSession $session -Method Post -Uri "$BaseUrl$Path" -Headers $Headers `
        -ContentType 'application/json; charset=utf-8' -Body $jsonBytes
}
$order = Invoke-RestMethod -Uri "$BaseUrl/orders/1006" -WebSession $customerAuth.Session -Headers $customerHeaders
if ($order.status -eq 'CANCELLED') {
    Write-Output 'Order 1006 was already cancelled. Existing results:'
    Invoke-RestMethod -Uri "$BaseUrl/orders/1006/refunds" -WebSession $customerAuth.Session -Headers $customerHeaders | ConvertTo-Json -Depth 10
    exit 0
}
$ticket = Invoke-DemoPost '/tickets' @{
    user_id = 6; order_id = 1006; issue_type = 'CANCEL'; description = 'Demo: cancel high-value order'
} $customerHeaders
$action = Invoke-DemoPost '/actions' @{
    ticket_id = $ticket.id; proposed_action = 'CANCEL_AND_REFUND'; idempotency_key = "demo-order1006-ticket-$($ticket.id)"
} $customerHeaders
Write-Output "Policy: $($action.decision); amount: $($action.amount); execution: $($action.execution_status)"
if ($action.execution_status -ne 'WAITING_APPROVAL') {
    $action | ConvertTo-Json -Depth 10
    exit 1
}
$approvals = Invoke-RestMethod -Uri "$BaseUrl/approvals?status=PENDING&limit=100" -WebSession $adminAuth.Session -Headers $adminHeaders
$approval = $approvals | Where-Object { $_.action_request_id -eq $action.id } | Select-Object -First 1
if (-not $approval) { throw 'Approval was not found.' }
$review = Invoke-DemoPost "/approvals/$($approval.id)/review" @{
    approve = $true; reason = 'Demo reviewer checked the request'
} $adminHeaders
Write-Output "Approval: $($review.status)"
$executed = Invoke-DemoPost "/actions/$($action.id)/simulate-execution" @{ outcome = 'SUCCESS' } $adminHeaders
Write-Output "Execution: $($executed.execution_status); final action: $($executed.final_action)"
Invoke-RestMethod -Uri "$BaseUrl/actions/$($action.id)/audit" -WebSession $adminAuth.Session -Headers $adminHeaders | ConvertTo-Json -Depth 10
