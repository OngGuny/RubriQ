"""설정. 시크릿은 .env에서만 읽는다 (.env.example 참조)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    langfuse_public_key: str | None = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="http://localhost:3001", alias="LANGFUSE_HOST")

    database_url: str = Field(
        default="postgresql://rubriq:rubriq@localhost:5432/rubriq", alias="DATABASE_URL"
    )

    # 재채점 루프 상한. 수렴 보장이 없어서 상한 없이는 latency가 폭발한다 (설계 문서 §1).
    max_regrade_loops: int = Field(default=2, ge=0, alias="RUBRIQ_MAX_REGRADE_LOOPS")

    # 회귀 게이트: 골든셋 QWK가 이 밑으로 떨어지면 CI를 fail 시킨다.
    regression_qwk_threshold: float = Field(
        default=0.60, ge=-1.0, le=1.0, alias="RUBRIQ_REGRESSION_QWK_THRESHOLD"
    )

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
