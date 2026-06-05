[CmdletBinding()]
param(
    [string]$ProblemDescription = "invocation failed",
    [string]$ProjectEndpoint = "https://foundry-sre-project-resource.services.ai.azure.com/api/projects/foundry-sre-project",
    [string]$AgentName = "travel-planner-langgraph",
    [string]$AgentVersion = "6",
    [string]$TriggerUrl = "https://ninhu-sre-agent-poc--52700a3c.62f83535.swedencentral.azuresre.ai/api/v1/httptriggers/trigger/0b7288d5-6855-418e-b747-f395c2762dec",
    [string]$SreAgentUrl = "https://sre.azure.com/agents/subscriptions/7b43cfa1-da92-48cc-865d-5499466b3b5c/resourceGroups/ninhu-ai-test/providers/Microsoft.App/agents/ninhu-sre-agent-poc",
    [string]$Subscription = "7b43cfa1-da92-48cc-865d-5499466b3b5c",
    [string]$AuthResource = "59f0a04a-b322-4310-adc9-39ac41e9631e"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "az is required. Install Azure CLI first."
}

if (-not [string]::IsNullOrWhiteSpace($Subscription)) {
    az account set --subscription $Subscription
    if ($LASTEXITCODE -ne 0) {
        throw "Azure subscription selection failed with exit code $LASTEXITCODE."
    }
}

$token = az account get-access-token --resource $AuthResource --query accessToken -o tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) {
    throw "Could not acquire an Azure bearer token for the SRE Agent trigger."
}

$body = @{
    payload = [ordered]@{
        project_endpoint = $ProjectEndpoint
        agent_name       = $AgentName
        agent_version    = $AgentVersion
        issue            = $ProblemDescription
    }
} | ConvertTo-Json -Depth 10

$headers = @{
    Authorization = "Bearer $token"
}

$response = Invoke-WebRequest `
    -Uri $TriggerUrl `
    -Method Post `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body `
    -UseBasicParsing

$responseBody = $response.Content | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($responseBody.threadId)) {
    throw "SRE Agent trigger response did not include a threadId. Response: $($response.Content)"
}

$threadUrl = "$($SreAgentUrl.TrimEnd('/'))/views/thread/$($responseBody.threadId)"

[pscustomobject]@{
    statusCode    = $response.StatusCode
    success       = $responseBody.success
    message       = $responseBody.message
    executionTime = $responseBody.executionTime
    threadId      = $responseBody.threadId
    threadUrl     = $threadUrl
}