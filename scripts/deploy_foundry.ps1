[CmdletBinding()]
param(
    [string]$Environment = "foundry-travel-planner",
    [string]$ProjectEndpoint = "https://foundry-sre-project-resource.services.ai.azure.com/api/projects/foundry-sre-project",
    [string]$ProjectId = "/subscriptions/7b43cfa1-da92-48cc-865d-5499466b3b5c/resourceGroups/ninhu-ai-test/providers/Microsoft.CognitiveServices/accounts/foundry-sre-project-resource/projects/foundry-sre-project",
    [string]$AgentName = "travel-planner-langgraph",
    [string]$ResourceGroupName = "ninhu-ai-test",
    [string]$AiAccountName = "foundry-sre-project-resource",
    [string]$AiProjectName = "foundry-sre-project",
    [string]$ModelDeployment = "gpt-5.4-mini",
    [string]$Location = "westus",
    [string]$AiDeploymentsLocation = "swedencentral",
    [string]$Subscription = "7b43cfa1-da92-48cc-865d-5499466b3b5c",
    [string]$AzureTracingGenAiContentRecordingEnabled = "true",
    [string]$OtelSemconvStabilityOptIn = "gen_ai_latest_experimental",
    [string]$OtelInstrumentationGenAiCaptureMessageContent = "SPAN_AND_EVENT",
    [string]$ChaosMode = "off",
    [double]$ChaosRate = 0.1,
    [double]$ChaosLatencyMinSeconds = 5.0,
    [double]$ChaosLatencyMaxSeconds = 20.0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Get-AgentInfo {
    $json = az rest `
        --method get `
        --url "$ProjectEndpoint/agents/$AgentName`?api-version=2025-11-15-preview" `
        --resource "https://ai.azure.com" `
        --headers "Foundry-Features=HostedAgents=V1Preview" `
        -o json
    if ($LASTEXITCODE -ne 0) {
        throw "Could not retrieve Foundry agent '$AgentName'."
    }
    return $json | ConvertFrom-Json
}

function Ensure-FoundryUserRole {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PrincipalId,
        [Parameter(Mandatory = $true)]
        [string]$Scope
    )

    $existing = az role assignment list --assignee $PrincipalId --role "Foundry User" --scope $Scope -o json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw "Could not list role assignments for principal $PrincipalId."
    }
    if ($existing.Count -eq 0) {
        Invoke-Checked { az role assignment create --assignee $PrincipalId --role "Foundry User" --scope $Scope -o none } "Foundry User role assignment for $PrincipalId"
    }
}

if (-not (Get-Command azd -ErrorAction SilentlyContinue)) {
    throw "azd is required. Install Azure Developer CLI first."
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "az is required. Install Azure CLI first."
}

Invoke-Checked { az account set --subscription $Subscription } "Azure subscription selection"

if (-not (Test-Path ".azure\$Environment\.env")) {
    Invoke-Checked { azd env new $Environment --subscription $Subscription --location $Location --no-prompt } "azd environment creation"
} else {
    Invoke-Checked { azd env select $Environment } "azd environment selection"
}

$PrincipalId = az ad signed-in-user show --query id -o tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($PrincipalId)) {
    throw "Could not resolve signed-in Azure user object id."
}

Invoke-Checked { azd env set AZURE_SUBSCRIPTION_ID $Subscription --environment $Environment } "azd env set AZURE_SUBSCRIPTION_ID"
Invoke-Checked { azd env set AZURE_RESOURCE_GROUP $ResourceGroupName --environment $Environment } "azd env set AZURE_RESOURCE_GROUP"
Invoke-Checked { azd env set AZURE_LOCATION $Location --environment $Environment } "azd env set AZURE_LOCATION"
Invoke-Checked { azd env set AZURE_AI_DEPLOYMENTS_LOCATION $AiDeploymentsLocation --environment $Environment } "azd env set AZURE_AI_DEPLOYMENTS_LOCATION"
Invoke-Checked { azd env set AZURE_AI_ACCOUNT_NAME $AiAccountName --environment $Environment } "azd env set AZURE_AI_ACCOUNT_NAME"
Invoke-Checked { azd env set AZURE_AI_PROJECT_NAME $AiProjectName --environment $Environment } "azd env set AZURE_AI_PROJECT_NAME"
Invoke-Checked { azd env set AZURE_AI_PROJECT_ENDPOINT $ProjectEndpoint --environment $Environment } "azd env set AZURE_AI_PROJECT_ENDPOINT"
Invoke-Checked { azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME $ModelDeployment --environment $Environment } "azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME"
Invoke-Checked { azd env set AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED $AzureTracingGenAiContentRecordingEnabled --environment $Environment } "azd env set AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"
Invoke-Checked { azd env set OTEL_SEMCONV_STABILITY_OPT_IN $OtelSemconvStabilityOptIn --environment $Environment } "azd env set OTEL_SEMCONV_STABILITY_OPT_IN"
Invoke-Checked { azd env set OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT $OtelInstrumentationGenAiCaptureMessageContent --environment $Environment } "azd env set OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
Invoke-Checked { azd env set CHAOS_MODE $ChaosMode --environment $Environment } "azd env set CHAOS_MODE"
Invoke-Checked { azd env set CHAOS_RATE $ChaosRate --environment $Environment } "azd env set CHAOS_RATE"
Invoke-Checked { azd env set CHAOS_LATENCY_MIN_SECONDS $ChaosLatencyMinSeconds --environment $Environment } "azd env set CHAOS_LATENCY_MIN_SECONDS"
Invoke-Checked { azd env set CHAOS_LATENCY_MAX_SECONDS $ChaosLatencyMaxSeconds --environment $Environment } "azd env set CHAOS_LATENCY_MAX_SECONDS"
Invoke-Checked { azd env set AZURE_PRINCIPAL_ID $PrincipalId --environment $Environment } "azd env set AZURE_PRINCIPAL_ID"
Invoke-Checked { azd env set AZURE_PRINCIPAL_TYPE "User" --environment $Environment } "azd env set AZURE_PRINCIPAL_TYPE"
Invoke-Checked { azd env set USE_EXISTING_AI_PROJECT "true" --environment $Environment } "azd env set USE_EXISTING_AI_PROJECT"
Invoke-Checked { azd env set ENABLE_HOSTED_AGENTS "true" --environment $Environment } "azd env set ENABLE_HOSTED_AGENTS"
Invoke-Checked { azd env set ENABLE_MONITORING "false" --environment $Environment } "azd env set ENABLE_MONITORING"
Invoke-Checked { azd env set AI_PROJECT_DEPLOYMENTS "[]" --environment $Environment } "azd env set AI_PROJECT_DEPLOYMENTS"
Invoke-Checked { azd env set AI_PROJECT_CONNECTIONS "[]" --environment $Environment } "azd env set AI_PROJECT_CONNECTIONS"
Invoke-Checked { azd env set AI_PROJECT_CONNECTION_CREDENTIALS "{}" --environment $Environment } "azd env set AI_PROJECT_CONNECTION_CREDENTIALS"

if (-not (Test-Path "azure.yaml")) {
    azd ai agent init `
        --manifest "agent.manifest.yaml" `
        --src "." `
        --project-id $ProjectId `
        --model-deployment $ModelDeployment `
        --environment $Environment `
        --no-prompt
}

$azdUpSucceeded = $true
azd up --environment $Environment --no-prompt
if ($LASTEXITCODE -ne 0) {
    $azdUpSucceeded = $false
    Write-Warning "azd up returned exit code $LASTEXITCODE. Checking the current Foundry agent state before failing."
}

$agent = Get-AgentInfo
$latest = $agent.versions.latest
if ($latest.status -ne "active") {
    throw "Foundry agent '$AgentName' is not active. Current status: $($latest.status)"
}
if (-not $azdUpSucceeded) {
    Write-Warning "azd reported a post-create failure, but Foundry reports '$AgentName' version $($latest.version) as active. Continuing with RBAC and smoke test."
}

Invoke-Checked { azd env set AGENT_TRAVEL_PLANNER_LANGGRAPH_NAME $AgentName --environment $Environment } "azd env set agent name"
Invoke-Checked { azd env set AGENT_TRAVEL_PLANNER_LANGGRAPH_VERSION $latest.version --environment $Environment } "azd env set agent version"

$accountId = "/subscriptions/$Subscription/resourceGroups/$ResourceGroupName/providers/Microsoft.CognitiveServices/accounts/$AiAccountName"
$accountIdentity = az resource show --ids $accountId --query identity.principalId -o tsv
if ($LASTEXITCODE -ne 0) {
    throw "Could not resolve AI account managed identity."
}

$principalIds = @(
    $agent.instance_identity.principal_id,
    $agent.blueprint.principal_id,
    $accountIdentity
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique

foreach ($principalId in $principalIds) {
    Ensure-FoundryUserRole -PrincipalId $principalId -Scope $accountId
}

Start-Sleep -Seconds 60

$token = az account get-access-token --resource "https://ai.azure.com" --query accessToken -o tsv
if ($LASTEXITCODE -ne 0) {
    throw "Could not acquire caller token for smoke test."
}

$body = @{
    input = "Give me a concise one day food walk in Vancouver."
    stream = $false
} | ConvertTo-Json -Compress

$headers = @{
    Authorization = "Bearer $token"
    "Foundry-Features" = "HostedAgents=V1Preview"
}

$response = $null
for ($attempt = 1; $attempt -le 3; $attempt++) {
    try {
        $response = Invoke-RestMethod `
            -Uri "$ProjectEndpoint/agents/$AgentName/endpoint/protocols/openai/responses?api-version=2025-11-15-preview" `
            -Method Post `
            -Headers $headers `
            -Body $body `
            -ContentType "application/json" `
            -TimeoutSec 240
        break
    } catch {
        if ($attempt -eq 3) {
            throw
        }
        Write-Warning "Smoke test attempt $attempt failed. Waiting for hosted-agent identity propagation before retrying."
        Start-Sleep -Seconds 60
    }
}

Write-Host "Foundry agent '$AgentName' version $($latest.version) is active."
Write-Host "Smoke response id: $($response.id)"
