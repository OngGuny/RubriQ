"""채점 파이프라인의 데이터 계약.

여기서 강제하는 것 두 가지:
1. 루브릭 6개 항목이 정확히 한 번씩 채점됐는가
2. 모든 점수에 본문 인용 근거가 붙었는가 (설계 문서 §1 "근거 인용 강제")

2번은 essay 원문이 필요해 Pydantic validator로 못 넣는다. `ungrounded_evidence()`로 분리했고,
후처리 노드가 호출한다. 스키마 안에서 닫히지 않는 검증이라는 점을 명시해 둔다.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCORE_MIN = 1
SCORE_MAX = 5
SCORE_LABELS: tuple[int, ...] = (1, 2, 3, 4, 5)


class RubricDimension(StrEnum):
    """ELLIPSE 분석적 루브릭 6개 항목."""

    COHESION = "cohesion"
    SYNTAX = "syntax"
    VOCABULARY = "vocabulary"
    PHRASEOLOGY = "phraseology"
    GRAMMAR = "grammar"
    CONVENTIONS = "conventions"


ALL_DIMENSIONS: tuple[RubricDimension, ...] = tuple(RubricDimension)


class GradeLevel(StrEnum):
    ELEMENTARY = "elementary"
    MIDDLE = "middle"
    HIGH = "high"


class Essay(BaseModel):
    """채점 대상 입력."""

    model_config = ConfigDict(frozen=True)

    essay_id: str
    text: str = Field(min_length=1)
    grade_level: GradeLevel | None = None
    task_type: str | None = None
    prompt: str | None = Field(default=None, description="에세이 과제 지시문")

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("essay text is blank")
        return v

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class Evidence(BaseModel):
    """점수의 근거가 되는 본문 인용.

    offset은 선택이다. LLM이 뱉은 offset은 신뢰할 수 없어서, 원문 대조는 quote 문자열로 한다.
    """

    model_config = ConfigDict(frozen=True)

    quote: str = Field(min_length=1)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _offsets_consistent(self) -> Evidence:
        if (self.start is None) != (self.end is None):
            raise ValueError("start/end must be given together")
        if self.start is not None and self.end is not None:
            if self.end <= self.start:
                raise ValueError(f"end({self.end}) must be > start({self.start})")
            if self.end - self.start != len(self.quote):
                raise ValueError(
                    f"span length {self.end - self.start} != quote length {len(self.quote)}"
                )
        return self


class DimensionScore(BaseModel):
    """루브릭 한 항목의 채점 결과."""

    model_config = ConfigDict(frozen=True)

    dimension: RubricDimension
    score: int = Field(ge=SCORE_MIN, le=SCORE_MAX)
    rationale: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1, description="근거 없는 점수는 허용하지 않는다")


class GrammarError(BaseModel):
    """결정적 도구(LanguageTool 등)가 뽑은 오류. LLM 판단이 아니다."""

    model_config = ConfigDict(frozen=True)

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    rule_id: str
    message: str
    suggestion: str | None = None

    @model_validator(mode="after")
    def _span_valid(self) -> GrammarError:
        if self.end <= self.start:
            raise ValueError(f"end({self.end}) must be > start({self.start})")
        return self


class GradingResult(BaseModel):
    """채점 최종 산출물."""

    essay_id: str
    scores: list[DimensionScore] = Field(min_length=1)
    teacher_comment: str | None = None
    needs_human_review: bool = False
    review_reason: str | None = None
    regrade_count: int = Field(default=0, ge=0)
    prompt_version: str | None = None
    model_name: str | None = None

    @model_validator(mode="after")
    def _dimensions_exactly_once(self) -> GradingResult:
        seen = [s.dimension for s in self.scores]
        dupes = {d for d in seen if seen.count(d) > 1}
        if dupes:
            raise ValueError(f"duplicate dimensions: {sorted(d.value for d in dupes)}")
        missing = set(ALL_DIMENSIONS) - set(seen)
        if missing:
            raise ValueError(f"missing dimensions: {sorted(d.value for d in missing)}")
        return self

    @model_validator(mode="after")
    def _review_reason_present(self) -> GradingResult:
        # 사람에게 넘길 때 이유를 안 남기면 넘겨받은 사람이 할 수 있는 게 없다.
        if self.needs_human_review and not self.review_reason:
            raise ValueError("needs_human_review=True requires review_reason")
        return self

    def score_of(self, dimension: RubricDimension) -> int:
        return next(s.score for s in self.scores if s.dimension is dimension)

    def score_map(self) -> dict[RubricDimension, int]:
        return {s.dimension: s.score for s in self.scores}


def ungrounded_evidence(
    result: GradingResult, essay_text: str
) -> list[tuple[RubricDimension, Evidence]]:
    """원문에서 찾을 수 없는 인용을 모두 돌려준다. 빈 리스트면 전부 grounded.

    LLM이 그럴듯한 문장을 지어내 근거로 다는 경우를 잡는 검사다.
    공백만 정규화해서 비교한다 — 줄바꿈 차이로 오탐이 나면 검사 자체를 신뢰 못 하게 된다.
    """
    haystack = " ".join(essay_text.split())
    bad: list[tuple[RubricDimension, Evidence]] = []
    for dim_score in result.scores:
        for ev in dim_score.evidence:
            needle = " ".join(ev.quote.split())
            if needle not in haystack:
                bad.append((dim_score.dimension, ev))
    return bad
