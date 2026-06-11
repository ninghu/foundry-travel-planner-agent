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
    "Bangkok",
    "Buenos Aires",
    "Edinburgh",
    "Istanbul",
    "Lima",
    "Porto",
    "Prague",
    "Queenstown",
    "Singapore",
    "Tbilisi",
    "Vienna",
    "Hanoi",
    "Helsinki",
    "Ljubljana",
    "Oaxaca City",
    "Split",
    "Taipei",
    "Valletta",
    "Wellington",
    "Zanzibar City",
]

ORIGINS = [
    "Seattle",
    "San Francisco",
    "New York",
    "Chicago",
    "Austin",
    "Boston",
    "Los Angeles",
    "Denver",
    "Atlanta",
    "Toronto",
    "London",
    "Dublin",
    "Sydney",
    "Berlin",
    "Amsterdam",
    "Dubai",
    "Bengaluru",
    "Sao Paulo",
]

INTERESTS = [
    "food and history",
    "museums and walkable neighborhoods",
    "family-friendly activities",
    "outdoor activities and scenic views",
    "public transit and low-stress logistics",
    "coffee shops, bookstores, and architecture",
    "street food and night markets",
    "wine, vineyards, and slow countryside drives",
    "hiking, national parks, and wildlife",
    "art galleries and live music",
    "beaches, snorkeling, and watersports",
    "local festivals and cultural events",
    "photography and scenic viewpoints",
    "wellness, spas, and quiet retreats",
    "shopping, design, and local crafts",
    "off-the-beaten-path neighborhoods",
]

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

TRAVELER_GROUPS = [
    "a solo traveler",
    "a couple",
    "two friends",
    "a group of four friends",
    "a family with young kids",
    "a family with teenagers",
    "a multigenerational family",
    "a group of five college friends",
]

PACES = [
    "relaxed",
    "balanced",
    "packed and fast-paced",
    "slow and immersive",
]

CONSTRAINTS = [
    "mostly vegetarian dining options",
    "wheelchair-accessible venues",
    "minimal flying and lots of trains",
    "kid-friendly restaurants and early evenings",
    "a no-car itinerary",
    "late-night dining and nightlife",
    "pet-friendly stays",
    "budget hostels and cheap eats",
    "boutique hotels in central areas",
    "a focus on sustainable, low-impact travel",
]


def _trip_request() -> str:
    nights = random.randint(3, 12)
    budget = random.choice([1200, 1800, 2500, 3200, 4500, 6500, 9000])
    return (
        f"Plan a {nights}-night {random.choice(INTERESTS)} trip from "
        f"{random.choice(ORIGINS)} to {random.choice(DESTINATIONS)} in "
        f"{random.choice(MONTHS)} for {random.choice(TRAVELER_GROUPS)}, with a "
        f"target budget around {budget} USD. Prefer {random.choice(CONSTRAINTS)} "
        f"and include weather-aware backup ideas."
    )


def _itinerary_request() -> str:
    days = random.randint(2, 7)
    return (
        f"Build a {random.choice(PACES)} {days}-day itinerary for "
        f"{random.choice(TRAVELER_GROUPS)} visiting {random.choice(DESTINATIONS)} "
        f"in {random.choice(MONTHS)}, focused on {random.choice(INTERESTS)}."
    )


def _budget_request() -> str:
    nights = random.randint(4, 10)
    budget = random.choice([1500, 2200, 3000, 4000, 5500])
    return (
        f"Is {budget} USD realistic for a {nights}-night trip to "
        f"{random.choice(DESTINATIONS)} for {random.choice(TRAVELER_GROUPS)} in "
        f"{random.choice(MONTHS)}? Give a rough budget breakdown and ways to save."
    )


def _comparison_request() -> str:
    first, second = random.sample(DESTINATIONS, 2)
    return (
        f"Compare {first} and {second} for a {random.choice(MONTHS)} trip focused "
        f"on {random.choice(INTERESTS)} for {random.choice(TRAVELER_GROUPS)}. "
        f"Which is the better fit and why?"
    )


def _feasibility_request() -> str:
    days = random.randint(2, 5)
    return (
        f"Is {days} days enough to enjoy {random.choice(DESTINATIONS)} in "
        f"{random.choice(MONTHS)} if I care most about {random.choice(INTERESTS)}? "
        f"What would you prioritize or cut?"
    )


def _logistics_request() -> str:
    return (
        f"I'm flying from {random.choice(ORIGINS)} to "
        f"{random.choice(DESTINATIONS)} in {random.choice(MONTHS)} with "
        f"{random.choice(TRAVELER_GROUPS)}. What should I know about getting "
        f"around, weather, and what to pack?"
    )


def _day_trip_request() -> str:
    return (
        f"Suggest the best day trips and half-day excursions from "
        f"{random.choice(DESTINATIONS)} in {random.choice(MONTHS)} for "
        f"{random.choice(TRAVELER_GROUPS)} interested in "
        f"{random.choice(INTERESTS)}."
    )


PROMPT_BUILDERS = [
    _trip_request,
    _itinerary_request,
    _budget_request,
    _comparison_request,
    _feasibility_request,
    _logistics_request,
    _day_trip_request,
]


def build_prompt() -> str:
    return random.choice(PROMPT_BUILDERS)()


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
) -> tuple[str, str | None, str | None]:
    kwargs: dict[str, Any] = {"input": prompt}
    extra_body: dict[str, Any] = {}
    if stateful and session_id:
        extra_body["agent_session_id"] = session_id
    if stateful and previous_response_id:
        kwargs["previous_response_id"] = previous_response_id
    if extra_body:
        kwargs["extra_body"] = extra_body
    response = client.responses.create(**kwargs)
    next_session_id = getattr(response, "model_extra", {}).get("agent_session_id")
    return output_text(response), next_session_id or session_id, getattr(response, "id", None)


def invoke_local(local_url: str, prompt: str, timeout: float) -> str:
    body: dict[str, Any] = {"input": prompt, "stream": False}
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
    return parser.parse_args()


def main() -> int:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if callable(stdout_reconfigure) and callable(stderr_reconfigure):
        stdout_reconfigure(encoding="utf-8", errors="replace")
        stderr_reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
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
        started = time.perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            if args.local_url:
                text = invoke_local(args.local_url, prompt, args.timeout_seconds)
            else:
                text, session_id, previous_response_id = invoke_remote(
                    remote_client,
                    prompt,
                    session_id,
                    previous_response_id,
                    args.stateful,
                )
            elapsed = time.perf_counter() - started
            preview = " ".join(text.split())[:220]
            print(
                f"[{timestamp}] ok elapsed={elapsed:.1f}s prompt={prompt!r} response={preview!r}",
                flush=True,
            )
        except Exception as exc:
            elapsed = time.perf_counter() - started
            print(
                f"[{timestamp}] error elapsed={elapsed:.1f}s prompt={prompt!r} error={type(exc).__name__}: {exc}",
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
