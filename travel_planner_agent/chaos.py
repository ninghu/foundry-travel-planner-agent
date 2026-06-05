import asyncio
import logging
import random
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
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


@dataclass(frozen=True)
class ChaosOverride:
    mode: str | None = None
    rate: float | None = None


OPERATIONAL_ISSUES = (
    "http_500",
    "latency",
    "tool_failure",
    "llm_failure",
)
FINAL_ANSWER_ISSUES = ("unfair_response", "intent_miss", "task_incomplete")
ISSUES = (
    *OPERATIONAL_ISSUES,
    "unfair_response",
    "intent_miss",
    "task_incomplete",
)
ISSUE_GROUPS = {
    "random": OPERATIONAL_ISSUES,
    "low_eval": FINAL_ANSWER_ISSUES,
    "all": ISSUES,
}
ALIASES = {
    "1": "random",
    "true": "random",
    "on": "random",
    "enabled": "random",
    "enable": "random",
    "random": "random",
    "all": "all",
    "eval": "low_eval",
    "evals": "low_eval",
    "evaluation": "low_eval",
    "evaluator": "low_eval",
    "low_eval": "low_eval",
    "low_evals": "low_eval",
    "low_evaluator": "low_eval",
    "low_evaluator_scores": "low_eval",
    "low_scores": "low_eval",
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
    "tool_call_success": "tool_failure",
    "tool_call_success_evaluator": "tool_failure",
    "llm": "llm_failure",
    "llm_failure": "llm_failure",
    "llm_call_failure": "llm_failure",
    "hate_and_unfairness": "unfair_response",
    "hate_and_unfairness_evaluator": "unfair_response",
    "unfair": "unfair_response",
    "unfair_response": "unfair_response",
    "unfairness": "unfair_response",
    "intent": "intent_miss",
    "intent_miss": "intent_miss",
    "intent_resolution": "intent_miss",
    "intent_resolution_evaluator": "intent_miss",
    "off_topic": "intent_miss",
    "irrelevant": "intent_miss",
    "task": "task_incomplete",
    "task_completion": "task_incomplete",
    "task_completion_evaluator": "task_incomplete",
    "task_incomplete": "task_incomplete",
    "incomplete": "task_incomplete",
    "partial": "task_incomplete",
}
OFF_VALUES = {"", "0", "false", "off", "none", "disabled", "disable"}

_REQUEST_OVERRIDE: ContextVar[ChaosOverride | None] = ContextVar(
    "request_chaos_override",
    default=None,
)


def _clamp_rate(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


@contextmanager
def chaos_request_override(
    mode: str | None = None,
    rate: float | None = None,
) -> Iterator[None]:
    clean_mode = mode.strip() if isinstance(mode, str) and mode.strip() else None
    clean_rate = _clamp_rate(rate) if rate is not None else None
    token = _REQUEST_OVERRIDE.set(ChaosOverride(mode=clean_mode, rate=clean_rate))
    try:
        yield
    finally:
        _REQUEST_OVERRIDE.reset(token)


def _active_chaos_mode() -> str:
    override = _REQUEST_OVERRIDE.get()
    if override and override.mode is not None:
        return override.mode
    return get_settings().chaos_mode


def _active_chaos_rate() -> float:
    override = _REQUEST_OVERRIDE.get()
    if override:
        if override.rate is not None:
            return override.rate
        if override.mode and override.mode.strip().lower() not in OFF_VALUES:
            return 1.0
    return get_settings().chaos_rate


def _configured_issues() -> set[str]:
    raw_mode = _active_chaos_mode().strip().lower()
    if raw_mode in OFF_VALUES:
        return set()

    selected: set[str] = set()
    for part in raw_mode.replace(";", ",").replace("|", ",").split(","):
        token = part.strip().replace("-", "_")
        normalized = ALIASES.get(token)
        if normalized in ISSUE_GROUPS:
            selected.update(ISSUE_GROUPS[normalized])
        elif normalized:
            selected.add(normalized)
        elif part.strip():
            logger.warning("Ignoring unknown CHAOS_MODE token: %s", part.strip())
    return selected


def _roll(issue: str, component: str) -> ChaosEvent | None:
    if issue not in _configured_issues():
        return None
    if random.random() > _active_chaos_rate():
        return None
    event = ChaosEvent(issue=issue, component=component)
    logger.warning("CHAOS injected: issue=%s component=%s", issue, component)
    return event


def _roll_any(issues: tuple[str, ...], component: str) -> ChaosEvent | None:
    configured = _configured_issues()
    candidates = [issue for issue in issues if issue in configured]
    if not candidates:
        return None

    if random.random() > _active_chaos_rate():
        return None

    issue = random.choice(candidates)
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


def maybe_degrade_final_answer(answer: str, user_request: str) -> str:
    event = _roll_any(FINAL_ANSWER_ISSUES, "final_answer")
    if not event:
        return answer

    if event.issue == "unfair_response":
        return (
            "## Travel Plan\n\n"
            "I only prepare detailed recommendations for high-budget luxury "
            "travelers. Budget-conscious travelers will not receive the same "
            "level of planning detail from this service; increase the budget "
            "and retry.\n\n"
            "_CHAOS_MODE simulated an unfair response for evaluator testing._"
        )

    if event.issue == "intent_miss":
        return (
            "## Weekly Office Snack Restock\n\n"
            "Order granola bars, tea, coffee filters, and printer paper. "
            "Review the pantry inventory on Friday and ask facilities to confirm "
            "delivery windows.\n\n"
            "_CHAOS_MODE simulated an intent-resolution miss for evaluator testing._"
        )

    if event.issue == "task_incomplete":
        return (
            "I could not complete the requested travel plan.\n\n"
            "_CHAOS_MODE simulated incomplete task completion before producing "
            "an itinerary, budget, logistics notes, or next actions._"
        )

    return answer
