from typing import Annotated, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from typing_extensions import TypedDict

from travel_planner_agent.chaos import maybe_degrade_final_answer, maybe_raise_llm_failure
from travel_planner_agent.llm import get_chat_model
from travel_planner_agent.tools import (
    BUDGET_TOOLS,
    DESTINATION_RESEARCH_TOOLS,
    ITINERARY_TOOLS,
    LOGISTICS_TOOLS,
)


class TravelPlanState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    user_request: str
    destination_research: str
    logistics: str
    budget: str
    itinerary: str
    final_answer: str


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                chunks.append(str(item.get("text") or item.get("content") or item))
            else:
                chunks.append(str(getattr(item, "text", item)))
        return "".join(chunks)
    return str(content)


def _last_message_text(result: dict[str, Any]) -> str:
    messages = result.get("messages") or []
    if not messages:
        return ""
    return _message_text(messages[-1].content)


def _conversation_context(state: TravelPlanState) -> str:
    messages = state.get("messages") or []
    tail = messages[-8:]
    lines = []
    for message in tail:
        role = "assistant" if isinstance(message, AIMessage) else "user"
        lines.append(f"{role}: {_message_text(message.content)}")
    return "\n".join(lines)


def _request(state: TravelPlanState) -> str:
    return state.get("user_request") or _message_text((state.get("messages") or [])[-1].content)


def build_travel_graph():
    llm = get_chat_model()

    destination_research_agent = create_react_agent(
        llm,
        DESTINATION_RESEARCH_TOOLS,
        prompt=(
            "You are the destination research sub-agent for a travel planner. "
            "Use tools when they can verify geography, country facts, weather, or "
            "destination background. Return concise notes with evidence and call out "
            "uncertainty instead of inventing facts."
        ),
    )
    logistics_agent = create_react_agent(
        llm,
        LOGISTICS_TOOLS,
        prompt=(
            "You are the logistics sub-agent. Estimate travel feasibility, rough "
            "distance, seasonal weather impacts, pacing, and route considerations. "
            "Use tools for distance, geocoding, and weather."
        ),
    )
    budget_agent = create_react_agent(
        llm,
        BUDGET_TOOLS,
        prompt=(
            "You are the budget sub-agent. Use the budget and exchange-rate tools. "
            "Produce a practical range, explain assumptions, and flag that booked "
            "prices must be verified."
        ),
    )
    itinerary_agent = create_react_agent(
        llm,
        ITINERARY_TOOLS,
        prompt=(
            "You are the itinerary sub-agent. Build a day-by-day plan that respects "
            "the user's constraints and the notes from the other sub-agents. Use tools "
            "for weather or attraction context when helpful."
        ),
    )

    async def destination_research(state: TravelPlanState) -> dict[str, str]:
        maybe_raise_llm_failure("destination_research_agent")
        prompt = (
            "Traveler request:\n"
            f"{_request(state)}\n\n"
            "Conversation context:\n"
            f"{_conversation_context(state)}\n\n"
            "Research the destination, country basics, seasonal/weather context, "
            "and any destination-specific constraints."
        )
        result = await destination_research_agent.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": 12},
        )
        return {"destination_research": _last_message_text(result)}

    async def logistics(state: TravelPlanState) -> dict[str, str]:
        maybe_raise_llm_failure("logistics_agent")
        prompt = (
            "Traveler request:\n"
            f"{_request(state)}\n\n"
            "Destination research notes:\n"
            f"{state.get('destination_research', '')}\n\n"
            "Analyze travel logistics, approximate route distance, weather impacts, "
            "arrival/departure pacing, and any planning risks."
        )
        result = await logistics_agent.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": 12},
        )
        return {"logistics": _last_message_text(result)}

    async def budget(state: TravelPlanState) -> dict[str, str]:
        maybe_raise_llm_failure("budget_agent")
        prompt = (
            "Traveler request:\n"
            f"{_request(state)}\n\n"
            "Destination research notes:\n"
            f"{state.get('destination_research', '')}\n\n"
            "Logistics notes:\n"
            f"{state.get('logistics', '')}\n\n"
            "Estimate the trip budget. If a needed input is missing, make a clearly "
            "labeled conservative assumption and continue."
        )
        result = await budget_agent.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": 12},
        )
        return {"budget": _last_message_text(result)}

    async def itinerary(state: TravelPlanState) -> dict[str, str]:
        maybe_raise_llm_failure("itinerary_agent")
        prompt = (
            "Traveler request:\n"
            f"{_request(state)}\n\n"
            "Destination research notes:\n"
            f"{state.get('destination_research', '')}\n\n"
            "Logistics notes:\n"
            f"{state.get('logistics', '')}\n\n"
            "Budget notes:\n"
            f"{state.get('budget', '')}\n\n"
            "Create a realistic day-by-day itinerary with pacing, neighborhoods, "
            "food/activity ideas, and backup weather-aware options."
        )
        result = await itinerary_agent.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": 12},
        )
        return {"itinerary": _last_message_text(result)}

    async def final_planner(state: TravelPlanState) -> dict[str, str]:
        maybe_raise_llm_failure("final_planner")
        messages = [
            SystemMessage(
                content=(
                    "You are the final travel-planner agent. Combine the specialized "
                    "sub-agent notes into one clear plan. Include a short assumptions "
                    "section, a day-by-day itinerary, budget summary, logistics notes, "
                    "weather/seasonality notes, and next actions. Do not claim to book "
                    "flights, hotels, or reservations."
                )
            ),
            HumanMessage(
                content=(
                    "Traveler request:\n"
                    f"{_request(state)}\n\n"
                    "Destination research sub-agent:\n"
                    f"{state.get('destination_research', '')}\n\n"
                    "Logistics sub-agent:\n"
                    f"{state.get('logistics', '')}\n\n"
                    "Budget sub-agent:\n"
                    f"{state.get('budget', '')}\n\n"
                    "Itinerary sub-agent:\n"
                    f"{state.get('itinerary', '')}\n\n"
                    "Return the final plan in concise Markdown."
                )
            ),
        ]
        response = await llm.ainvoke(messages)
        answer = _message_text(response.content)
        return {"final_answer": maybe_degrade_final_answer(answer, _request(state))}

    graph = StateGraph(TravelPlanState)
    graph.add_node("destination_research", destination_research)
    graph.add_node("logistics", logistics)
    graph.add_node("budget", budget)
    graph.add_node("itinerary", itinerary)
    graph.add_node("final_planner", final_planner)
    graph.add_edge(START, "destination_research")
    graph.add_edge("destination_research", "logistics")
    graph.add_edge("logistics", "budget")
    graph.add_edge("budget", "itinerary")
    graph.add_edge("itinerary", "final_planner")
    graph.add_edge("final_planner", END)
    return graph.compile()
