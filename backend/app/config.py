import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

# Load environment variables from .env so OPENAI_API_KEY and others are available
load_dotenv()

# OpenRouter configuration
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    app_env: str = "local"
    auth_mode: str = "google"
    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_base_url: str | None = None
    openai_chat_model: str = "gpt-4.1-mini"

    # OpenRouter settings for multi-model evaluation
    openrouter_api_key: str = ""
    openrouter_base_url: str = OPENROUTER_BASE_URL
    document_bucket: str = ""
    gcp_project: str = ""
    vertex_location: str = "global"
    vertex_chat_model: str = "gemini-3.5-flash-lite"
    frontend_service_account: str = ""
    backend_audience: str = ""
    quartr_api_key: str = ""
    quartr_api_base_url: str = "https://api.quartr.com/public/v3"
    data_max_age_hours: int = 168
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_max_output_tokens: int = 2048

    data_dir: Path = PROJECT_ROOT / "data"
    raw_dir: Path = PROJECT_ROOT / "data/raw"
    processed_dir: Path = PROJECT_ROOT / "data/processed"
    index_dir: Path = PROJECT_ROOT / "data/indexes"
    chroma_persist_dir: Path = PROJECT_ROOT / "data/indexes/chroma"


class AppConfig(BaseModel):
    settings: Settings


def get_settings(*, validate_llm: bool = True) -> Settings:
    app_env = os.environ.get("APP_ENV") or (
        "production" if os.environ.get("K_SERVICE") else "local"
    )
    data_dir = Path(os.environ.get("DATA_DIR") or PROJECT_ROOT / "data").expanduser().resolve()
    settings = Settings(
        app_env=app_env.lower(),
        auth_mode=os.environ.get(
            "AUTH_MODE", "google" if app_env.lower() == "production" else "disabled"
        ).lower(),
        llm_provider=os.environ.get("LLM_PROVIDER", "openai").lower(),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_base_url=os.environ.get("OPENAI_BASE_URL") or None,
        openai_chat_model=os.environ.get("OPENAI_CHAT_MODEL", "gpt-4.1-mini"),
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        openrouter_base_url=os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
        document_bucket=os.environ.get("DOCUMENT_BUCKET", ""),
        gcp_project=os.environ.get("GOOGLE_CLOUD_PROJECT", "") or os.environ.get("GCP_PROJECT", ""),
        vertex_location=os.environ.get("VERTEX_LOCATION", "global"),
        vertex_chat_model=os.environ.get("VERTEX_CHAT_MODEL", "gemini-3.5-flash-lite"),
        frontend_service_account=os.environ.get("FRONTEND_SERVICE_ACCOUNT", ""),
        backend_audience=os.environ.get("BACKEND_AUDIENCE", ""),
        quartr_api_key=os.environ.get("QUARTR_API_KEY", ""),
        quartr_api_base_url=os.environ.get(
            "QUARTR_API_BASE_URL", "https://api.quartr.com/public/v3"
        ),
        data_max_age_hours=int(os.environ.get("DATA_MAX_AGE_HOURS", "168")),
        llm_timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
        llm_max_retries=int(os.environ.get("LLM_MAX_RETRIES", "2")),
        llm_max_output_tokens=int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "2048")),
        data_dir=data_dir,
        raw_dir=data_dir / "raw",
        processed_dir=data_dir / "processed",
        index_dir=data_dir / "indexes",
        chroma_persist_dir=data_dir / "indexes" / "chroma",
    )

    if settings.auth_mode not in {"disabled", "google"}:
        raise ValueError("AUTH_MODE must be either 'disabled' or 'google'.")
    if settings.auth_mode == "disabled" and settings.app_env not in {
        "local",
        "development",
        "test",
    }:
        raise ValueError("AUTH_MODE=disabled is permitted only in a local or test environment.")
    if validate_llm and settings.llm_provider == "openai" and not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required but missing. Add it to your .env file.")
    if validate_llm and settings.llm_provider == "vertexai" and not settings.gcp_project:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required when LLM_PROVIDER=vertexai.")
    if settings.llm_provider not in {"openai", "vertexai"}:
        raise ValueError("LLM_PROVIDER must be either 'openai' or 'vertexai'.")
    if not 1 <= settings.llm_timeout_seconds <= 300:
        raise ValueError("LLM_TIMEOUT_SECONDS must be between 1 and 300 seconds.")
    if not 0 <= settings.llm_max_retries <= 5:
        raise ValueError("LLM_MAX_RETRIES must be between 0 and 5.")
    if not 128 <= settings.llm_max_output_tokens <= 8192:
        raise ValueError("LLM_MAX_OUTPUT_TOKENS must be between 128 and 8192.")

    return settings
