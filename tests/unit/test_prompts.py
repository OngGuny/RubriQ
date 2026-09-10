"""프롬프트 로딩과 캐시 경계 검증.

이 파일이 지키는 핵심 불변식: **가변 내용이 캐시 프리픽스에 들어가지 않는다.**
어기면 에러 없이 캐시 히트율만 0이 되므로, 테스트로 못 잡으면 아무도 못 잡는다.
"""

from __future__ import annotations

import pytest

from rubriq.prompts.registry import (
    MalformedPrompt,
    Prompt,
    PromptNotFound,
    _parse,
    list_prompts,
    load_prompt,
)


class TestLoadPrompt:
    def test_loads_scoring_v1(self) -> None:
        p = load_prompt("scoring", "v1")
        assert p.id == "scoring@v1"
        assert p.system and p.user_template

    def test_missing_prompt_lists_alternatives(self) -> None:
        with pytest.raises(PromptNotFound, match="사용 가능"):
            load_prompt("scoring", "v99")

    def test_list_prompts_includes_scoring(self) -> None:
        assert "scoring_v1" in list_prompts()


class TestCacheBoundary:
    """캐시 프리픽스 오염 방지."""

    def test_essay_slot_only_in_user_block(self) -> None:
        p = load_prompt("scoring", "v1")
        assert "{{ESSAY}}" in p.user_template
        assert "{{ESSAY}}" not in p.system

    def test_variable_content_in_system_is_rejected(self) -> None:
        """캐시를 죽이는 대표적 실수를 로딩 시점에 잡는다."""
        raw = "rubric {{ESSAY}}\n<!-- CACHE_BOUNDARY -->\nessay: {{ESSAY}}"
        with pytest.raises(MalformedPrompt, match="캐시 히트율이 0"):
            _parse("x", "v1", raw)

    def test_missing_boundary_rejected(self) -> None:
        with pytest.raises(MalformedPrompt, match="정확히 한 번"):
            _parse("x", "v1", "no marker here {{ESSAY}}")

    def test_duplicate_boundary_rejected(self) -> None:
        raw = "a\n<!-- CACHE_BOUNDARY -->\nb\n<!-- CACHE_BOUNDARY -->\n{{ESSAY}}"
        with pytest.raises(MalformedPrompt, match="정확히 한 번"):
            _parse("x", "v1", raw)

    def test_missing_essay_slot_rejected(self) -> None:
        with pytest.raises(MalformedPrompt, match="슬롯이 없다"):
            _parse("x", "v1", "rubric\n<!-- CACHE_BOUNDARY -->\nno slot")

    def test_empty_system_rejected(self) -> None:
        with pytest.raises(MalformedPrompt, match="system 블록이 비어"):
            _parse("x", "v1", "  \n<!-- CACHE_BOUNDARY -->\n{{ESSAY}}")

    def test_system_is_byte_identical_across_renders(self) -> None:
        """서로 다른 에세이를 렌더해도 캐시 대상(system)은 변하지 않아야 한다."""
        p = load_prompt("scoring", "v1")
        before = p.system
        p.render_user("essay one")
        p.render_user("completely different essay two")
        assert p.system == before

    def test_system_exceeds_opus5_minimum_cacheable_prefix(self) -> None:
        """Claude Opus 5의 최소 캐시 프리픽스는 512토큰. 못 넘으면 조용히 캐시가 안 된다.

        정확한 토큰 수는 API 없이 셀 수 없어 문자 수로 보수적 하한을 잡는다
        (영문 기준 대략 4자/토큰이므로 2048자면 ~512토큰).
        """
        p = load_prompt("scoring", "v1")
        assert len(p.system) > 2048, (
            f"system 블록이 {len(p.system)}자로 짧다. 캐시가 안 먹을 수 있으니 "
            "실제 usage.cache_read_input_tokens로 확인할 것."
        )


class TestRender:
    def test_essay_is_substituted(self) -> None:
        p = load_prompt("scoring", "v1")
        assert "MY UNIQUE ESSAY" in p.render_user("MY UNIQUE ESSAY")

    def test_render_without_slot_raises(self) -> None:
        p = Prompt(name="x", version="v1", system="s", user_template="no slot")
        with pytest.raises(MalformedPrompt):
            p.render_user("essay")


class TestFingerprint:
    def test_is_stable(self) -> None:
        assert load_prompt("scoring", "v1").fingerprint == load_prompt("scoring", "v1").fingerprint

    def test_changes_when_content_changes(self) -> None:
        """버전만 올리고 내용을 안 바꾸거나, 내용만 바꾸고 버전을 안 올린 경우를 잡는다."""
        a = Prompt(name="x", version="v1", system="rubric A", user_template="{{ESSAY}}")
        b = Prompt(name="x", version="v1", system="rubric B", user_template="{{ESSAY}}")
        assert a.id == b.id
        assert a.fingerprint != b.fingerprint

    def test_is_twelve_hex_chars(self) -> None:
        fp = load_prompt("scoring", "v1").fingerprint
        assert len(fp) == 12
        assert all(c in "0123456789abcdef" for c in fp)
