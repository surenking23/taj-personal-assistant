import os
from pathlib import Path


def get_api_token() -> str | None:
    return os.getenv("JARVIS_API_TOKEN")


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./jarvis.db")


def get_redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def get_workspace() -> Path:
    return Path(os.getenv("JARVIS_WORKSPACE", os.getcwd())).expanduser().resolve()


def get_ollama_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")


def get_ollama_model() -> str | None:
    return os.getenv("OLLAMA_MODEL") or None


def get_model_provider() -> str:
    return os.getenv("JARVIS_MODEL_PROVIDER", "copilot").casefold()


def get_copilot_model() -> str:
    return os.getenv("COPILOT_MODEL", "auto")


def get_openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or None


def get_openai_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")
