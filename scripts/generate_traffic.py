import argparse
import random
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential


DESTINATIONS = [
    "Lisbon",
    "Kyoto",
    "Mexico City",
    "Reykjavik",
    "Barcelona",
    "Vancouver",
    "Cape Town",
    "Seoul",
    "Montreal",
    "Marrakesh",
]

ORIGINS = [
    "Seattle",
    "San Francisco",
    "New York",
    "Chicago",
    "Austin",
    "Boston",
    "Los Angeles",
]

INTERESTS = [
    "food and history",
    "museums and walkable neighborhoods",
    "family-friendly activities",
    "outdoor activities and scenic views",
    "public transit and low-stress logistics",
    "coffee shops, bookstores, and architecture",
]

MONTHS = [
    "March",
    "April",
    "May",
    "June",
    "September",
    "October",
    "November",
    "December",
]

DEFAULT_RANDOM_CHAOS_MODES = "off,low_eval,tool_failure"


def build_prompt() -> str:
    travelers = random.choice([1, 2, 2, 3, 4])
    nights = random.randint(3, 9)
    budget = random.choice([1800, 2500, 3200, 4500, 6500])
    return (
        f"Plan a {nights} night {random.choice(INTERESTS)} trip from "
        f"{random.choice(ORIGINS)} to {random.choice(DESTINATIONS)} in "
        f"{random.choice(MONTHS)} for {travelers} traveler(s), with a target "
        f"budget around {budget} USD. Include weather-aware backup ideas."
    )


def output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return text
    output = getattr(response, "output", None) or []
    chunks: list[str] = []
    for item in output:
        for content in getattr(item, "content", []) or []:
            value = getattr(content, "text", None)
            if value:
                chunks.append(value)
    return "".join(chunks)


def invoke_remote(
    client: Any,
    prompt: str,
    session_id: str | None,
    previous_response_id: str | None,
    stateful: bool,
    metadata: dict[str, str] | None,
) -> tuple[str, str | None, str | None]:
    kwargs: dict[str, Any] = {"input": prompt}
    extra_body: dict[str, Any] = {}
    if metadata:
        kwargs["metadata"] = metadata
    if stateful and session_id:
        extra_body["agent_session_id"] = session_id
    if stateful and previous_response_id:
        kwargs["previous_response_id"] = previous_response_id
    if extra_body:
        kwargs["extra_body"] = extra_body
    response = client.responses.create(**kwargs)
    next_session_id = getattr(response, "model_extra", {}).get("agent_session_id")
    return output_text(response), next_session_id or session_id, getattr(response, "id", None)


def invoke_local(
    local_url: str,
    prompt: str,
    timeout: float,
    metadata: dict[str, str] | None,
) -> str:
    body: dict[str, Any] = {"input": prompt, "stream": False}
    if metadata:
        body["metadata"] = metadata
    with httpx.Client(timeout=timeout) as client:
        response = client.post(local_url, json=body)
        response.raise_for_status()
        data = response.json()
    if isinstance(data, dict):
        if data.get("output_text"):
            return str(data["output_text"])
        output = data.get("output") or []
        chunks: list[str] = []
        for item in output:
            for content in item.get("content", []) or []:
                text = content.get("text")
                if text:
                    chunks.append(text)
        if chunks:
            return "".join(chunks)
    return str(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continuously send random travel-planning traffic to a hosted Foundry agent."
    )
    parser.add_argument("--project-endpoint", default=None)
    parser.add_argument("--agent-name", default="travel-planner-langgraph")
    parser.add_argument("--local-url", default=None)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--jitter-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-requests", type=int, default=0)
    parser.add_argument("--stateful", action="store_true")
    parser.add_argument(
        "--chaos-mode",
        default=None,
        help="Per-request CHAOS_MODE override sent in response metadata.",
    )
    parser.add_argument(
        "--random-chaos-mode",
        action="store_true",
        help="Choose a per-request chaos mode from --chaos-modes for each request.",
    )
    parser.add_argument(
        "--chaos-modes",
        default=DEFAULT_RANDOM_CHAOS_MODES,
        help="Comma-separated modes used by --random-chaos-mode.",
    )
    parser.add_argument(
        "--chaos-rate",
        type=float,
        default=1.0,
        help="Per-request CHAOS_RATE override when a chaos mode is sent.",
    )
    return parser.parse_args()


def parse_chaos_modes(value: str) -> list[str]:
    return [mode.strip() for mode in value.split(",") if mode.strip()]


def choose_chaos_mode(args: argparse.Namespace, modes: list[str]) -> str | None:
    if args.random_chaos_mode:
        return random.choice(modes) if modes else None
    return args.chaos_mode.strip() if args.chaos_mode else None


def build_request_metadata(chaos_mode: str | None, chaos_rate: float) -> dict[str, str] | None:
    if not chaos_mode:
        return None
    rate = max(0.0, min(float(chaos_rate), 1.0))
    return {
        "chaos_mode": chaos_mode,
        "chaos_rate": str(rate),
    }


def main() -> int:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if callable(stdout_reconfigure) and callable(stderr_reconfigure):
        stdout_reconfigure(encoding="utf-8", errors="replace")
        stderr_reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    chaos_modes = parse_chaos_modes(args.chaos_modes)
    if args.random_chaos_mode and not chaos_modes:
        raise SystemExit("--chaos-modes must include at least one mode.")
    stop = False

    def _stop(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    remote_client = None
    if not args.local_url:
        if not args.project_endpoint:
            raise SystemExit("--project-endpoint is required unless --local-url is set.")
        project = AIProjectClient(
            endpoint=args.project_endpoint,
            credential=DefaultAzureCredential(),
            allow_preview=True,
        )
        remote_client = project.get_openai_client(agent_name=args.agent_name)

    count = 0
    session_id = None
    previous_response_id = None
    while not stop:
        prompt = build_prompt()
        chaos_mode = choose_chaos_mode(args, chaos_modes)
        metadata = build_request_metadata(chaos_mode, args.chaos_rate)
        started = time.perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            if args.local_url:
                text = invoke_local(args.local_url, prompt, args.timeout_seconds, metadata)
            else:
                text, session_id, previous_response_id = invoke_remote(
                    remote_client,
                    prompt,
                    session_id,
                    previous_response_id,
                    args.stateful,
                    metadata,
                )
            elapsed = time.perf_counter() - started
            preview = " ".join(text.split())[:220]
            print(
                f"[{timestamp}] ok elapsed={elapsed:.1f}s chaos_mode={chaos_mode or '-'} prompt={prompt!r} response={preview!r}",
                flush=True,
            )
        except Exception as exc:
            elapsed = time.perf_counter() - started
            print(
                f"[{timestamp}] error elapsed={elapsed:.1f}s chaos_mode={chaos_mode or '-'} prompt={prompt!r} error={type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )

        count += 1
        if args.max_requests and count >= args.max_requests:
            break
        sleep_for = max(
            0.0,
            args.interval_seconds + random.uniform(-args.jitter_seconds, args.jitter_seconds),
        )
        time.sleep(sleep_for)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
