param([ValidateSet('Verify', 'Configure')][string]$Operation = 'Verify')

$ErrorActionPreference = 'Stop'
$env:GCM_INTERACTIVE = 'Never'
$env:GIT_TERMINAL_PROMPT = '0'
$credentialLines = "protocol=https`nhost=github.com`n`n" | git credential fill 2>$null
$credential = @{}
foreach ($line in $credentialLines) {
    $parts = $line -split '=', 2
    if ($parts.Length -eq 2) { $credential[$parts[0]] = $parts[1] }
}
if (-not $credential.ContainsKey('password')) { throw 'Git Credential Manager has no GitHub credential.' }
$headers = @{
    Authorization = 'Bearer ' + $credential.password
    'User-Agent' = 'archsearch-repository-setup'
    'X-GitHub-Api-Version' = '2022-11-28'
    Accept = 'application/vnd.github+json'
}
function Invoke-GitHub([string]$Method, [string]$Endpoint, $Body = $null) {
    $parameters = @{ Method = $Method; Uri = 'https://api.github.com' + $Endpoint; Headers = $headers }
    if ($null -ne $Body) {
        $parameters.Body = ConvertTo-Json $Body -Depth 20 -Compress
        $parameters.ContentType = 'application/json'
    }
    try { Invoke-RestMethod @parameters }
    catch { throw "GitHub $Method $Endpoint failed (HTTP $([int]$_.Exception.Response.StatusCode))." }
}
try {
    $profile = Invoke-GitHub 'GET' '/user'
    if ($profile.login -ne 'MAK1MAAaa') { throw 'Credential identity does not match the repository owner.' }
    $root = '/repos/MAK1MAAaa/ai-arch-proj'
    if ($Operation -eq 'Configure') {
        $null = Invoke-GitHub 'PATCH' $root @{
            allow_auto_merge = $true; allow_squash_merge = $true
            allow_merge_commit = $false; allow_rebase_merge = $false; delete_branch_on_merge = $false
        }
        $null = Invoke-GitHub 'PUT' ($root + '/actions/permissions/workflow') @{
            default_workflow_permissions = 'read'; can_approve_pull_request_reviews = $true
        }
        $null = Invoke-GitHub 'PUT' ($root + '/branches/main/protection') @{
            required_status_checks = @{ strict = $true; contexts = @('quality-gate') }
            enforce_admins = $true; restrictions = $null
            required_pull_request_reviews = @{
                dismiss_stale_reviews = $true; require_code_owner_reviews = $false
                required_approving_review_count = 1; require_last_push_approval = $true
            }
            required_linear_history = $true; allow_force_pushes = $false; allow_deletions = $false
            required_conversation_resolution = $true
        }
    }
    $repository = Invoke-GitHub 'GET' $root
    $permissions = Invoke-GitHub 'GET' ($root + '/actions/permissions/workflow')
    $protection = Invoke-GitHub 'GET' ($root + '/branches/main/protection')
    [pscustomobject]@{
        login = $profile.login; autoMerge = $repository.allow_auto_merge
        defaultWorkflowPermissions = $permissions.default_workflow_permissions
        botCanApprove = $permissions.can_approve_pull_request_reviews
        requiredChecks = $protection.required_status_checks.contexts
        requiredReviews = $protection.required_pull_request_reviews.required_approving_review_count
        requireLastPushApproval = $protection.required_pull_request_reviews.require_last_push_approval
        dismissStaleReviews = $protection.required_pull_request_reviews.dismiss_stale_reviews
        enforceAdmins = $protection.enforce_admins.enabled
        strictChecks = $protection.required_status_checks.strict
        allowForcePush = $protection.allow_force_pushes.enabled
        allowDeletion = $protection.allow_deletions.enabled
    } | ConvertTo-Json -Depth 4
}
finally {
    $credential.Clear()
    $headers.Clear()
    $credentialLines = $null
}
