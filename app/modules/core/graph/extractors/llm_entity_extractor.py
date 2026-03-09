# app/modules/core/graph/extractors/llm_entity_extractor.py
"""
LLM 기반 엔티티 추출기

텍스트에서 엔티티(인물, 회사, 장소 등)를 LLM을 사용하여 추출합니다.
IEntityExtractor 프로토콜을 구현하여 GraphRAGFactory와 호환됩니다.

생성일: 2026-01-05
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from ..models import Entity

logger = logging.getLogger(__name__)


# 엔티티 추출 프롬프트 템플릿
ENTITY_EXTRACTION_PROMPT = '''다음 텍스트에서 엔티티(개체명)를 추출하세요.

텍스트:
{text}

추출 규칙:
1. 인물, 회사, 장소, 제품, 날짜 등의 엔티티를 찾으세요
2. 각 엔티티의 이름과 타입을 식별하세요
3. 최대 {max_entities}개까지 추출하세요

응답 형식 (JSON 배열):
[
    {{"name": "엔티티명", "type": "엔티티타입"}},
    ...
]

엔티티 타입 목록:
- person: 인물, 담당자
- company: 회사, 기업, 기관
- location: 장소, 지역, 주소
- product: 제품, 서비스
- date: 날짜, 기간
- event: 행사, 이벤트
- other: 기타

JSON 응답만 출력하세요:'''


class LLMEntityExtractor:
    """
    LLM 기반 엔티티 추출기

    Gemini, GPT 등 LLM을 사용하여 텍스트에서 엔티티를 추출합니다.
    IEntityExtractor 프로토콜을 구현합니다.

    사용 예시:
        >>> from app.modules.core.generation import LLMFactory
        >>> llm_client = LLMFactory.create(config)
        >>> extractor = LLMEntityExtractor(llm_client=llm_client)
        >>> entities = await extractor.extract("A사는 서울에 있습니다.")
        >>> print(entities)
        [Entity(name="A사", type="company"), Entity(name="서울", type="location")]
    """

    # 기본 설정
    DEFAULT_CONFIG: dict[str, Any] = {
        "max_entities": 20,
        "model": "google/gemini-2.5-flash-lite",
    }

    def __init__(
        self,
        llm_client: Any,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Args:
            llm_client: LLM 클라이언트 (덕 타이핑 - generate(prompt: str) -> str 메서드 필요)
            config: 추출 설정 (max_entities, model 등)

        Note:
            llm_client는 다음 인터페이스를 구현해야 합니다:
            - async def generate(prompt: str) -> str
        """
        self._llm_client = llm_client
        self._config = {**self.DEFAULT_CONFIG, **(config or {})}

    async def extract(self, text: str) -> list[Entity]:
        """
        텍스트에서 엔티티 추출

        Args:
            text: 추출 대상 텍스트

        Returns:
            추출된 엔티티 리스트 (실패 시 빈 리스트)
        """
        # 빈 텍스트 처리
        if not text or not text.strip():
            return []

        try:
            # 프롬프트 생성
            prompt = ENTITY_EXTRACTION_PROMPT.format(
                text=text,
                max_entities=self._config["max_entities"],
            )

            # LLM 호출
            response = await self._llm_client.generate(prompt)

            # JSON 파싱
            entities = self._parse_response(response)

            logger.info(f"엔티티 {len(entities)}개 추출 완료")
            return entities

        except Exception as e:
            logger.warning(f"엔티티 추출 실패 (graceful degradation): {e}")
            return []

    def _parse_response(self, response: str) -> list[Entity]:
        """
        LLM 응답 JSON 파싱

        Args:
            response: LLM 응답 텍스트

        Returns:
            파싱된 Entity 리스트

        Raises:
            json.JSONDecodeError: JSON 파싱 실패
        """
        # JSON 부분만 추출 (코드 블록 처리)
        response = response.strip()
        if response.startswith("```"):
            # ```json ... ``` 형식 처리
            lines = response.split("\n")
            response = "\n".join(lines[1:-1])

        # JSON 파싱
        data = json.loads(response)

        # Entity 객체 변환
        entities: list[Entity] = []
        for item in data:
            entity = Entity(
                id=str(uuid.uuid4()),
                name=item.get("name", ""),
                type=item.get("type", "other"),
                properties=item.get("properties", {}),
            )
            entities.append(entity)

        return entities
