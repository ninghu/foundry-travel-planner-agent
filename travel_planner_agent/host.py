import asyncio
import logging

from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    ResponsesServerOptions,
    TextResponse,
)
from azure.ai.agentserver.responses.models import (
    MessageContentInputTextContent,
    MessageContentOutputTextContent,
)
from langchain_core.messages import AIMessage, HumanMessage

from travel_planner_agent.chaos import (
    ChaosInjectedError,
    chaos_request_override,
    maybe_raise_http_500,
    maybe_sleep_for_latency,
)
from travel_planner_agent.config import configure_logging
from travel_planner_agent.graph import build_travel_graph


configure_logging()
logger = logging.getLogger(__name__)

GRAPH = build_travel_graph()

app = ResponsesAgentServerHost(
    options=ResponsesServerOptions(default_fetch_history_count=20)
)


def _history_to_langchain_messages(history: list) -> list:
    messages = []
    for item in history:
        content_items = getattr(item, "content", None) or []
        for content in content_items:
            if isinstance(content, MessageContentOutputTextContent) and content.text:
                messages.append(AIMessage(content=content.text))
            elif isinstance(content, MessageContentInputTextContent) and content.text:
                messages.append(HumanMessage(content=content.text))
    return messages


def _mapping_get(source, key: str):
    if isinstance(source, dict):
        return source.get(key)
    if hasattr(source, "get"):
        try:
            return source.get(key)
        except Exception:
            return None
    return None


def _request_value(request: CreateResponse, key: str):
    for source_name in ("metadata", "model_extra", "extra_body"):
        source = getattr(request, source_name, None)
        value = _mapping_get(source, key)
        if value is not None:
            return value
        metadata = _mapping_get(source, "metadata")
        value = _mapping_get(metadata, key)
        if value is not None:
            return value
    return getattr(request, key, None)


def _request_chaos_override(request: CreateResponse) -> tuple[str | None, float | None]:
    mode = _request_value(request, "chaos_mode") or _request_value(request, "chaosMode")
    raw_rate = _request_value(request, "chaos_rate") or _request_value(request, "chaosRate")
    if raw_rate is None or raw_rate == "":
        return str(mode).strip() if mode else None, None
    try:
        rate = max(0.0, min(float(raw_rate), 1.0))
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid request chaos_rate: %r", raw_rate)
        rate = None
    return str(mode).strip() if mode else None, rate


@app.response_handler
async def handle_create(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
):
    chaos_mode, chaos_rate = _request_chaos_override(request)
    with chaos_request_override(chaos_mode, chaos_rate):
        maybe_raise_http_500("responses_handler")

    async def run_graph():
        with chaos_request_override(chaos_mode, chaos_rate):
            try:
                if cancellation_signal.is_set():
                    return

                await maybe_sleep_for_latency("responses_handler")

                try:
                    history = await context.get_history()
                except Exception:
                    logger.debug("No prior response history available", exc_info=True)
                    history = []

                current_input = await context.get_input_text()
                if not current_input:
                    current_input = "Plan a practical 3 day first-time visitor trip."

                messages = _history_to_langchain_messages(history)
                messages.append(HumanMessage(content=current_input))
                result = await GRAPH.ainvoke(
                    {"messages": messages, "user_request": current_input},
                    config={"recursion_limit": 80},
                )
                if not cancellation_signal.is_set():
                    yield result.get("final_answer", "I could not create a travel plan.")
            except ChaosInjectedError:
                logger.exception("Chaos injection failed the request")
                raise
            except Exception as exc:
                logger.exception("Travel planner graph failed")
                yield f"[ERROR] {type(exc).__name__}: {exc}"

    return TextResponse(context, request, text=run_graph())
