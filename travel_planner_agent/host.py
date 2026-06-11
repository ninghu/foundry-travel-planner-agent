import asyncio
import logging
import os

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
    maybe_raise_http_500,
    maybe_sleep_for_latency,
)
from travel_planner_agent.config import configure_logging, configure_tracing
from travel_planner_agent.graph import build_travel_graph


configure_logging()
configure_tracing()
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


@app.response_handler
async def handle_create(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
):
    maybe_raise_http_500("responses_handler")

    async def run_graph():
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
            # Prefer conversation_id for thread grouping; fall back to response_id when the
            # ResponseContext does not expose a stable conversation id.
            thread_id = getattr(context, "conversation_id", None) or getattr(
                context, "response_id", None
            )
            result = await GRAPH.ainvoke(
                {"messages": messages, "user_request": current_input},
                config={
                    "recursion_limit": 80,
                    "run_name": "foundry_travel_planner",
                    "tags": [
                        "foundry",
                        "travel_planner",
                        os.getenv("ENVIRONMENT", "production"),
                    ],
                    "metadata": {
                        "thread_id": thread_id,
                        "user_id": getattr(context, "user_id", None),
                        "environment": os.getenv("ENVIRONMENT", "production"),
                    },
                },
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
