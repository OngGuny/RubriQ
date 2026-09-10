"""LLM 클라이언트 인터페이스와 비용 계산.

벤더를 프로토콜 뒤로 감추는 이유는 T2의 모델 라우팅 때문이다 (설계 문서 §4).
항목별로 경량/고성능 모델을 배분해 비용·QWK 트레이드오프를 재려면
호출부가 벤더를 몰라야 한다.

토큰 사용량을 응답에 같이 실어 나르는 것도 의도적이다.
'에세이당 비용'이 설계 문서 §3의 필수 지표라서, 나중에 붙이면 호출부를 다 고쳐야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """한 번의 호출에서 쓴 토큰."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )

    @property
    def cache_hit(self) -> bool:
        """캐시가 실제로 먹었는가. 0이면 무언가가 프리픽스를 무효화하고 있다는 뜻."""
        return self.cache_read_tokens > 0


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """1M 토큰당 USD."""

    input_per_mtok: float
    output_per_mtok: float
    # 캐시 읽기는 입력가의 약 0.1배, 쓰기는 약 1.25배.
    cache_read_multiplier: float = 0.1
    cache_write_multiplier: float = 1.25


# 2026-06 기준 Anthropic 1st-party 요금. 모델을 추가하면 여기에 같이 추가한다.
PRICING: dict[str, ModelPricing] = {
    "claude-opus-5": ModelPricing(5.00, 25.00),
    "claude-opus-4-8": ModelPricing(5.00, 25.00),
    "claude-sonnet-5": ModelPricing(2.00, 10.00),
    "claude-haiku-4-5": ModelPricing(1.00, 5.00),
    "claude-fable-5-1": ModelPricing(10.00, 50.00),
}


class UnknownModelPricing(KeyError):
    """요금표에 없는 모델. 비용을 0으로 위장하지 않고 예외로 올린다."""


def estimate_cost_usd(model: str, usage: TokenUsage) -> float:
    """호출 1회 비용(USD).

    요금표에 없으면 예외를 던진다. 모르는 모델의 비용을 0으로 계산하면
    '비용 절감했다'는 잘못된 결론이 나온다.
    """
    try:
        p = PRICING[model]
    except KeyError as e:
        raise UnknownModelPricing(
            f"{model}의 요금 정보가 없다. rubriq.llm.base.PRICING에 추가할 것."
        ) from e
    return (
        usage.input_tokens * p.input_per_mtok
        + usage.output_tokens * p.output_per_mtok
        + usage.cache_read_tokens * p.input_per_mtok * p.cache_read_multiplier
        + usage.cache_write_tokens * p.input_per_mtok * p.cache_write_multiplier
    ) / 1_000_000


@dataclass(frozen=True, slots=True)
class LLMResult[T: BaseModel]:
    """구조화 출력 + 그 호출의 관측값."""

    output: T
    model: str
    usage: TokenUsage
    latency_ms: float
    raw_stop_reason: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def cost_usd(self) -> float:
        return estimate_cost_usd(self.model, self.usage)


class StructuredLLM(Protocol):
    """구조화 출력을 돌려주는 LLM.

    `cacheable_system`은 요청 간 **바이트 단위로 동일해야** 캐시가 먹는다.
    가변 내용(에세이, 타임스탬프)을 여기 넣으면 캐시 히트율이 0이 된다.
    """

    def complete[T: BaseModel](
        self,
        *,
        cacheable_system: str,
        user_content: str,
        schema: type[T],
    ) -> LLMResult[T]: ...
