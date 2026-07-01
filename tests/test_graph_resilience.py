"""End-to-end resilience test: sub-agent exceptions must not crash the graph."""
import asyncio
import os
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("AZURE_AI_PROJECT_ENDPOINT", "https://example.invalid/project")
os.environ.setdefault("AZURE_AI_MODEL_DEPLOYMENT_NAME", "test-model")


class _FakeAIResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Stand-in for get_chat_model() that doesn't need Azure creds."""

    def __init__(self, reply: str = "OK plan.") -> None:
        self._reply = reply

    async def ainvoke(self, messages, config=None):
        return _FakeAIResponse(self._reply)

    def bind_tools(self, *_args, **_kwargs):
        return self


def _install_fake_llm(monkeypatch) -> None:
    from travel_planner_agent import graph as graph_module

    fake = _FakeLLM()
    monkeypatch.setattr(graph_module, "get_chat_model", lambda: fake)

    async def _fake_react(state, config=None):
        return {"messages": [types.SimpleNamespace(content="sub-agent notes")]}

    fake_agent = types.SimpleNamespace(ainvoke=_fake_react)
    monkeypatch.setattr(graph_module, "create_react_agent", lambda *a, **k: fake_agent)


def test_graph_survives_sub_agent_llm_exception(monkeypatch):
    from travel_planner_agent import chaos, graph as graph_module
    from langchain_core.messages import HumanMessage

    _install_fake_llm(monkeypatch)

    def _always_raise(component: str) -> None:
        raise chaos.ChaosInjectedError(f"injected failure in {component}")

    monkeypatch.setattr(graph_module, "maybe_raise_llm_failure", _always_raise)

    compiled = graph_module.build_travel_graph()

    result = asyncio.run(
        compiled.ainvoke(
            {
                "messages": [HumanMessage(content="Plan a trip to Kyoto.")],
                "user_request": "Plan a trip to Kyoto.",
            }
        )
    )

    final_answer = result.get("final_answer")
    assert final_answer, "graph must produce a non-empty final_answer even when sub-agents fail"
    assert isinstance(final_answer, str)
