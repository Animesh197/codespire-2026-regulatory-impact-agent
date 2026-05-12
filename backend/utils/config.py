from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (directory containing `backend/`)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM: Groq (OpenAI-compatible) and/or OpenAI
    llm_provider: Literal["auto", "groq", "openai"] = "auto"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.3-70b-versatile"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Embeddings: local (no OpenAI key) or OpenAI
    embedding_provider: Literal["auto", "local", "openai"] = "auto"
    embedding_model: str = "text-embedding-3-small"
    local_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    upload_dir: str = str(_PROJECT_ROOT / "data" / "uploads")
    results_dir: str = str(_PROJECT_ROOT / "data" / "results")
    max_upload_bytes: int = 15 * 1024 * 1024
    chunk_size: int = 800
    chunk_overlap: int = 120
    retrieval_k: int = 5
    max_regulation_chunks_for_compare: int = 24


settings = Settings()


def resolved_llm_provider() -> Literal["groq", "openai"]:
    s = settings
    if s.llm_provider == "groq":
        if not s.groq_api_key.strip():
            raise RuntimeError("LLM_PROVIDER=groq but GROQ_API_KEY is empty.")
        return "groq"
    if s.llm_provider == "openai":
        if not s.openai_api_key.strip():
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is empty.")
        return "openai"
    if s.groq_api_key.strip():
        return "groq"
    if s.openai_api_key.strip():
        return "openai"
    raise RuntimeError("Set GROQ_API_KEY and/or OPENAI_API_KEY in .env (or set LLM_PROVIDER explicitly).")


def resolved_embedding_provider() -> Literal["local", "openai"]:
    s = settings
    if s.embedding_provider == "local":
        return "local"
    if s.embedding_provider == "openai":
        if not s.openai_api_key.strip():
            raise RuntimeError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY.")
        return "openai"
    # auto
    if s.openai_api_key.strip():
        return "openai"
    return "local"
