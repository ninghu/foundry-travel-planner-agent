import asyncio
import logging
import random
from dataclasses import dataclass

from travel_planner_agent.config import get_settings


logger = logging.getLogger(__name__)


class ChaosInjectedError(RuntimeError):
    """Intentional failure used when CHAOS_MODE is enabled."""


@dataclass(frozen=True)
class ChaosEvent:
    issue: str
    component: str
    delay_seconds: float | None = None


ISSUES = ("http_500", "latency", "tool_failure", "llm_failure")
ALIASES = {
    "1": "random",
    "true": "random",
    "on": "random",
    "enabled": "random",
    "enable": "random",
    "random": "random",
    "all": "random",
    "500": "http_500",
    "http500": "http_500",
    "http_500": "http_500",
    "server_error": "http_500",
    "latency": "latency",
    "latency_spike": "latency",
    "slow": "latency",
    "tool": "tool_failure",
    "tool_failure": "tool_failure",
    "tool_call_failure": "tool_failure",
    "llm": "llm_failure",
    "llm_failure": "llm_failure",
    "llm_call_failure": "llm_failure",
}
OFF_VALUES = {"", "0", "false", "off", "none", "disabled", "disable"}


def _configured_issues() -> set[str]:
    raw_mode = get_settings().chaos_mode.strip().lower()
    if raw_mode in OFF_VALUES:
        return set()

    selected: set[str] = set()
    for part in raw_mode.replace(";", ",").replace("|", ",").split(","):
        normalized = ALIASES.get(part.strip().replace("-", "_"))
        if normalized == "random":
            selected.update(ISSUES)
        elif normalized:
            selected.add(normalized)
        elif part.strip():
            logger.warning("Ignoring unknown CHAOS_MODE token: %s", part.strip())
    return selected


def _roll(issue: str, component: str) -> ChaosEvent | None:
    settings = get_settings()
    if issue not in _configured_issues():
        return None
    if random.random() > settings.chaos_rate:
        return None
    event = ChaosEvent(issue=issue, component=component)
    logger.warning("CHAOS injected: issue=%s component=%s", issue, component)
    return event


def maybe_raise_http_500(component: str) -> None:
    event = _roll("http_500", component)
    if event:
        raise ChaosInjectedError(
            f"CHAOS_MODE simulated HTTP 500 at component={component}"
        )


def maybe_raise_tool_failure(tool_name: str) -> None:
    event = _roll("tool_failure", tool_name)
    if event:
        raise ChaosInjectedError(
            f"CHAOS_MODE simulated tool call failure in tool={tool_name}"
        )


def maybe_raise_llm_failure(component: str) -> None:
    event = _roll("llm_failure", component)
    if event:
        raise ChaosInjectedError(
            f"CHAOS_MODE simulated LLM call failure at component={component}"
        )


async def maybe_sleep_for_latency(component: str) -> None:
    event = _roll("latency", component)
    if not event:
        return

    settings = get_settings()
    delay = random.uniform(
        settings.chaos_latency_min_seconds,
        settings.chaos_latency_max_seconds,
    )
    logger.warning(
        "CHAOS latency spike: component=%s delay_seconds=%.2f",
        component,
        delay,
    )
    await asyncio.sleep(delay)
