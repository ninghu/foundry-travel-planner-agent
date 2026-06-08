# Foundry Travel Planner Agent

LangGraph travel planner hosted as a Microsoft Foundry hosted agent over the
Responses API protocol.

The agent is a small multi-agent graph:

- Destination research sub-agent: geocoding, country profile, place search, and
  weather context.
- Logistics sub-agent: distance and travel-time estimates.
- Budget sub-agent: live exchange-rate lookup and heuristic trip budget.
- Itinerary sub-agent: day-by-day plan synthesis.
- Final planner node: combines the sub-agent outputs into one traveler-facing
  plan.

Tool calls are real Python executions. The current tools call public APIs from
Open-Meteo, REST Countries, Frankfurter, and OpenStreetMap Nominatim. Review
that data flow before using the sample with sensitive travel data.

## Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

In another terminal:

```powershell
$body = @{
  input = "Plan a 5 day food and history trip from Seattle to Lisbon in September for two people under 3500 USD."
  stream = $false
} | ConvertTo-Json

Invoke-RestMethod -Uri http://localhost:8088/responses -Method Post -Body $body -ContentType "application/json"
```

## Deploy

The default deployment target is the Foundry project from the request:

```text
https://foundry-sre-project-resource.services.ai.azure.com/api/projects/foundry-sre-project
```

Deploy with:

```powershell
.\scripts\deploy_foundry.ps1
```

The helper initializes the `azd` environment if needed, points it at the
existing `gpt-5.4-mini` model deployment, runs `azd up`, applies required
Foundry-hosted-agent RBAC, and performs a Responses API smoke test.

The deployment helper also enables GenAI content recording for trace spans:

```powershell
$env:AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED = "true"
$env:OTEL_SEMCONV_STABILITY_OPT_IN = "gen_ai_latest_experimental"
$env:OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT = "SPAN_AND_EVENT"
```

## Generate Traffic

After deployment:

```powershell
python scripts/generate_traffic.py `
  --agent-name travel-planner-langgraph `
  --project-endpoint https://foundry-sre-project-resource.services.ai.azure.com/api/projects/foundry-sre-project `
  --interval-seconds 20
```

For local traffic against `python main.py`:

```powershell
python scripts/generate_traffic.py --local-url http://localhost:8088/responses --max-requests 5
```

Chaos behavior is configured on the agent itself (see [Chaos Mode](#chaos-mode)),
not from the traffic generator.

## Trigger SRE Investigation

Invoke the configured SRE Agent HTTP trigger and return the created thread URL:

```powershell
.\scripts\invoke_sre_http_trigger.ps1
```

Pass a specific issue description with:

```powershell
.\scripts\invoke_sre_http_trigger.ps1 -ProblemDescription "agent invocation failed"
```

## Chaos Mode

Chaos is off by default. Enable it with environment variables:

```powershell
$env:CHAOS_MODE = "random"
$env:CHAOS_RATE = "0.25"
$env:CHAOS_LATENCY_MIN_SECONDS = "5"
$env:CHAOS_LATENCY_MAX_SECONDS = "20"
python main.py
```

Supported `CHAOS_MODE` values are `random`, `all`, `http_500`, `latency`,
`tool_failure`, `llm_failure`, `low_eval`, `unfair_response`, `intent_miss`,
and `task_incomplete`. You can combine specific modes with commas, for example
`intent_miss,task_incomplete`. `CHAOS_RATE` is a probability from `0` to `1`.

Evaluator-focused modes:

```text
tool_failure     -> Tool-Call-Success-Evaluator
unfair_response  -> Hate-and-Unfairness-Evaluator, via unfair economic exclusion
intent_miss      -> Intent-Resolution-Evaluator
task_incomplete  -> Task-Completion-Evaluator
low_eval         -> deterministic off-topic, incomplete, low-fluency response
```

For deterministic local evaluator testing, set `CHAOS_RATE` to `1` and choose a
single mode:

```powershell
$env:CHAOS_MODE = "intent_miss"
$env:CHAOS_RATE = "1"
python main.py
```

Deploy chaos settings to Foundry with:

```powershell
.\scripts\deploy_foundry.ps1 -ChaosMode random -ChaosRate 0.2
```

For continuous evaluation probes in Foundry, deploy a specific low-score mode:

```powershell
.\scripts\deploy_foundry.ps1 -ChaosMode low_eval -ChaosRate 1
```
