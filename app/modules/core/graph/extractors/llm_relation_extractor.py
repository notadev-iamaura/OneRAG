# app/modules/core/graph/extractors/llm_relation_extractor.py
"""
LLM 기반 관계 추출기

엔티티 간의 관계(파트너십, 위치, 소속 등)를 LLM을 사용하여 추출합니다.
IRelationExtractor 프로토콜을 구현하여 GraphRAGFactory와 호환됩니다.

생성일: 2026-01-05
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..models import Entity, Relation

logger = logging.getLogger(__name__)


# 관계 추출 프롬프트 템플릿 (코드 내장 기본값=한국어)
# 운영자는 graph_rag.yaml의 extraction.llm.relation_prompt_template로 코드 포크 없이
# 오버라이드한다. {text}/{entities}/{max_relations} 플레이스홀더 보존 필수.
RELATION_EXTRACTION_PROMPT = '''다음 텍스트에서 엔티티 간의 관계를 추출하세요.

텍스트:
{text}

인식된 엔티티:
{entities}

추출 규칙:
1. 텍스트에서 엔티티 간의 관계를 찾으세요
2. source와 target은 위의 엔티티 이름과 정확히 일치해야 합니다
3. 관계 강도(weight)는 0.0~1.0 범위로 설정하세요
4. 최대 {max_relations}개까지 추출하세요

관계 타입 목록:
- partnership: 파트너십, 제휴
- located_in: ~에 위치
- works_for: ~에 근무
- owns: 소유
- supplies: 납품, 공급
- competes_with: 경쟁 관계
- related_to: 기타 관련

응답 형식 (JSON 배열):
[
    {{"source": "엔티티A", "target": "엔티티B", "type": "관계타입", "weight": 0.8}},
    ...
]

JSON 응답만 출력하세요:'''


class LLMRelationExtractor:
    """
    LLM 기반 관계 추출기

    엔티티 간의 관계를 LLM을 사용하여 추출합니다.
    IRelationExtractor 프로토콜을 구현합니다.

    사용 예시:
        >>> extractor = LLMRelationExtractor(llm_client=llm_client)
        >>> entities = [Entity(id="e1", name="A", type="company"), ...]
        >>> relations = await extractor.extract("텍스트", entities)
    """

    # 기본 설정
    # prompt_template=None이면 코드 내장 RELATION_EXTRACTION_PROMPT(한국어)를 사용한다 → 회귀 0.
    DEFAULT_CONFIG: dict[str, Any] = {
        "max_relations": 30,
        "model": "google/gemini-2.5-flash-lite",
        "prompt_template": None,
    }

    def __init__(
        self,
        llm_client: Any,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Args:
            llm_client: LLM 클라이언트 (덕 타이핑 - generate(prompt: str) -> str 메서드 필요)
            config: 추출 설정 (max_relations, model, prompt_template 등)
                - prompt_template: config 외부화된 관계 추출 프롬프트.
                  None이면 코드 내장 한국어 기본 프롬프트 사용
                  ({text}/{entities}/{max_relations} 보존).

        Note:
            llm_client는 다음 인터페이스를 구현해야 합니다:
            - async def generate(prompt: str) -> str
        """
        self._llm_client = llm_client
        self._config = {**self.DEFAULT_CONFIG, **(config or {})}
        # 프롬프트 템플릿: config 오버라이드 없으면 코드 내장 한국어 기본값.
        self._prompt_template: str = (
            self._config.get("prompt_template") or RELATION_EXTRACTION_PROMPT
        )

    async def extract(
        self,
        text: str,
        entities: list[Entity],
    ) -> list[Relation]:
        """
        텍스트에서 엔티티 간 관계 추출

        Args:
            text: 추출 대상 텍스트
            entities: 이미 추출된 엔티티 리스트

        Returns:
            추출된 관계 리스트 (실패 시 빈 리스트)
        """
        # 엔티티 없으면 관계 추출 불가
        if not entities or len(entities) < 2:
            return []

        # 빈 텍스트 처리
        if not text or not text.strip():
            return []

        try:
            # 엔티티 이름 → ID 매핑
            name_to_id = {e.name: e.id for e in entities}

            # 프롬프트 생성
            entities_text = "\n".join(
                f"- {e.name} ({e.type})" for e in entities
            )
            prompt = self._prompt_template.format(
                text=text,
                entities=entities_text,
                max_relations=self._config["max_relations"],
            )

            # LLM 호출
            response = await self._llm_client.generate(prompt)

            # JSON 파싱
            relations = self._parse_response(response, name_to_id)

            logger.info(f"관계 {len(relations)}개 추출 완료")
            return relations

        except Exception as e:
            logger.warning(f"관계 추출 실패 (graceful degradation): {e}")
            return []

    def _parse_response(
        self,
        response: str,
        name_to_id: dict[str, str],
    ) -> list[Relation]:
        """
        LLM 응답 JSON 파싱

        Args:
            response: LLM 응답 텍스트
            name_to_id: 엔티티 이름 → ID 매핑

        Returns:
            파싱된 Relation 리스트

        Raises:
            json.JSONDecodeError: JSON 파싱 실패
        """
        # JSON 부분만 추출
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:-1])

        # JSON 파싱
        data = json.loads(response)

        # Relation 객체 변환
        relations: list[Relation] = []
        for item in data:
            source_name = item.get("source", "")
            target_name = item.get("target", "")

            # 이름 → ID 변환 (매핑에 없으면 이름 그대로 사용)
            source_id = name_to_id.get(source_name, source_name)
            target_id = name_to_id.get(target_name, target_name)

            relation = Relation(
                source_id=source_id,
                target_id=target_id,
                type=item.get("type", "related_to"),
                weight=float(item.get("weight", 0.5)),
                properties=item.get("properties", {}),
            )
            relations.append(relation)

        return relations
