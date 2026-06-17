"""
Notion API 기반 메타데이터 추출기 (범용)

Notion 데이터베이스에서 직접 페이지 콘텐츠를 조회하고
LLM을 통해 구조화된 메타데이터를 추출합니다.

특징:
- 설정 파일(domain.yaml) 기반으로 카테고리와 DB ID를 동적으로 로드
- 범용 스키마(GenericMetadataSchema) 사용으로 도메인 의존성 제거
- 프롬프트 파일(extraction_prompts.json)을 통한 외부 프롬프트 주입
"""

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.batch.metadata_augmentation.metadata_schemas.generic import GenericMetadataSchema
from app.batch.notion_client import NotionAPIClient, NotionPage
from app.lib.config_loader import load_config
from app.lib.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# 기본 프롬프트 상수
# =============================================================================
# 카테고리별 외부 프롬프트(extraction_prompts.json)가 모두 없을 때 사용하는
# 최후 폴백 프롬프트. system 메시지가 영어(JSON 추출 전문가)이므로 user 폴백도
# 언어 중립(영어)으로 유지해 비일관을 제거한다(도메인 범용 OSS RAG 정체성).
# 운영자는 extraction_prompts.json에 카테고리별/default 프롬프트를 추가해
# 이 상수를 오버라이드할 수 있다(회귀 0: 외부 프롬프트가 있으면 그대로 우선).
_DEFAULT_EXTRACTION_PROMPT: str = (
    "Analyze the information below and extract metadata as JSON.\n\n"
    "Information:\n{content}\n\nJSON:"
)


# =============================================================================
# 데이터 클래스
# =============================================================================


@dataclass
class ExtractionResult:
    """메타데이터 추출 결과"""

    entity_name: str
    category: str
    page_id: str
    extraction_rate: float
    filled_fields: int
    total_fields: int
    metadata: dict[str, Any]
    raw_content: str = ""
    error: str | None = None
    extracted_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class BatchResult:
    """배치 추출 결과"""

    category: str
    total_pages: int
    success_count: int
    failed_count: int
    average_extraction_rate: float
    results: list[ExtractionResult]
    duration_seconds: float


# =============================================================================
# 메인 추출기 클래스
# =============================================================================


class NotionMetadataExtractor:
    """
    Notion API 기반 메타데이터 추출기 (범용)
    """

    def __init__(
        self,
        notion_api_key: str | None = None,
        openrouter_api_key: str | None = None,
        output_dir: str = "data/metadata",
        model: str = "anthropic/claude-sonnet-4",
    ):
        """
        추출기 초기화

        Args:
            notion_api_key: Notion API 키
            openrouter_api_key: OpenRouter API 키
            output_dir: 결과 저장 디렉토리
            model: 사용할 LLM 모델
        """
        # 설정 로드 (검증 없이 로드하여 유연성 확보)
        self.config = load_config(validate=False)
        domain_config = self.config.get("domain", {})
        batch_config = domain_config.get("batch", {})
        metadata_config = domain_config.get("metadata", {}).get("schema", {})

        # 카테고리 설정 매핑 (예: product -> db_id)
        self.categories_config = batch_config.get("categories", {})
        self.database_ids = {
            k: v["db_id"] for k, v in self.categories_config.items() if "db_id" in v
        }

        # 메타데이터 스키마 규칙 주입
        self._setup_schema_validation(metadata_config)
        self.field_aliases = metadata_config.get("field_aliases", {})

        # 프롬프트 로드
        self.prompts = self._load_prompts()

        # 클라이언트 설정
        self.notion_api_key = notion_api_key or os.getenv("NOTION_API_KEY")
        if not self.notion_api_key:
            raise ValueError("NOTION_API_KEY가 설정되지 않았습니다.")

        self.notion_client = NotionAPIClient(api_key=self.notion_api_key)

        self.openrouter_api_key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY가 설정되지 않았습니다.")

        self.llm_client = AsyncOpenAI(
            api_key=self.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )

        self.model = model
        self.output_dir = Path(output_dir)

        logger.info(
            f"✅ NotionMetadataExtractor 초기화 완료 (model={model}, "
            f"categories={list(self.database_ids.keys())})"
        )

    def _setup_schema_validation(self, metadata_config: dict[str, Any]):
        """범용 스키마에 검증 규칙 및 파싱 규칙 설정.

        검증 규칙(required/numeric/boolean 필드)에 더해, 파싱 규칙
        (domain.metadata.schema.parsing — 통화/날짜/불리언/null 토큰)도 주입한다.
        parsing 키가 없으면 코드 기본값(한국어 + 언어 중립)을 유지한다(회귀 0).
        """
        required = metadata_config.get("required_fields", ["name"])
        numeric = metadata_config.get("numeric_fields", [])
        boolean = metadata_config.get("boolean_fields", [])

        GenericMetadataSchema.set_validation_rules(
            required=required,
            numeric=numeric,
            boolean=boolean
        )

        # 파싱 규칙 외부화: config 미설정 시 코드 기본값 유지(회귀 0).
        parsing_config = metadata_config.get("parsing")
        GenericMetadataSchema.set_parsing_config(parsing_config)

        logger.info("🔧 범용 스키마 검증/파싱 규칙 설정 완료")

    def _load_prompts(self) -> dict[str, str]:
        """프롬프트 파일 로드"""
        prompt_path = Path("data/prompts/extraction_prompts.json")
        if prompt_path.exists():
            try:
                with open(prompt_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"프롬프트 로드 실패: {e}")
                return {}
        return {}

    async def close(self):
        """리소스 정리"""
        await self.notion_client.close()

    # =========================================================================
    # 핵심 추출 메서드
    # =========================================================================

    async def extract_category(
        self,
        category: str,
        limit: int | None = None,
        save_results: bool = True,
    ) -> BatchResult:
        """
        특정 카테고리의 모든 메타데이터 추출
        """
        import time
        start_time = time.time()

        if category not in self.database_ids:
            raise ValueError(f"설정되지 않은 카테고리: {category}")

        database_id = self.database_ids[category]
        logger.info(f"🚀 '{category}' 카테고리 추출 시작 (DB: {database_id})")

        # 1. Notion 데이터베이스 조회
        db_result = await self.notion_client.query_database(database_id)
        pages = db_result.pages

        if limit:
            pages = pages[:limit]
            logger.info(f"  📋 테스트 모드: {limit}개 페이지만 처리")

        # 2. 각 페이지 처리
        results: list[ExtractionResult] = []
        success_count = 0

        for idx, page in enumerate(pages, 1):
            logger.info(f"  [{idx}/{len(pages)}] 처리 중: {page.title}")

            try:
                result = await self._extract_single_page(page, category)
                results.append(result)

                if result.error is None:
                    success_count += 1
                    logger.info(
                        f"    ✅ 추출 완료: {result.extraction_rate:.1f}% "
                        f"({result.filled_fields}/{result.total_fields} 필드)"
                    )
                else:
                    logger.warning(f"    ⚠️ 추출 실패: {result.error}")

                # Rate Limit 방지
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"    ❌ 예외 발생: {e}")
                results.append(ExtractionResult(
                    entity_name=page.title,
                    category=category,
                    page_id=page.id,
                    extraction_rate=0.0,
                    filled_fields=0,
                    total_fields=0,
                    metadata={},
                    error=str(e),
                ))

        # 3. 결과 저장
        if save_results:
            await self._save_results(category, results)

        # 4. 통계 계산
        duration = time.time() - start_time
        avg_rate = sum(r.extraction_rate for r in results) / len(results) if results else 0.0

        return BatchResult(
            category=category,
            total_pages=len(pages),
            success_count=success_count,
            failed_count=len(pages) - success_count,
            average_extraction_rate=avg_rate,
            results=results,
            duration_seconds=duration,
        )

    async def _extract_single_page(
        self,
        page: NotionPage,
        category: str,
    ) -> ExtractionResult:
        """단일 페이지에서 메타데이터 추출"""
        # 1. 페이지 본문 콘텐츠 조회
        content = await self.notion_client.get_page_content(page.id)
        properties_text = self._properties_to_text(page.properties)
        full_content = f"제목: {page.title}\n\n{properties_text}\n\n{content}"

        if not full_content.strip():
            return ExtractionResult(
                entity_name=page.title,
                category=category,
                page_id=page.id,
                extraction_rate=0.0,
                filled_fields=0,
                total_fields=0,
                metadata={},
                raw_content="",
                error="콘텐츠 없음",
            )

        # 2. LLM으로 구조화 추출
        extracted_data = await self._call_llm(full_content, category)

        if extracted_data is None:
            return ExtractionResult(
                entity_name=page.title,
                category=category,
                page_id=page.id,
                extraction_rate=0.0,
                filled_fields=0,
                total_fields=0,
                metadata={},
                raw_content=full_content[:500],
                error="LLM 추출 실패",
            )

        # 3. 이름 필드 강제 설정 (별칭 사용)
        # category에 해당하는 이름 필드를 찾거나 기본값 사용
        # 여기서는 간단히 page.title을 name으로 사용
        extracted_data["name"] = page.title
        extracted_data["category"] = category

        # 4. GenericMetadataSchema로 검증
        try:
            # 동적 스키마 사용
            validated = GenericMetadataSchema.model_validate(extracted_data)

            # 별칭 적용하여 저장용 딕셔너리 생성 (선택 사항)
            # 여기서는 원본 키를 유지하되, 필요한 경우 display_dict 사용
            metadata = validated.model_dump()

            filled, total = validated.get_filled_field_count()
            rate = validated.get_extraction_rate()

            return ExtractionResult(
                entity_name=page.title,
                category=category,
                page_id=page.id,
                extraction_rate=rate,
                filled_fields=filled,
                total_fields=total,
                metadata=metadata,
                raw_content=full_content[:500],
            )

        except ValidationError as e:
            return ExtractionResult(
                entity_name=page.title,
                category=category,
                page_id=page.id,
                extraction_rate=0.0,
                filled_fields=0,
                total_fields=0,
                metadata=extracted_data,
                raw_content=full_content[:500],
                error=f"검증 실패: {str(e)[:100]}",
            )

    def _properties_to_text(self, properties: dict[str, Any]) -> str:
        """Notion 속성을 텍스트로 변환"""
        lines = []
        for key, value in properties.items():
            if value:
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value)
                lines.append(f"{key}: {value}")
        return "\n".join(lines)

    async def _call_llm(self, content: str, category: str) -> dict | None:
        """LLM 호출"""
        # 카테고리별 템플릿 가져오기 (기본값 제공)
        prompt_template = self.prompts.get(category, self.prompts.get("default", ""))

        # 템플릿이 없으면 언어 중립(영어) 기본 프롬프트 사용
        # system 메시지가 영어이므로 user 폴백도 영어로 통일한다(비일관 제거).
        if not prompt_template:
            prompt_template = _DEFAULT_EXTRACTION_PROMPT

        # 템플릿 포맷팅 (category_name 등 주입)
        category_name = self.categories_config.get(category, {}).get("category_name", category)
        prompt = prompt_template.format(
            content=content[:8000], # 토큰 제한
            category_name=category_name
        )

        try:
            response = await self.llm_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a JSON extraction expert. Output valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=4000,
            )
            raw = response.choices[0].message.content or ""
            return self._parse_json_response(raw)
        except Exception as e:
            logger.error(f"LLM 호출 실패: {e}")
            return None

    def _parse_json_response(self, response: str) -> dict | None:
        """JSON 파싱 (코드 블록 처리 포함)"""
        # 1. ```json ... ``` 제거
        if "```" in response:
            parts = response.split("```")
            for part in parts:
                if "{" in part:
                    response = part
                    if response.startswith("json"):
                        response = response[4:]
                    break

        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            return None

    async def _save_results(self, category: str, results: list[ExtractionResult]):
        """결과 저장"""
        output_path = self.output_dir / category
        output_path.mkdir(parents=True, exist_ok=True)

        for result in results:
            if result.entity_name:
                safe_name = re.sub(r'[\\/*?:\"<>|]', "", result.entity_name)
                file_path = output_path / f"{safe_name}.json"

                data = {
                    "entity_name": result.entity_name,
                    "category": result.category,
                    "page_id": result.page_id,
                    "extraction_rate": result.extraction_rate,
                    "filled_fields": result.filled_fields,
                    "total_fields": result.total_fields,
                    "metadata": result.metadata,
                    "extracted_at": result.extracted_at,
                }
                if result.error:
                    data["error"] = result.error

                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

# =============================================================================
# CLI 실행
# =============================================================================

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Notion API 기반 메타데이터 추출 (범용)")
    parser.add_argument("--category", default="all", help="추출할 카테고리 키 (domain.yaml 참조)")
    parser.add_argument("--limit", type=int, default=None, help="테스트용 페이지 제한")
    parser.add_argument("--model", default="anthropic/claude-sonnet-4", help="사용할 LLM 모델")

    args = parser.parse_args()
    extractor = NotionMetadataExtractor(model=args.model)

    try:
        # 설정된 모든 카테고리 가져오기
        available_categories = list(extractor.database_ids.keys())

        if args.category == "all":
            categories = available_categories
        else:
            if args.category not in available_categories:
                print(f"❌ 오류: '{args.category}'는 설정된 카테고리가 아닙니다.")
                print(f"가능한 카테고리: {available_categories}")
                return
            categories = [args.category]

        for category in categories:
            await extractor.extract_category(category, limit=args.limit)

    finally:
        await extractor.close()

if __name__ == "__main__":
    asyncio.run(main())
