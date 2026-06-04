from functools import lru_cache

from azure.identity import DefaultAzureCredential
from langchain_azure_ai.chat_models import AzureAIOpenAIApiChatModel

from travel_planner_agent.config import get_settings


@lru_cache(maxsize=1)
def get_chat_model() -> AzureAIOpenAIApiChatModel:
    settings = get_settings()
    return AzureAIOpenAIApiChatModel(
        project_endpoint=settings.project_endpoint,
        credential=DefaultAzureCredential(),
        model=settings.model_deployment_name,
        streaming=True,
    )
