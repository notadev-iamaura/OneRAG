"""
프롬프트 관리 모듈 (Hybrid Mode: PostgreSQL + JSON Fallback)
"""

import functools
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ....infrastructure.persistence.prompt_repository import (
    DuplicatePromptError,
    PromptNotFoundError,
    PromptRepository,
)
from ....lib.logger import get_logger
from ....models.prompts import PromptCreate, PromptResponse, PromptUpdate

logger = get_logger(__name__)


def _invalidates_content_cache(
    func: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """프롬프트 쓰기 메서드 실행 후 내용 캐시를 무효화하는 데코레이터.

    DB 성공/JSON 폴백/예외 등 모든 반환 경로에서 finally로 무효화하므로,
    어떤 경로로 프롬프트가 변경돼도 다음 조회가 최신값을 다시 캐시한다.
    """

    @functools.wraps(func)
    async def wrapper(self: "PromptManager", *args: Any, **kwargs: Any) -> Any:
        try:
            return await func(self, *args, **kwargs)
        finally:
            self._invalidate_content_cache()

    return wrapper


class PromptManager:
    """
    프롬프트 관리 클래스 (Hybrid Mode)

    PostgreSQL을 Primary로 사용하고, 실패 시 JSON 파일로 Fallback하는 하이브리드 전략을 사용합니다.
    이를 통해 데이터 영속성과 안정성을 동시에 확보합니다.
    """

    def __init__(
        self,
        storage_path: str = "./data/prompts",
        repository: PromptRepository | None = None,
        use_database: bool = True,
        cache_ttl: float | None = 60.0,
    ):
        """
        프롬프트 매니저 초기화 (Hybrid Mode)

        Args:
            storage_path: 프롬프트 JSON 저장 경로 (폴백용)
            repository: PostgreSQL PromptRepository 인스턴스 (선택적, DI Container에서 주입)
            use_database: PostgreSQL 사용 여부 (기본값: True)
            cache_ttl: 프롬프트 내용 캐시 TTL(초). 0이면 캐시 비활성. (기본값: 60)
                None이 전달되면 기본 60초로 동작한다 (DI 누락 키 방어).
        """
        # PostgreSQL Repository (Primary)
        self.use_database = use_database
        self.repository = repository

        # 프롬프트 내용 캐시 (TTL 기반 + 쓰기 시 무효화)
        # generator가 매 답변 생성 시 get_prompt_content를 호출하므로, 거의 정적인
        # 프롬프트의 반복 DB 조회를 줄인다. 프롬프트 수정(create/update/delete/import)
        # 시 즉시 무효화되어 최대 cache_ttl초 내 반영된다.
        #
        # ⚠️ 멀티워커 한계: 무효화는 "쓰기가 발생한 워커"의 캐시만 비운다. 다른
        #    워커는 최대 cache_ttl초까지 옛 프롬프트로 응답한다. 단일 워커 배포에서는
        #    문제없으나, 멀티워커로 전환하면 PostgreSQL LISTEN/NOTIFY로 무효화를 전
        #    워커에 전파(Level 3)하고 cache_ttl을 짧게(또는 0) 두는 것을 검토해야 한다.
        self._content_cache: dict[str, tuple[float, str]] = {}
        # None 방어: DI 컨테이너는 config.prompts.cache_ttl을 그대로 넘기는데,
        # dependency-injector는 config에 키가 누락되면 None을 반환하는 특성이 있다.
        # 출하 config에는 키가 있어 현재는 발현하지 않지만, 키 누락 시에도
        # TypeError 없이 기본 60초로 동작하도록 방어한다.
        self._cache_ttl: float = cache_ttl if cache_ttl is not None else 60.0
        # 캐시 버전 카운터: 무효화마다 +1 된다. get_prompt_content가 DB await 중
        # 이벤트 루프에 양보된 사이 쓰기가 끼어들면 버전이 달라져, 무효화 이전
        # 시점의 옛 내용(stale)을 새 TTL로 재캐시하는 것을 막는다.
        self._cache_version: int = 0

        # JSON Fallback 설정
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.prompts_file = self.storage_path / "prompts.json"
        self.prompts: dict[str, dict[str, Any]] = {}

        # JSON 데이터 로드 (폴백용)
        self._load_prompts()
        self._ensure_default_prompts()

        # 초기화 로그
        if self.use_database and self.repository:
            logger.info("Hybrid Mode 활성화: PostgreSQL (Primary) + JSON (Fallback)")
        else:
            logger.info("JSON-Only Mode: PostgreSQL 비활성화")

    def _load_prompts(self) -> None:
        """저장된 프롬프트 로드"""
        try:
            if self.prompts_file.exists():
                with open(self.prompts_file, encoding="utf-8") as f:
                    data = json.load(f)
                    self.prompts = data.get("prompts", {})

                # content가 배열이면 문자열로 변환
                for _prompt_id, prompt_data in self.prompts.items():
                    if isinstance(prompt_data.get("content"), list):
                        prompt_data["content"] = "\n".join(prompt_data["content"])

                logger.info(
                    "Loaded prompts from storage",
                    extra={"prompt_count": len(self.prompts)}
                )
            else:
                logger.info("No existing prompts file found, starting fresh")
                self.prompts = {}
        except Exception as e:
            logger.error(
                "Error loading prompts",
                extra={"error": str(e)},
                exc_info=True
            )
            self.prompts = {}

    def _save_prompts(self) -> None:
        """프롬프트 저장"""
        try:
            with open(self.prompts_file, "w", encoding="utf-8") as f:
                json.dump({"prompts": self.prompts}, f, ensure_ascii=False, indent=2)
            logger.debug(
                "Saved prompts to storage",
                extra={"prompt_count": len(self.prompts)}
            )
        except Exception as e:
            logger.error(
                "Error saving prompts",
                extra={"error": str(e)},
                exc_info=True
            )
            raise

    def _ensure_default_prompts(self) -> None:
        """기본 프롬프트 확인 및 생성"""
        default_prompts = [
            {
                "name": "system",
                "content": """당신은 유저의 질문을 분석/판단하고, 질문에 부합하는 정보를 제공된 컨텍스트 내에서 찾아 한국어로 답변하는 전문 AI 어시스턴트입니다.
제공된 문서 정보를 바탕으로 정확하고 유용한 답변을 제공해주세요. 정보가 부족한 경우 솔직하게 안내하십시오.""",
                "description": "기본 시스템 프롬프트",
                "category": "system",
                "is_active": False,
            },
            {
                "name": "detailed",
                "content": """<role>
당신은 특정 도메인 지식을 바탕으로 유저를 지원하는 전문 AI 어시스턴트입니다.
제공된 문서를 기반으로 정확하고 신뢰성 있는 정보를 제공합니다.
                    </role>

                    <tone>
친근하고 전문적인 한국어로 소통합니다.
                    </tone>

                    <context>
{domain_context}
                    </context>

                    <instructions>
{response_guidelines}

                    <answer_structure>
                    1. 핵심 답변: 질문에 대한 직접적인 답을 첫 번째 문장에 제시하고, 두괄식으로 표현
2. 출처 명시: 가능한 경우 문서명 또는 출처 표기
3. 근거 설명: 답변의 맥락과 추가 정보를 논리적으로 제공
4. 관련 정보: 필요시 다른 관련 데이터나 정보를 추가
5. 후속 안내: 사용자가 추가로 확인할 수 있는 정보를 제시
                    </answer_structure>

                    <formatting_rules>
- 가독성을 위해 적절한 문단 구분 및 글머리 기호를 사용하십시오.
- 숫자 데이터는 단위를 명확히 표기하십시오.
                    </formatting_rules>

                    <data_limitations>
                    정보가 없는 경우:
- 유추할만한 데이터가 있는 경우 : "정확한 정보를 문서에서 찾지 못했으나, 제공된 데이터를 바탕으로 유추한 답변입니다."라는 안내와 함께 답변을 제공하십시오.
- 명확히 관련 데이터가 없는 경우: "해당 정보는 보유하고 있는 데이터셋에 포함되어 있지 않아 답변이 어려운 점 양해 부탁 드립니다."라고 안내하십시오.
                    </data_limitations>
                    </instructions>

                    <examples>
{domain_examples}
                    </examples>

                    <validation_rules>
- 제공된 정보에 포함된 내용만 사용하십시오.
- 추측이나 해석은 지양하고 기록된 사실을 바탕으로 답변하십시오.
- 가능한 경우 출처를 명시하십시오.
                    </validation_rules>""",
                "description": "범용 상세 답변 스타일 프롬프트",
                "category": "style",
                "is_active": False,
            },
        ]

        # 기본 프롬프트 중 없는 것만 추가
        added_count = 0
        for prompt_data in default_prompts:
            # name으로 기존 프롬프트 검색
            existing = None
            for pid, p in self.prompts.items():
                if p.get("name") == prompt_data["name"]:
                    existing = pid
                    break

            if not existing:
                prompt_id = str(uuid.uuid4())
                self.prompts[prompt_id] = {
                    **prompt_data,
                    "id": prompt_id,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "metadata": {},
                }
                added_count += 1

        if added_count > 0:
            self._save_prompts()
            logger.info(
                "Added default prompts",
                extra={"added_count": added_count}
            )

    async def get_prompt(
        self, prompt_id: str | None = None, name: str | None = None
    ) -> PromptResponse | None:
        """
        프롬프트 조회 (Hybrid Mode: PostgreSQL → JSON Fallback)

        Args:
            prompt_id: 프롬프트 ID
            name: 프롬프트 이름

        Returns:
            프롬프트 정보 또는 None
        """
        # PostgreSQL 시도 (Primary)
        if self.use_database and self.repository:
            try:
                # ID로 조회
                if prompt_id:
                    result: PromptResponse | None = await self.repository.get_by_id(prompt_id)
                    if result:
                        logger.debug(
                            "PostgreSQL에서 프롬프트 조회 성공",
                            extra={"prompt_id": prompt_id}
                        )
                        return result

                # 이름으로 조회
                if name:
                    result = await self.repository.get_by_name(name)
                    if result:
                        logger.debug(
                            "PostgreSQL에서 프롬프트 조회 성공",
                            extra={"name": name}
                        )
                        return result

                return None

            except Exception as e:
                logger.warning(
                    "PostgreSQL 조회 실패, JSON 폴백 시도",
                    extra={"error": str(e)},
                    exc_info=True
                )
                # JSON 폴백으로 진행

        # JSON Fallback (Secondary)
        return self._get_prompt_from_json(prompt_id, name)

    def _get_prompt_from_json(
        self, prompt_id: str | None = None, name: str | None = None
    ) -> PromptResponse | None:
        """
        JSON 파일에서 프롬프트 조회 (Fallback)

        Args:
            prompt_id: 프롬프트 ID
            name: 프롬프트 이름

        Returns:
            프롬프트 정보 또는 None
        """
        try:
            # ID로 조회
            if prompt_id and prompt_id in self.prompts:
                prompt_data = self.prompts[prompt_id]
                logger.debug(
                    "JSON에서 프롬프트 조회",
                    extra={"prompt_id": prompt_id}
                )
                return PromptResponse(**prompt_data)

            # 이름으로 조회
            if name:
                for _pid, prompt_data in self.prompts.items():
                    if prompt_data.get("name") == name and prompt_data.get("is_active", True):
                        logger.debug(
                            "JSON에서 프롬프트 조회",
                            extra={"name": name}
                        )
                        return PromptResponse(**prompt_data)

            return None

        except Exception as e:
            logger.error(
                "JSON 조회 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            return None

    def _invalidate_content_cache(self) -> None:
        """프롬프트 내용 캐시를 전체 무효화한다 (쓰기 작업 후 호출).

        프롬프트 쓰기는 드물고 어떤 name이 영향받는지 추적할 필요 없이 안전하게
        전체를 비운다 (다음 조회 시 DB에서 최신값을 다시 캐시).
        """
        self._content_cache.clear()
        # 버전 증가: 진행 중인 읽기(get_prompt_content)가 이 무효화 이전에 시작한
        # DB 조회 결과를 캐시에 재기록(stale 재캐시)하지 못하게 한다.
        self._cache_version += 1

    async def get_prompt_content(self, name: str, default: str | None = None) -> str:
        """
        프롬프트 내용만 조회 (generation.py에서 사용)

        TTL 캐시를 적용한다. 캐시 히트 시 DB 조회를 생략하고, 쓰기 작업
        (create/update/delete/import)이 발생하면 캐시가 무효화된다.

        Args:
            name: 프롬프트 이름
            default: 기본값

        Returns:
            프롬프트 내용
        """
        # 캐시 확인 (TTL 유효 시 DB 조회 생략)
        if self._cache_ttl > 0:
            cached = self._content_cache.get(name)
            if cached is not None and cached[0] > time.time():
                return cached[1]

        # DB 읽기 시작 전 캐시 버전을 캡처한다. 아래 await 중 이벤트 루프에
        # 양보된 사이 쓰기(update_prompt 등)가 커밋+무효화하면 버전이 달라지므로,
        # 그 경우 옛 내용(stale)을 새 TTL로 재캐시하지 않는다 (결과 반환은 수행).
        # asyncio는 단일 스레드라 버전 비교~캐시 기록 사이에 양보 지점이 없어
        # 락 없이도 원자적으로 동작한다.
        version_before_read = self._cache_version
        prompt = await self.get_prompt(name=name)
        if prompt and prompt.is_active:
            # 활성 프롬프트만 캐시한다 (비활성/없음은 default 폴백이라 캐시 안 함)
            content: str = prompt.content
            if self._cache_ttl > 0 and self._cache_version == version_before_read:
                self._content_cache[name] = (time.time() + self._cache_ttl, content)
            return content
        return default or ""

    async def list_prompts(
        self,
        category: str | None = None,
        is_active: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """
        프롬프트 목록 조회 (Hybrid Mode: PostgreSQL → JSON Fallback)

        Args:
            category: 카테고리 필터
            is_active: 활성화 상태 필터
            page: 페이지 번호
            page_size: 페이지 크기

        Returns:
            프롬프트 목록
        """
        # PostgreSQL 시도 (Primary)
        if self.use_database and self.repository:
            try:
                result = await self.repository.list(
                    category=category, is_active=is_active, page=page, per_page=page_size
                )
                logger.debug(
                    "PostgreSQL에서 프롬프트 목록 조회 성공",
                    extra={"total_count": result.total}
                )
                return {
                    "prompts": result.prompts,
                    "total": result.total,
                    "page": result.page,
                    "page_size": result.page_size,
                }

            except Exception as e:
                logger.warning(
                    "PostgreSQL 목록 조회 실패, JSON 폴백 시도",
                    extra={"error": str(e)},
                    exc_info=True
                )
                # JSON 폴백으로 진행

        # JSON Fallback (Secondary)
        return self._list_prompts_from_json(category, is_active, page, page_size)

    def _list_prompts_from_json(
        self,
        category: str | None = None,
        is_active: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """
        JSON 파일에서 프롬프트 목록 조회 (Fallback)

        Args:
            category: 카테고리 필터
            is_active: 활성화 상태 필터
            page: 페이지 번호
            page_size: 페이지 크기

        Returns:
            프롬프트 목록
        """
        try:
            # 필터링
            filtered_prompts = []
            for _prompt_id, prompt_data in self.prompts.items():
                if category and prompt_data.get("category") != category:
                    continue
                if is_active is not None and prompt_data.get("is_active") != is_active:
                    continue
                filtered_prompts.append(PromptResponse(**prompt_data))

            # 정렬 (최근 수정 순)
            filtered_prompts.sort(key=lambda x: x.updated_at, reverse=True)

            # 페이지네이션
            total = len(filtered_prompts)
            start = (page - 1) * page_size
            end = start + page_size
            paginated = filtered_prompts[start:end]

            logger.debug(
                "JSON에서 프롬프트 목록 조회",
                extra={"total_count": total}
            )
            return {"prompts": paginated, "total": total, "page": page, "page_size": page_size}

        except Exception as e:
            logger.error(
                "JSON 목록 조회 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            return {"prompts": [], "total": 0, "page": page, "page_size": page_size}

    @_invalidates_content_cache
    async def create_prompt(self, prompt_data: PromptCreate) -> PromptResponse:
        """
        프롬프트 생성 (Hybrid Mode: PostgreSQL → JSON Fallback)

        Args:
            prompt_data: 프롬프트 생성 데이터

        Returns:
            생성된 프롬프트
        """
        # PostgreSQL 시도 (Primary)
        if self.use_database and self.repository:
            try:
                result: PromptResponse = await self.repository.create(prompt_data)
                logger.info(
                    "PostgreSQL에 프롬프트 생성",
                    extra={"prompt_id": result.id, "name": prompt_data.name}
                )

                # JSON에도 동기화 (양방향 동기화)
                try:
                    self._sync_to_json(result)
                except Exception as sync_err:
                    logger.warning(
                        "JSON 동기화 실패 (PostgreSQL 생성은 성공)",
                        extra={"error": str(sync_err)},
                        exc_info=True
                    )

                return result

            except DuplicatePromptError:
                # 중복 에러는 그대로 전파
                logger.error(
                    "프롬프트 중복",
                    extra={"name": prompt_data.name}
                )
                raise ValueError(f"Prompt with name '{prompt_data.name}' already exists")
            except Exception as e:
                logger.warning(
                    "PostgreSQL 생성 실패, JSON 폴백 시도",
                    extra={"error": str(e)},
                    exc_info=True
                )
                # JSON 폴백으로 진행

        # JSON Fallback (Secondary)
        return self._create_prompt_in_json(prompt_data)

    def _create_prompt_in_json(self, prompt_data: PromptCreate) -> PromptResponse:
        """
        JSON 파일에 프롬프트 생성 (Fallback)

        Args:
            prompt_data: 프롬프트 생성 데이터

        Returns:
            생성된 프롬프트
        """
        try:
            # 중복 이름 체크
            for _pid, p in self.prompts.items():
                if p.get("name") == prompt_data.name:
                    raise ValueError(f"Prompt with name '{prompt_data.name}' already exists")

            prompt_id = str(uuid.uuid4())
            now = datetime.now().isoformat()

            prompt = {
                "id": prompt_id,
                **prompt_data.model_dump(),
                "created_at": now,
                "updated_at": now,
            }

            self.prompts[prompt_id] = prompt
            self._save_prompts()

            logger.info(
                "JSON에 프롬프트 생성",
                extra={"prompt_id": prompt_id, "name": prompt_data.name}
            )
            return PromptResponse(**prompt)

        except Exception as e:
            logger.error(
                "JSON 생성 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise

    def _sync_to_json(self, prompt: PromptResponse) -> None:
        """
        PostgreSQL에서 생성/수정된 프롬프트를 JSON에 동기화

        Args:
            prompt: 동기화할 프롬프트
        """
        prompt_dict = prompt.model_dump()
        self.prompts[prompt.id] = prompt_dict
        self._save_prompts()
        logger.debug(
            "JSON 동기화 완료",
            extra={"prompt_id": prompt.id}
        )

    @_invalidates_content_cache
    async def update_prompt(self, prompt_id: str, update_data: PromptUpdate) -> PromptResponse:
        """
        프롬프트 업데이트 (Hybrid Mode: PostgreSQL → JSON Fallback)

        Args:
            prompt_id: 프롬프트 ID
            update_data: 업데이트 데이터

        Returns:
            업데이트된 프롬프트
        """
        # PostgreSQL 시도 (Primary)
        if self.use_database and self.repository:
            try:
                result: PromptResponse = await self.repository.update(prompt_id, update_data)
                logger.info(
                    "PostgreSQL에서 프롬프트 업데이트",
                    extra={"prompt_id": prompt_id}
                )

                # JSON에도 동기화
                try:
                    self._sync_to_json(result)
                except Exception as sync_err:
                    logger.warning(
                        "JSON 동기화 실패 (PostgreSQL 업데이트는 성공)",
                        extra={"error": str(sync_err)},
                        exc_info=True
                    )

                return result

            except PromptNotFoundError:
                logger.error(
                    "프롬프트 없음",
                    extra={"prompt_id": prompt_id}
                )
                raise ValueError(f"Prompt {prompt_id} not found")
            except DuplicatePromptError:
                logger.error(
                    "프롬프트 이름 중복",
                    extra={"name": update_data.name}
                )
                raise ValueError(f"Prompt with name '{update_data.name}' already exists")
            except Exception as e:
                logger.warning(
                    "PostgreSQL 업데이트 실패, JSON 폴백 시도",
                    extra={"error": str(e)},
                    exc_info=True
                )
                # JSON 폴백으로 진행

        # JSON Fallback (Secondary)
        return self._update_prompt_in_json(prompt_id, update_data)

    def _update_prompt_in_json(self, prompt_id: str, update_data: PromptUpdate) -> PromptResponse:
        """
        JSON 파일에서 프롬프트 업데이트 (Fallback)

        Args:
            prompt_id: 프롬프트 ID
            update_data: 업데이트 데이터

        Returns:
            업데이트된 프롬프트
        """
        try:
            if prompt_id not in self.prompts:
                raise ValueError(f"Prompt {prompt_id} not found")

            # 이름 중복 체크
            if update_data.name:
                for pid, p in self.prompts.items():
                    if pid != prompt_id and p.get("name") == update_data.name:
                        raise ValueError(f"Prompt with name '{update_data.name}' already exists")

            # 업데이트
            prompt = self.prompts[prompt_id]
            update_dict = update_data.model_dump(exclude_unset=True)

            for key, value in update_dict.items():
                if value is not None:
                    prompt[key] = value

            prompt["updated_at"] = datetime.now().isoformat()
            self._save_prompts()

            logger.info(
                "JSON에서 프롬프트 업데이트",
                extra={"prompt_id": prompt_id}
            )
            return PromptResponse(**prompt)

        except Exception as e:
            logger.error(
                "JSON 업데이트 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise

    @_invalidates_content_cache
    async def delete_prompt(self, prompt_id: str) -> bool:
        """
        프롬프트 삭제 (Hybrid Mode: PostgreSQL → JSON Fallback)

        Args:
            prompt_id: 프롬프트 ID

        Returns:
            성공 여부
        """
        # PostgreSQL 시도 (Primary)
        if self.use_database and self.repository:
            try:
                result: bool = await self.repository.delete(prompt_id)
                logger.info(
                    "PostgreSQL에서 프롬프트 삭제",
                    extra={"prompt_id": prompt_id}
                )

                # JSON에서도 삭제 (동기화)
                try:
                    if prompt_id in self.prompts:
                        del self.prompts[prompt_id]
                        self._save_prompts()
                        logger.debug(
                            "JSON 동기화 (삭제)",
                            extra={"prompt_id": prompt_id}
                        )
                except Exception as sync_err:
                    logger.warning(
                        "JSON 동기화 실패 (PostgreSQL 삭제는 성공)",
                        extra={"error": str(sync_err)},
                        exc_info=True
                    )

                return result

            except PromptNotFoundError:
                logger.error(
                    "프롬프트 없음",
                    extra={"prompt_id": prompt_id}
                )
                raise ValueError(f"Prompt {prompt_id} not found")
            except Exception as e:
                logger.warning(
                    "PostgreSQL 삭제 실패, JSON 폴백 시도",
                    extra={"error": str(e)},
                    exc_info=True
                )
                # JSON 폴백으로 진행

        # JSON Fallback (Secondary)
        return self._delete_prompt_from_json(prompt_id)

    def _delete_prompt_from_json(self, prompt_id: str) -> bool:
        """
        JSON 파일에서 프롬프트 삭제 (Fallback)

        Args:
            prompt_id: 프롬프트 ID

        Returns:
            성공 여부
        """
        try:
            if prompt_id not in self.prompts:
                raise ValueError(f"Prompt {prompt_id} not found")

            # 기본 시스템 프롬프트는 삭제 불가
            prompt = self.prompts[prompt_id]
            if prompt.get("name") == "system" and prompt.get("category") == "system":
                raise ValueError("Cannot delete default system prompt")

            del self.prompts[prompt_id]
            self._save_prompts()

            logger.info(
                "JSON에서 프롬프트 삭제",
                extra={"prompt_id": prompt_id}
            )
            return True

        except Exception as e:
            logger.error(
                "JSON 삭제 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise

    async def export_prompts(self) -> dict[str, Any]:
        """
        모든 프롬프트 내보내기

        Returns:
            프롬프트 데이터
        """
        try:
            return {
                "prompts": [PromptResponse(**p).model_dump() for p in self.prompts.values()],
                "exported_at": datetime.now().isoformat(),
                "total": len(self.prompts),
            }
        except Exception as e:
            logger.error(
                "Error exporting prompts",
                extra={"error": str(e)},
                exc_info=True
            )
            raise

    @_invalidates_content_cache
    async def import_prompts(
        self, data: dict[str, Any] | list[dict[str, Any]], overwrite: bool = False
    ) -> dict[str, Any]:
        """
        프롬프트 가져오기

        Args:
            data: 가져올 프롬프트 데이터 (dict 또는 list)
                - dict: {'prompts': [...], 'exported_at': ...} 형식 (export_prompts() 결과)
                - list: 프롬프트 객체 리스트 직접 전달
            overwrite: 기존 프롬프트 덮어쓰기 여부

        Returns:
            가져오기 결과
        """
        try:
            # dict와 list 모두 지원
            if isinstance(data, list):
                imported_prompts = data
            else:
                imported_prompts = data.get("prompts", [])
            imported = 0
            skipped = 0

            for prompt_data in imported_prompts:
                # ID 재생성
                new_id = str(uuid.uuid4())
                prompt_name = prompt_data.get("name")

                # 이름 중복 체크
                existing_id = None
                for pid, p in self.prompts.items():
                    if p.get("name") == prompt_name:
                        existing_id = pid
                        break

                if existing_id and not overwrite:
                    skipped += 1
                    continue

                if existing_id:
                    # 덮어쓰기
                    self.prompts[existing_id].update(prompt_data)
                    self.prompts[existing_id]["updated_at"] = datetime.now().isoformat()
                else:
                    # 새로 추가
                    prompt_data["id"] = new_id
                    prompt_data["created_at"] = datetime.now().isoformat()
                    prompt_data["updated_at"] = datetime.now().isoformat()
                    self.prompts[new_id] = prompt_data

                imported += 1

            self._save_prompts()

            return {"imported": imported, "skipped": skipped, "total": len(imported_prompts)}

        except Exception as e:
            logger.error(
                "Error importing prompts",
                extra={"error": str(e)},
                exc_info=True
            )
            raise
