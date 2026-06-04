import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


load_dotenv(override=False)


@dataclass(frozen=True)
class Settings:
    project_endpoint: str
    model_deployment_name: str
    log_level: str = "INFO"
    tool_timeout_seconds: float = 8.0
    chaos_mode: str = "off"
    chaos_rate: float = 0.0
    chaos_latency_min_seconds: float = 5.0
    chaos_latency_max_seconds: float = 20.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    project_endpoint = (
        os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
        or ""
    ).rstrip("/")
    if not project_endpoint:
        raise EnvironmentError(
            "Set AZURE_AI_PROJECT_ENDPOINT for local runs. In Foundry hosted mode "
            "the platform injects FOUNDRY_PROJECT_ENDPOINT."
        )

    model_deployment_name = os.getenv(
        "AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5.4-mini"
    )
    timeout = float(os.getenv("TRAVEL_TOOL_TIMEOUT_SECONDS", "8"))
    chaos_latency_seconds = os.getenv("CHAOS_LATENCY_SECONDS")
    chaos_latency_min = float(os.getenv("CHAOS_LATENCY_MIN_SECONDS", "5"))
    chaos_latency_max = float(os.getenv("CHAOS_LATENCY_MAX_SECONDS", "20"))
    if chaos_latency_seconds:
        chaos_latency_min = float(chaos_latency_seconds)
        chaos_latency_max = float(chaos_latency_seconds)
    if chaos_latency_max < chaos_latency_min:
        chaos_latency_max = chaos_latency_min

    chaos_mode = os.getenv("CHAOS_MODE", "off")
    chaos_mode_is_off = chaos_mode.strip().lower() in {
        "",
        "0",
        "false",
        "off",
        "none",
        "disabled",
        "disable",
    }
    chaos_rate_default = "0" if chaos_mode_is_off else "0.1"

    return Settings(
        project_endpoint=project_endpoint,
        model_deployment_name=model_deployment_name,
        log_level=os.getenv("TRAVEL_AGENT_LOG_LEVEL", "INFO"),
        tool_timeout_seconds=timeout,
        chaos_mode=chaos_mode,
        chaos_rate=max(
            0.0,
            min(float(os.getenv("CHAOS_RATE", chaos_rate_default)), 1.0),
        ),
        chaos_latency_min_seconds=chaos_latency_min,
        chaos_latency_max_seconds=chaos_latency_max,
    )


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
