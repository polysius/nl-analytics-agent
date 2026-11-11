"""Runtime settings, read from environment variables once at import time."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Read-only role used for every query the agent runs on behalf of a user.
    database_url: str = os.getenv("DATABASE_URL", "postgresql://agent_ro:agent_ro@localhost:5433/f1")
    # Admin role, used only to build the embedding catalogue and the roles.
    admin_database_url: str = os.getenv(
        "ADMIN_DATABASE_URL", "postgresql://admin:admin@localhost:5433/f1"
    )
    row_cap: int = int(os.getenv("ROW_CAP", "200"))
    statement_timeout_ms: int = int(os.getenv("STATEMENT_TIMEOUT_MS", "10000"))
    max_repair_retries: int = int(os.getenv("MAX_REPAIR_RETRIES", "2"))

    llm_provider: str = os.getenv("LLM_PROVIDER", "anthropic")  # anthropic | openai | stub
    llm_model: str = os.getenv("LLM_MODEL", "claude-sonnet-5-5")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")

    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    reranker_model: str = os.getenv("RERANKER_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")


settings = Settings()
