"""Anthropic 구조화 출력 클라이언트.

설계 메모:
- `client.messages.parse(output_format=<Pydantic 모델>)`를 쓴다. 응답이 스키마에 맞는지
  SDK가 검증해 `parsed_output`으로 준다. 이 프로젝트는 후처리 스키마 검증이 요구사항이라
  (설계 문서 §1) 직접 json.loads 하는 경로보다 이쪽이 맞다.
- 고정 블록은 `system`에, 가변 블록(에세이)은 `messages`에 둔다.
  렌더 순서가 tools → system → messages라서, 이렇게 놔야 system 전체가 캐시 프리픽스가 된다.
  `cache_control`은 system 끝에 건다.
- refusal fallback(`betas=["server-side-fallback-..."]`)은 쓰지 않는다.
  에세이 채점은 거부 표면이 사실상 없고, fallback은 `client.beta.messages` 경로라
  `parse()`의 스키마 검증과 조합이 문서화돼 있지 않다. 스키마 검증이 이 프로젝트에서 더 중요하다.
  거부가 실제로 관측되면 그때 도입한다.
"""

from __future__ import annotations

import time
from typing import Literal, cast, get_args

import anthropic
from anthropic.types import CacheControlEphemeralParam, OutputConfigParam, TextBlockParam
from pydantic import BaseModel

from rubriq.llm.base import LLMResult, TokenUsage

Effort = Literal["low", "medium", "high", "xhigh", "max"]
VALID_EFFORTS: tuple[str, ...] = get_args(Effort)

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16_000


class AnthropicStructuredLLM:
    """`StructuredLLM` 프로토콜의 Anthropic 구현."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        effort: Effort = "medium",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        enable_caching: bool = True,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        """
        Args:
            effort: low | medium | high | xhigh | max. 사고 깊이와 토큰 지출을 조절한다.
                베이스라인 기본값을 medium으로 둔 건 임의 선택이며,
                effort 스윕은 그 자체가 측정 대상이다 (비용 대비 QWK).
            enable_caching: 루브릭 정의부 캐싱. 끄고 켜서 비용·latency를 비교하기 위해
                설정으로 뺐다 (설계 문서 T2 「프롬프트 캐싱 전후 비교」).
        """
        if effort not in VALID_EFFORTS:
            raise ValueError(f"effort는 {VALID_EFFORTS} 중 하나여야 한다 (받은 값: {effort})")
        self._client = client or anthropic.Anthropic()
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._enable_caching = enable_caching

    @property
    def model(self) -> str:
        return self._model

    def complete[T: BaseModel](
        self,
        *,
        cacheable_system: str,
        user_content: str,
        schema: type[T],
    ) -> LLMResult[T]:
        system_block = TextBlockParam(type="text", text=cacheable_system)
        if self._enable_caching:
            # 캐시 경계는 system 끝. 렌더 순서가 tools → system → messages라
            # 여기까지가 프리픽스가 된다.
            system_block["cache_control"] = CacheControlEphemeralParam(type="ephemeral")

        started = time.perf_counter()
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            output_config=cast(OutputConfigParam, {"effort": self._effort}),
            system=[system_block],
            messages=[{"role": "user", "content": user_content}],
            output_format=schema,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0

        # 거부는 예외가 아니라 stop_reason으로 온다. content를 읽기 전에 확인한다.
        if response.stop_reason == "refusal":
            detail = getattr(response, "stop_details", None)
            category = getattr(detail, "category", None)
            raise RefusalError(f"모델이 채점을 거부했다 (category={category})")

        parsed = response.parsed_output
        if parsed is None:
            raise SchemaViolationError(
                f"구조화 출력 파싱 실패 (stop_reason={response.stop_reason}). "
                "max_tokens 초과로 잘렸을 가능성을 먼저 확인할 것."
            )

        usage = response.usage
        return LLMResult(
            output=parsed,
            model=response.model or self._model,
            usage=TokenUsage(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            ),
            latency_ms=latency_ms,
            raw_stop_reason=response.stop_reason,
        )


class RefusalError(RuntimeError):
    """모델이 안전상 이유로 응답을 거부했다."""


class SchemaViolationError(RuntimeError):
    """구조화 출력이 스키마를 만족하지 못했다."""
