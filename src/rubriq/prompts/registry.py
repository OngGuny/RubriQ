"""프롬프트 로딩과 버전 관리.

프롬프트를 코드에 하드코딩하지 않는 이유:
성능 변화를 프롬프트 변경과 연결하려면 어떤 버전이 쓰였는지 트레이스에 남아야 한다.
파일로 분리하고 버전 식별자를 붙여야 그게 가능하다.

프롬프트는 **고정부와 가변부로 나뉘어 있다.** 캐시는 프리픽스 매칭이라
가변 내용이 앞에 끼면 그 뒤가 전부 캐시 미스가 된다 (ADR 003).
- `system_block()`  → 요청 간 바이트 단위로 동일. 캐시 대상
- `user_block()`    → 에세이마다 달라짐. 캐시 경계 뒤
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "templates"

# 가변 슬롯. 템플릿의 이 자리에 에세이가 들어간다.
_ESSAY_SLOT = "{{ESSAY}}"
_SPLIT_MARKER = "<!-- CACHE_BOUNDARY -->"


class PromptNotFound(FileNotFoundError):
    pass


class MalformedPrompt(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Prompt:
    """고정/가변이 분리된 프롬프트.

    Attributes:
        name: 프롬프트 이름 (예: "scoring")
        version: 버전 식별자 (예: "v1")
        system: 캐시 대상 고정부
        user_template: `{{ESSAY}}` 슬롯을 가진 가변부
    """

    name: str
    version: str
    system: str
    user_template: str

    @property
    def id(self) -> str:
        """트레이스·리포트에 남기는 식별자."""
        return f"{self.name}@{self.version}"

    @property
    def fingerprint(self) -> str:
        """내용 해시 앞 12자.

        버전 문자열을 안 올리고 내용만 고친 경우를 잡는다.
        측정 결과와 프롬프트를 대조할 때 버전만 믿으면 조용히 틀린다.
        """
        digest = hashlib.sha256((self.system + self.user_template).encode("utf-8"))
        return digest.hexdigest()[:12]

    def render_user(self, essay_text: str) -> str:
        if _ESSAY_SLOT not in self.user_template:
            raise MalformedPrompt(f"{self.id}: user 블록에 {_ESSAY_SLOT} 슬롯이 없다")
        return self.user_template.replace(_ESSAY_SLOT, essay_text)


def _parse(name: str, version: str, raw: str) -> Prompt:
    if raw.count(_SPLIT_MARKER) != 1:
        raise MalformedPrompt(
            f"{name}@{version}: {_SPLIT_MARKER} 가 정확히 한 번 있어야 한다 "
            f"(발견 {raw.count(_SPLIT_MARKER)}회). 고정부/가변부 경계를 표시하는 마커다."
        )
    system, user_template = raw.split(_SPLIT_MARKER)
    system, user_template = system.strip(), user_template.strip()
    if not system:
        raise MalformedPrompt(f"{name}@{version}: system 블록이 비어 있다")
    if _ESSAY_SLOT not in user_template:
        raise MalformedPrompt(f"{name}@{version}: user 블록에 {_ESSAY_SLOT} 슬롯이 없다")
    if _ESSAY_SLOT in system:
        # 이게 캐시를 죽이는 대표적인 실수다.
        raise MalformedPrompt(
            f"{name}@{version}: system 블록에 {_ESSAY_SLOT}가 있다. "
            "가변 내용이 캐시 프리픽스에 들어가면 캐시 히트율이 0이 된다."
        )
    return Prompt(name=name, version=version, system=system, user_template=user_template)


@lru_cache
def load_prompt(name: str, version: str = "v1") -> Prompt:
    """`templates/{name}_{version}.md`를 읽는다."""
    path = TEMPLATE_DIR / f"{name}_{version}.md"
    if not path.exists():
        available = sorted(p.stem for p in TEMPLATE_DIR.glob("*.md"))
        raise PromptNotFound(f"{path} 없음. 사용 가능: {available}")
    return _parse(name, version, path.read_text(encoding="utf-8"))


def list_prompts() -> list[str]:
    return sorted(p.stem for p in TEMPLATE_DIR.glob("*.md"))
