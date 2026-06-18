"""
Memory Service - LangChain 메모리 관리 및 대화 컨텍스트
Phase 4.3: enhanced_session.py에서 추출한 검증된 메모리 관리 로직
⚠️ 주의: 이 코드는 기존 검증된 로직을 재사용합니다.
"""

import asyncio
import re
import time
from collections import defaultdict
from datetime import UTC
from typing import Any

from cachetools import TTLCache
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage

from .....lib.langfuse_client import observe, record_generation
from .....lib.logger import get_logger
from .....lib.mongodb_client import MongoDBClient

logger = get_logger(__name__)


# ============================================================================
# 사용자 정보(이름/나이) 추출 패턴 — 코드 내장 기본값(한국어)
# ============================================================================
# 이 패턴들은 세션 메시지에서 사용자 이름/나이를 추출해 컨텍스트(LLM 프롬프트)에
# 반영하므로 동작 영향 경로다. session.yaml user_info_extraction로 외부화하되,
# 미설정 시 아래 기본값을 사용해 기존 동작과 동치(회귀 0)를 보장한다.

# 부분 문자열(substring) 기반 이름 추출 패턴. 메시지에 패턴이 포함되면 그 뒤 첫 단어를
# 이름 후보로 본다.
DEFAULT_NAME_PATTERNS: list[str] = [
    "내 이름은 ",
    "저는 ",
    "제 이름은 ",
    "나는 ",
    "이름이 ",
    " 입니다",
    "이라고 합니다",
    "라고 불러주세요",
]

# 정규식 기반 이름 추출 패턴(부분 문자열 매칭보다 우선). 첫 캡처 그룹이 이름이어야 한다.
DEFAULT_NAME_REGEX: str = r"저는\s+([가-힣]+)\s*입니다"

# 이름 후보 끝에서 제거할 조사/어미 문자 집합(str.rstrip 인자). 예: "철수입니다" → "철수".
DEFAULT_NAME_SUFFIX_STRIP_CHARS: str = "이야입니다요."

# 나이 추출 트리거 단위. 메시지에 이 문자열과 숫자가 함께 있을 때만 나이 정규식을 적용한다.
DEFAULT_AGE_UNIT: str = "살"

# 나이 추출 정규식. 첫 캡처 그룹이 숫자(나이)여야 한다.
DEFAULT_AGE_REGEX: str = r"(\d+)\s*살"

# facts 딕셔너리에 저장할 때 사용하는 라벨(언어 종속). 컨텍스트 출력에는 user_info를
# 통해 노출되며, facts는 내부 사실 저장소다. 라벨도 외부화해 비한국어 운영을 지원한다.
DEFAULT_AGE_FACT_LABEL: str = "나이"
DEFAULT_NAME_FACT_LABEL: str = "이름"


# ============================================================================
# 대화 요약 LLM 프롬프트 — 코드 내장 기본값(한국어)
# ============================================================================
# _summarize_conversations가 오래된 대화를 LLM으로 요약할 때 사용하는 프롬프트다.
# 이 요약 결과는 컨텍스트(LLM 프롬프트)의 [이전 대화 요약] 블록으로 삽입되므로
# 동작 영향 경로다. session.yaml conversation_summary.summary_prompt_template로
# 외부화하되, 미설정 시 아래 한국어 기본값을 사용해 회귀 0을 보장한다.
# {full_text} 플레이스홀더는 대화 본문이 들어가는 자리이므로 반드시 보존해야 한다.
DEFAULT_SUMMARY_PROMPT_TEMPLATE: str = """아래 대화 내용을 2-3문장으로 간결하게 요약해주세요.
핵심 주제와 사용자가 궁금해했던 내용을 중심으로 요약합니다.

대화 내용:
{full_text}

요약:"""


# ============================================================================
# 세션 컨텍스트 라벨 — 코드 내장 기본값(한국어)
# ============================================================================
# get_context_string이 조립하는 세션 컨텍스트 문자열은 RAG 파이프라인의
# {session_context} 플레이스홀더로 LLM에 삽입되므로 cosmetic이 아닌 동작 영향
# 경로다. 라벨이 한국어 전용으로 하드코딩되어 있던 것을 외부화한다. session.yaml의
# session.context_labels 하위 키로 주입하며, 미설정 시 아래 한국어 기본값을 사용해
# 기존 출력과 byte 단위로 동치(회귀 0)를 보장한다.
DEFAULT_USER_NAME_LABEL: str = "사용자 이름"
DEFAULT_USER_INFO_LABEL_PREFIX: str = "사용자"
DEFAULT_TOPICS_LABEL: str = "대화 주제"
DEFAULT_SUMMARY_HEADER: str = "[이전 대화 요약]"
DEFAULT_RECENT_HEADER: str = "[최근 대화 내역]"
DEFAULT_RECENT_HEADER_FULL: str = "최근 대화 내역:"
DEFAULT_USER_TURN_LABEL: str = "사용자"
DEFAULT_AI_TURN_LABEL: str = "AI"
DEFAULT_FACTS_HEADER: str = "기억된 정보:"


class MemoryService:
    """
    LangChain 메모리 및 대화 컨텍스트 관리 서비스

    역할:
    - LangChain InMemoryChatMessageHistory 관리
    - 대화 추가 및 컨텍스트 문자열 생성
    - Window 로직 (max_exchanges 유지)
    - 사용자 정보 추출

    기존 코드 기반: enhanced_session.py의 메모리 및 대화 관리 메서드들
    """

    def __init__(
        self,
        max_exchanges: int | None = None,
        config: dict[str, Any] | None = None,
        mongodb_client: MongoDBClient | None = None,
        chat_store: Any | None = None,
    ):
        """
        Args:
            max_exchanges: 최대 교환 수 (1교환 = 사용자 메시지 + AI 메시지)
                           None일 경우 기본값 10 사용
            config: 전체 설정 딕셔너리 (요약 기능 설정 포함)
            mongodb_client: MongoDB 클라이언트 (DI)
            chat_store: 채팅 메시지 영속화 스토어 (선택적 백엔드, DI).
                        `ChatStore` Protocol(save_exchange/get_session_messages)을
                        만족하는 구현체이며, None이면 기본(인메모리)만 사용합니다.
                        주입되어도 백엔드 미연결 시 graceful 하게 영속화를 건너뜁니다.
                        0-dependency 기본 보존을 위해 미설정이 기본입니다.
        """
        self.max_exchanges = max_exchanges if max_exchanges is not None else 10
        self.config = config or {}
        self.mongodb_client = mongodb_client
        # 채팅 히스토리 영속화 스토어 (선택적 PostgreSQL 백엔드). None이면 인메모리만 사용.
        self.chat_store = chat_store

        # LangChain 메모리 저장소 (enhanced_session.py L35)
        self.memories: dict[str, InMemoryChatMessageHistory] = {}

        # 🔒 세션별 Lock 딕셔너리 (Race Condition 방지)
        # 각 세션은 독립적인 Lock을 가지므로 다른 세션끼리는 병렬 처리 가능
        self.session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        # 요약 설정 로드
        session_config = self.config.get("session", {})
        summary_config = session_config.get("conversation_summary", {})

        self.summary_enabled = summary_config.get("enabled", False)
        self.summary_trigger_count = summary_config.get("trigger_count", 10)
        self.summary_llm_provider = summary_config.get("llm_provider", "google")
        self.summary_llm_model = summary_config.get("llm_model", "gemini-2.0-flash-lite")

        # 대화 요약 LLM 프롬프트 외부화 (session.yaml conversation_summary.summary_prompt_template).
        # 미설정/공백/비문자열이면 코드 내장 한국어 기본값을 사용한다(회귀 0).
        # {full_text} 플레이스홀더를 반드시 포함해야 대화 본문이 주입되므로,
        # 플레이스홀더가 없는 비정상 값은 무효로 보아 기본값으로 폴백한다.
        self.summary_prompt_template: str = self._resolve_summary_prompt_template(
            summary_config.get("summary_prompt_template")
        )

        # 요약 캐시 (TTLCache: 최대 100개 세션, TTL 1시간)
        cache_ttl = summary_config.get("cache_ttl", 3600)
        self.summary_cache: TTLCache = TTLCache(maxsize=100, ttl=cache_ttl)

        # 사용자 정보(이름/나이) 추출 패턴 외부화 (session.yaml user_info_extraction).
        # 이 추출 결과(user_name/user_info)는 컨텍스트 문자열에 포함되어 LLM 프롬프트로
        # 전달되므로 cosmetic이 아닌 동작 영향 경로다. 따라서 기본값=현 한국어 패턴으로
        # 회귀 0을 보장하고, 운영자가 영어/타 언어 패턴을 코드 포크 없이 주입할 수 있게 한다.
        # 미설정/비정상 값이면 아래 코드 내장 한국어 기본값을 사용한다.
        self._load_user_info_extraction_config(session_config)

        # 세션 컨텍스트 라벨 외부화 (session.yaml session.context_labels).
        # get_context_string이 조립하는 라벨은 {session_context}로 LLM에 삽입되므로
        # 동작 영향 경로다. user_info_extraction과 동일한 패턴으로 외부화하며,
        # 미설정 시 코드 내장 한국어 기본값을 사용한다(회귀 0).
        self._load_context_labels_config(session_config)

        logger.info(
            f"MemoryService 초기화: max_exchanges={max_exchanges}, "
            f"LangChain 0.3+ InMemoryChatMessageHistory 사용, "
            f"Session-level locks 활성화 (Race Condition 보호), "
            f"대화 요약 기능={'활성화' if self.summary_enabled else '비활성화'} "
            f"(trigger={self.summary_trigger_count}개)"
        )

    def create_memory(self, session_id: str) -> InMemoryChatMessageHistory:
        """
        새 메모리 생성
        기존 코드: enhanced_session.py의 create_session() 내 메모리 생성 (L102)

        Args:
            session_id: 세션 ID

        Returns:
            InMemoryChatMessageHistory 인스턴스
        """
        chat_history = InMemoryChatMessageHistory()
        self.memories[session_id] = chat_history
        logger.debug(f"메모리 생성: {session_id}")
        return chat_history

    def get_memory(self, session_id: str) -> InMemoryChatMessageHistory | None:
        """
        메모리 조회

        Args:
            session_id: 세션 ID

        Returns:
            InMemoryChatMessageHistory 또는 None
        """
        return self.memories.get(session_id)

    def delete_memory(self, session_id: str):
        """
        메모리 삭제

        Args:
            session_id: 세션 ID
        """
        if session_id in self.memories:
            del self.memories[session_id]
            logger.debug(f"메모리 삭제: {session_id}")

    async def add_conversation(
        self,
        session_id: str,
        session: dict[str, Any],
        user_message: str,
        assistant_response: str,
        metadata: dict[str, Any] | None = None,
    ):
        """
        대화 추가 with Window trimming + Race Condition 보호 + MongoDB 영구 저장

        기존 코드: enhanced_session.py의 add_conversation() 일부 (L200-213)
        개선 사항:
        - Session-level Lock으로 동시 메시지 추가 시 Race Condition 방지
        - MongoDB에 대화 내용 영구 저장 (Feature Flag 제어)

        ⚠️ Race Condition 시나리오:
        - 같은 세션에서 사용자가 빠르게 두 번 메시지 전송
        - 두 요청이 동시에 chat_history.messages 리스트를 수정
        - 결과: 메시지 순서 꼬임, 메시지 누락, 윈도우 트리밍 오류

        ✅ Lock 전략:
        - 세션별 Lock (다른 세션은 병렬 처리 가능)
        - Lock은 빠른 작업만 보호 (0.001초 미만)
        - LLM 호출(3초+)은 Lock 밖에서 완료됨
        - MongoDB 저장(0.01~0.02초)도 Lock 밖에서 비동기 실행

        Args:
            session_id: 세션 ID
            session: 세션 데이터 (사용자 정보 업데이트용)
            user_message: 사용자 메시지
            assistant_response: AI 응답
        """
        chat_history = self.memories.get(session_id)

        if not chat_history:
            raise ValueError(f"Chat history not found for session: {session_id}")

        # 사용자 정보 추출 (L198) - Lock 밖 (빠른 작업)
        await self._extract_user_info(session, user_message)

        # 🔒 메시지 추가, 윈도우 트리밍, MongoDB 저장 (Lock으로 보호)
        # 같은 세션의 동시 요청은 여기서 순차 처리됨
        # MongoDB 저장도 Lock 안에서 수행하여 메모리-DB 불일치 방지
        async with self.session_locks[session_id]:
            # LangChain 0.3+ 방식: 메시지 추가 (L200-202)
            chat_history.add_user_message(user_message)
            chat_history.add_ai_message(assistant_response)
            messages_metadata = session.setdefault("messages_metadata", [])
            # ✅ #8 수정: 교환과 messages_metadata를 항상 1:1로 유지한다.
            # metadata가 없는 턴(facade가 None 전달)도 최소 placeholder(timestamp 포함)를
            # 추가해 get_chat_history의 offset 매핑이 영구적으로 어긋나지 않게 한다.
            entry = metadata if metadata is not None else {"timestamp": time.time()}
            messages_metadata.append(entry)

            # Window 로직: 최대 교환 수 유지 (L204-213)
            max_messages = self.max_exchanges * 2
            current_messages = chat_history.messages

            if len(current_messages) > max_messages:
                messages_to_remove = len(current_messages) - max_messages
                chat_history.messages = current_messages[messages_to_remove:]
                # ✅ #13 수정: messages_metadata도 동일 윈도우(교환 단위)로 trim하여
                # 무한 증가를 막고 messages와의 1:1 정렬을 유지한다.
                exchanges_to_remove = messages_to_remove // 2
                if exchanges_to_remove > 0:
                    del messages_metadata[:exchanges_to_remove]
                logger.debug(
                    f"Window trimming: {messages_to_remove}개 오래된 메시지 제거, "
                    f"현재 {len(chat_history.messages)}개 유지 "
                    f"(metadata {len(messages_metadata)}개 동기 trim)"
                )

            # 💾 MongoDB 영구 저장 (Lock 안에서 트랜잭션처럼 실행)
            # 메시지 메타데이터는 session의 messages_metadata 배열에 저장됨
            try:
                await self._save_message_to_mongodb(
                    session_id=session_id,
                    user_message=user_message,
                    assistant_response=assistant_response,
                    metadata=messages_metadata[-1] if messages_metadata else {},
                )
            except Exception as e:
                # MongoDB 저장 실패 시 메모리도 롤백
                logger.error(f"MongoDB 저장 실패, 메모리 롤백: {e}", exc_info=True)
                # 마지막 2개 메시지(user + assistant) 제거
                if len(chat_history.messages) >= 2:
                    chat_history.messages = chat_history.messages[:-2]
                # 방금 추가한 metadata entry를 롤백(메시지 2개 제거와 1:1 정합 유지)
                if messages_metadata and messages_metadata[-1] is entry:
                    messages_metadata.pop()
                raise  # 에러를 상위로 전파하여 클라이언트에게 실패 알림

        # 💾 채팅 영속화 스토어(PostgreSQL 등) 저장 (Lock 밖, graceful)
        # DB 저장/연결 실패는 채팅 응답을 절대 실패시키지 않습니다. 인메모리는 위에서
        # 이미 보존되었으므로, 여기서는 예외를 흡수(로깅)하여 영속화 실패가 채팅으로
        # 전파되지 않도록 합니다. user/assistant는 단일 트랜잭션으로 원자 저장됩니다.
        await self._save_exchange_to_chat_store(
            session_id=session_id,
            user_message=user_message,
            assistant_response=assistant_response,
            metadata=entry,
        )

    async def _save_exchange_to_chat_store(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        metadata: dict[str, Any],
    ) -> None:
        """채팅 영속화 스토어(chat_store)에 user/assistant 교환을 저장 (graceful).

        chat_store가 주입되지 않았거나(기본/인메모리) 백엔드 미연결이면 조용히
        건너뜁니다. 저장 실패는 어떤 경우에도 채팅에 영향을 주지 않습니다(예외 전파 금지).

        Args:
            session_id: 세션 ID
            user_message: 사용자 메시지
            assistant_response: AI 응답
            metadata: 이번 교환 메타데이터 (sources/tokens_used/company_id 등)
        """
        if self.chat_store is None:
            # chat_store 미주입(0-dependency 기본 경로): 영속화 생략
            return

        # company_id는 멀티테넌트 확장 대비로 두 메시지 모두에 보존(단일테넌트는 None).
        company_id = metadata.get("company_id")
        try:
            await self.chat_store.save_exchange(
                session_id=session_id,
                user_message=user_message,
                assistant_response=assistant_response,
                user_metadata={
                    "message_id": metadata.get("message_id"),
                    "company_id": company_id,
                },
                assistant_metadata={
                    "message_id": metadata.get("message_id"),
                    "company_id": company_id,
                    "tokens_used": metadata.get("tokens_used", 0),
                    "processing_time": metadata.get("processing_time", 0.0),
                    "sources": metadata.get("sources", []),
                    "topic": metadata.get("topic"),
                    "model_info": metadata.get("model_info"),
                },
            )
        except Exception as e:  # noqa: BLE001 - 채팅을 절대 실패시키지 않음
            logger.warning(
                f"채팅 메시지 영속화 실패 (graceful, 인메모리 유지): {e}",
                exc_info=True,
            )

    async def get_context_string(self, session_id: str, session: dict[str, Any]) -> str:
        """
        세션 컨텍스트 문자열 반환 (요약 기능 포함)
        기존 코드: enhanced_session.py의 get_context_string() (L244-287)
        신규: 대화가 많을 경우 오래된 대화를 요약하여 토큰 효율 개선

        Args:
            session_id: 세션 ID
            session: 세션 데이터

        Returns:
            컨텍스트 문자열
        """
        chat_history = self.memories.get(session_id)

        if not chat_history:
            return ""

        context_parts = []

        # 사용자 정보 추가 (L258-264). 라벨은 context_labels로 외부화(미설정 시 한국어 기본).
        if session.get("user_name"):
            context_parts.append(f"{self.user_name_label}: {session['user_name']}")

        if session.get("user_info"):
            for key, value in session["user_info"].items():
                context_parts.append(f"{self.user_info_label_prefix} {key}: {value}")

        # 대화 주제들 (L266-268)
        if session.get("topics"):
            context_parts.append(f"{self.topics_label}: {', '.join(session['topics'])}")

        # 메시지 가져오기 (L270-279)
        messages = chat_history.messages
        message_count = len(messages) // 2  # 교환 수 (사용자 + AI = 1교환)

        # 🆕 요약 로직 (옵션B 구현)
        if self.summary_enabled and message_count > self.summary_trigger_count:
            logger.debug(
                f"요약 모드 활성화: session_id={session_id}, "
                f"대화 수={message_count}, trigger={self.summary_trigger_count}"
            )

            # 캐시 키: session_id + 대화 개수
            cache_key = f"{session_id}_{message_count}"

            # 캐시 확인
            summary = self.summary_cache.get(cache_key)

            if summary:
                logger.debug(f"요약 캐시 히트: {cache_key}")
            else:
                logger.debug(f"요약 캐시 미스, LLM 요약 생성 중: {cache_key}")

                # 최근 5개 제외한 나머지를 요약
                max_recent = self.max_exchanges  # 기본 5개
                old_messages = messages[: -max_recent * 2] if len(messages) > max_recent * 2 else []

                if old_messages:
                    try:
                        summary = await self._summarize_conversations(old_messages)
                        self.summary_cache[cache_key] = summary
                        logger.info(f"✅ 요약 생성 완료: {summary[:100]}...")
                    except Exception as e:
                        logger.error(f"요약 생성 실패, 폴백: {e}")
                        summary = None

            # 요약 추가
            if summary:
                context_parts.append(f"\n{self.summary_header}\n{summary}")

            # 최근 대화만 추가
            recent_messages = (
                messages[-max_recent * 2 :] if len(messages) > max_recent * 2 else messages
            )
            if recent_messages:
                context_parts.append(f"\n{self.recent_header}")
                for message in recent_messages:
                    if isinstance(message, HumanMessage):
                        context_parts.append(f"{self.user_turn_label}: {message.content}")
                    elif isinstance(message, AIMessage):
                        context_parts.append(f"{self.ai_turn_label}: {message.content}")
        else:
            # 기존 방식: 모든 대화 표시
            if messages:
                context_parts.append(f"\n{self.recent_header_full}")
                for message in messages:
                    if isinstance(message, HumanMessage):
                        context_parts.append(f"{self.user_turn_label}: {message.content}")
                    elif isinstance(message, AIMessage):
                        context_parts.append(f"{self.ai_turn_label}: {message.content}")

        # 중요 사실들 (L281-285)
        if session.get("facts"):
            context_parts.append(f"\n{self.facts_header}")
            for key, value in session["facts"].items():
                context_parts.append(f"- {key}: {value}")

        return "\n".join(context_parts)

    async def get_chat_history(
        self,
        session_id: str,
        session: dict[str, Any],
        company_id: str | None = None,
    ) -> dict[str, Any]:
        """
        채팅 히스토리 반환 (메타데이터 포함)
        기존 코드: enhanced_session.py의 get_chat_history() (L289-350)

        영속화 스토어(chat_store)가 주입된 경우, PG의 전체 기록을 권위 소스로 사용해
        세션 소멸(서버 재시작/TTL 만료) 후에도 대화 내역을 복원합니다. PG가 비었거나
        미연결이면 인메모리 경로로 폴백하여 기존 동작을 그대로 유지합니다.

        Args:
            session_id: 세션 ID
            session: 세션 데이터
            company_id: 회사 범위 필터 (멀티테넌트 확장용, 기본 None = 필터 없음)

        Returns:
            {'messages': list, 'message_count': int}
        """
        # [완전·정합 보장] chat_store(PG)가 있으면 PG의 전체 기록을 우선한다.
        # 인메모리 버퍼는 LLM 컨텍스트용 window로 trim되므로, 긴 대화방의 "전체 복원"과
        # 행별 메타데이터 정합은 PG가 더 정확하다. PG 미연결/빈 경우에만 인메모리로 폴백.
        if self.chat_store is not None:
            restored = await self._restore_chat_history_from_postgres(
                session_id, company_id=company_id
            )
            if restored.get("messages"):
                return restored

        chat_history = self.memories.get(session_id)

        # 인메모리 미스 + PG 미사용/빈 경우: 세션 소멸 시 PG 복원 시도(없으면 빈 결과)
        if not chat_history:
            return await self._restore_chat_history_from_postgres(
                session_id, company_id=company_id
            )

        messages = []
        chat_messages = chat_history.messages
        messages_metadata = session.get("messages_metadata", [])
        metadata_offset = max(0, len(messages_metadata) - (len(chat_messages) // 2))

        # LangChain 메시지와 메타데이터 매칭 (L312-345)
        message_index = 0
        for i in range(0, len(chat_messages), 2):
            # 사용자 메시지
            if i < len(chat_messages):
                user_msg = chat_messages[i]
                if isinstance(user_msg, HumanMessage):
                    from datetime import datetime

                    messages.append(
                        {
                            "type": "user",
                            "content": user_msg.content,
                            "timestamp": (
                                datetime.fromtimestamp(
                                    messages_metadata[message_index + metadata_offset][
                                        "timestamp"
                                    ]
                                ).isoformat()
                                if message_index + metadata_offset < len(messages_metadata)
                                else datetime.now().isoformat()
                            ),
                        }
                    )

            # 어시스턴트 메시지
            if i + 1 < len(chat_messages):
                ai_msg = chat_messages[i + 1]
                if isinstance(ai_msg, AIMessage):
                    from datetime import datetime

                    msg_data = {
                        "type": "assistant",
                        "content": ai_msg.content,
                        "timestamp": (
                            datetime.fromtimestamp(
                                messages_metadata[message_index + metadata_offset]["timestamp"]
                            ).isoformat()
                            if message_index + metadata_offset < len(messages_metadata)
                            else datetime.now().isoformat()
                        ),
                    }

                    # 메타데이터 추가
                    if message_index + metadata_offset < len(messages_metadata):
                        metadata = messages_metadata[message_index + metadata_offset]
                        msg_data.update(
                            {
                                "tokens_used": metadata.get("tokens_used", 0),
                                "processing_time": metadata.get("processing_time", 0.0),
                                "model_info": metadata.get("model_info"),
                            }
                        )

                    messages.append(msg_data)
                    message_index += 1

        return {"messages": messages, "message_count": len(messages)}

    async def _restore_chat_history_from_postgres(
        self, session_id: str, company_id: str | None = None
    ) -> dict[str, Any]:
        """인메모리 미스 시 영속화 스토어(PostgreSQL)에서 채팅 히스토리를 복원합니다 (graceful).

        chat_store가 없거나 백엔드 미연결/조회 실패면 빈 결과를 반환합니다.
        반환 스키마는 인메모리 경로(get_chat_history)와 동일하게 맞춥니다.
        message_count는 user/assistant 각각을 1건으로 세므로 Q/A 1쌍 = 2 입니다.

        Args:
            session_id: 세션 ID
            company_id: 회사 범위 필터 (멀티테넌트 확장용, 기본 None = 필터 없음)

        Returns:
            {'messages': list, 'message_count': int}
        """
        if self.chat_store is None:
            return {"messages": [], "message_count": 0}

        # chat_store는 graceful 하므로 실패 시 빈 리스트를 반환합니다.
        stored = await self.chat_store.get_session_messages(
            session_id, company_id=company_id
        )
        if not stored:
            return {"messages": [], "message_count": 0}

        messages: list[dict[str, Any]] = []
        for record in stored:
            role = record.get("role")
            metadata = record.get("metadata") or {}
            timestamp = record.get("created_at")

            if role == "user":
                messages.append(
                    {
                        "type": "user",
                        "content": record.get("content", ""),
                        "timestamp": timestamp,
                    }
                )
            elif role == "assistant":
                messages.append(
                    {
                        "type": "assistant",
                        "content": record.get("content", ""),
                        "timestamp": timestamp,
                        "tokens_used": metadata.get("tokens_used", 0),
                        "processing_time": metadata.get("processing_time", 0.0),
                        "model_info": metadata.get("model_info"),
                        # 복원 시 sources 보존 (인용 근거 유지, 인메모리 경로와 스키마 일치)
                        "sources": metadata.get("sources", []),
                    }
                )

        logger.info(
            f"영속화 스토어에서 채팅 히스토리 복원: session_id={session_id}, "
            f"messages={len(messages)}"
        )
        return {"messages": messages, "message_count": len(messages)}

    def _load_user_info_extraction_config(
        self, session_config: dict[str, Any]
    ) -> None:
        """사용자 정보 추출 패턴을 config 우선으로 로드한다(미설정 시 코드 기본 → 회귀 0).

        session.yaml의 session.user_info_extraction 하위 키를 읽어 인스턴스 속성으로
        저장한다. 각 항목은 미설정/타입 불일치/공백이면 코드 내장 한국어 기본값을 쓴다.

        Args:
            session_config: self.config["session"] 딕셔너리.
        """
        extraction_config = session_config.get("user_info_extraction", {})
        if not isinstance(extraction_config, dict):
            extraction_config = {}

        # 부분 문자열 이름 패턴 리스트: 문자열 리스트일 때만 채택(아니면 기본값).
        configured_name_patterns = extraction_config.get("name_patterns")
        if isinstance(configured_name_patterns, list) and all(
            isinstance(p, str) for p in configured_name_patterns
        ):
            self.name_patterns: list[str] = configured_name_patterns
        else:
            self.name_patterns = list(DEFAULT_NAME_PATTERNS)

        # 정규식/단위/라벨류: 비어 있지 않은 문자열일 때만 채택.
        self.name_regex: str = self._resolve_str_config(
            extraction_config.get("name_regex"), DEFAULT_NAME_REGEX
        )
        self.name_suffix_strip_chars: str = self._resolve_str_config(
            extraction_config.get("name_suffix_strip_chars"),
            DEFAULT_NAME_SUFFIX_STRIP_CHARS,
        )
        self.name_fact_label: str = self._resolve_str_config(
            extraction_config.get("name_fact_label"), DEFAULT_NAME_FACT_LABEL
        )
        self.age_unit: str = self._resolve_str_config(
            extraction_config.get("age_unit"), DEFAULT_AGE_UNIT
        )
        self.age_regex: str = self._resolve_str_config(
            extraction_config.get("age_regex"), DEFAULT_AGE_REGEX
        )
        self.age_fact_label: str = self._resolve_str_config(
            extraction_config.get("age_fact_label"), DEFAULT_AGE_FACT_LABEL
        )

    @staticmethod
    def _resolve_str_config(configured: Any, default: str) -> str:
        """문자열 config 값을 해소한다(비문자열/공백이면 default → 회귀 0).

        Args:
            configured: config에서 읽은 원시 값.
            default: 코드 내장 기본 문자열.

        Returns:
            유효한 문자열(앞뒤 공백만 있는 값은 무효로 보아 default 사용).
        """
        if isinstance(configured, str) and configured.strip():
            return configured
        return default

    @staticmethod
    def _resolve_summary_prompt_template(configured: Any) -> str:
        """요약 프롬프트 템플릿을 해소한다(미설정/플레이스홀더 누락 시 기본값 → 회귀 0).

        요약 프롬프트는 반드시 {full_text} 플레이스홀더를 포함해야 대화 본문이
        주입된다. 비문자열/공백이거나 플레이스홀더가 없는 값은 무효로 보아 코드 내장
        한국어 기본값을 사용한다.

        Args:
            configured: config에서 읽은 원시 값.

        Returns:
            유효한 프롬프트 템플릿({full_text} 포함 보장).
        """
        if (
            isinstance(configured, str)
            and configured.strip()
            and "{full_text}" in configured
        ):
            return configured
        return DEFAULT_SUMMARY_PROMPT_TEMPLATE

    def _load_context_labels_config(self, session_config: dict[str, Any]) -> None:
        """세션 컨텍스트 라벨을 config 우선으로 로드한다(미설정 시 코드 기본 → 회귀 0).

        session.yaml의 session.context_labels 하위 키를 읽어 인스턴스 속성으로 저장한다.
        각 항목은 미설정/타입 불일치/공백이면 코드 내장 한국어 기본값을 쓴다.
        이 라벨들은 get_context_string이 조립하는 컨텍스트 문자열에 사용되며, 해당
        문자열은 {session_context}로 LLM에 삽입되므로 동작 영향 경로다.

        Args:
            session_config: self.config["session"] 딕셔너리.
        """
        labels_config = session_config.get("context_labels", {})
        if not isinstance(labels_config, dict):
            labels_config = {}

        # 사용자 이름 라벨. 예: "사용자 이름: 철수"의 "사용자 이름".
        self.user_name_label: str = self._resolve_str_config(
            labels_config.get("user_name_label"), DEFAULT_USER_NAME_LABEL
        )
        # user_info 항목 라벨 접두. 예: "사용자 나이: 30"의 "사용자".
        self.user_info_label_prefix: str = self._resolve_str_config(
            labels_config.get("user_info_label_prefix"), DEFAULT_USER_INFO_LABEL_PREFIX
        )
        # 대화 주제 라벨. 예: "대화 주제: a, b"의 "대화 주제".
        self.topics_label: str = self._resolve_str_config(
            labels_config.get("topics_label"), DEFAULT_TOPICS_LABEL
        )
        # 요약 모드의 [이전 대화 요약] 헤더.
        self.summary_header: str = self._resolve_str_config(
            labels_config.get("summary_header"), DEFAULT_SUMMARY_HEADER
        )
        # 요약 모드의 [최근 대화 내역] 헤더(대괄호 형태).
        self.recent_header: str = self._resolve_str_config(
            labels_config.get("recent_header"), DEFAULT_RECENT_HEADER
        )
        # 비요약(기본) 모드의 "최근 대화 내역:" 헤더(콜론 형태).
        self.recent_header_full: str = self._resolve_str_config(
            labels_config.get("recent_header_full"), DEFAULT_RECENT_HEADER_FULL
        )
        # 사용자 발화 라벨. 예: "사용자: 안녕"의 "사용자".
        self.user_turn_label: str = self._resolve_str_config(
            labels_config.get("user_turn_label"), DEFAULT_USER_TURN_LABEL
        )
        # AI 발화 라벨. 예: "AI: 안녕하세요"의 "AI".
        self.ai_turn_label: str = self._resolve_str_config(
            labels_config.get("ai_turn_label"), DEFAULT_AI_TURN_LABEL
        )
        # 중요 사실 블록의 "기억된 정보:" 헤더.
        self.facts_header: str = self._resolve_str_config(
            labels_config.get("facts_header"), DEFAULT_FACTS_HEADER
        )

    async def _extract_user_info(self, session: dict[str, Any], message: str):
        """
        메시지에서 사용자 정보 추출
        기존 코드: enhanced_session.py의 _extract_user_info() (L411-459)

        패턴은 session.yaml user_info_extraction로 외부화되며, 미설정 시 코드 내장
        한국어 기본값을 사용한다(회귀 0). 추출 결과는 컨텍스트(LLM 프롬프트)에 반영된다.

        Args:
            session: 세션 데이터
            message: 사용자 메시지
        """
        # 정규식 방식 (부분 문자열보다 우선)
        name_match = re.search(self.name_regex, message)
        if name_match:
            name_candidate = name_match.group(1).strip()
            if name_candidate and 1 < len(name_candidate) < 10:
                session["user_name"] = name_candidate
                session["facts"][self.name_fact_label] = name_candidate
                logger.info(f"이름 추출 (정규식): {name_candidate}")
                return

        # 부분 문자열 패턴 방식
        for pattern in self.name_patterns:
            if pattern in message:
                parts = message.split(pattern)
                if len(parts) > 1:
                    name_candidate = (
                        parts[1].split()[0].rstrip(self.name_suffix_strip_chars).strip()
                    )
                    if name_candidate and 1 < len(name_candidate) < 10:
                        session["user_name"] = name_candidate
                        session["facts"][self.name_fact_label] = name_candidate
                        logger.info(f"이름 추출 (패턴 매칭): {name_candidate}")
                        break

        # 나이 추출 (단위 문자열 + 숫자 동시 존재 시에만 정규식 적용)
        if self.age_unit in message and any(char.isdigit() for char in message):
            age_match = re.search(self.age_regex, message)
            if age_match:
                age = int(age_match.group(1))
                if 1 < age < 120:  # 합리적인 나이 범위
                    session["user_info"][self.age_fact_label] = age
                    session["facts"][self.age_fact_label] = f"{age}{self.age_unit}"

    async def _save_message_to_mongodb(
        self, session_id: str, user_message: str, assistant_response: str, metadata: dict
    ):
        """
        MongoDB에 대화 내용 영구 저장 (Feature Flag 제어)

        실패해도 기존 기능에 영향 없음 (Fail-Safe 설계)

        Args:
            session_id: 세션 ID
            user_message: 사용자 메시지
            assistant_response: AI 응답
            metadata: 메시지 메타데이터 (tokens_used, processing_time, sources 등)
        """
        try:
            # Feature Flag 확인 (app/config/features/session.yaml)
            from app.lib.config_loader import load_config

            config = load_config()
            session_config = config.get("session", {})

            if not session_config.get("save_chat_to_mongodb", False):
                # Feature Flag OFF: 저장하지 않음
                return

            # MongoDB 클라이언트 확인 (DI)
            if not self.mongodb_client:
                logger.warning("MongoDB client not available (not injected via DI)")
                return

            from datetime import datetime

            collection = self.mongodb_client.get_chat_history_collection()

            if not collection:
                logger.warning("MongoDB chat_history collection not available")
                return

            # 문서 구조 생성
            message_doc = {
                "session_id": session_id,
                "message_id": metadata.get("message_id", f"msg_{datetime.now().timestamp()}"),
                "timestamp": datetime.now(UTC),
                # 대화 내용
                "user_message": user_message,
                "ai_response": assistant_response,
                # 메타데이터
                "metadata": {
                    "tokens_used": metadata.get("tokens_used", 0),
                    "processing_time": metadata.get("processing_time", 0.0),
                    "sources": metadata.get("sources", []),
                    "topic": metadata.get("topic", "general"),
                    "model_info": metadata.get("model_info", {}),
                    "can_evaluate": metadata.get("can_evaluate", False),
                    "has_temp_document": metadata.get("has_temp_document", False),
                    "temp_doc_filename": metadata.get("temp_doc_filename"),
                },
                # 추가 타임스탬프
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }

            # 재시도 로직
            retry_count = session_config.get("mongodb_save_retry", 3)
            timeout = session_config.get("mongodb_save_timeout", 1.0)

            for attempt in range(retry_count):
                try:
                    # MongoDB 저장 (타임아웃 적용)
                    import asyncio

                    await asyncio.wait_for(
                        asyncio.to_thread(collection.insert_one, message_doc), timeout=timeout
                    )

                    logger.debug(
                        f"💾 채팅 히스토리 MongoDB 저장 성공: "
                        f"session_id={session_id}, "
                        f"message_id={message_doc['message_id']}"
                    )
                    return

                except TimeoutError:
                    if attempt < retry_count - 1:
                        logger.warning(
                            f"MongoDB 저장 타임아웃 (재시도 {attempt + 1}/{retry_count}): "
                            f"session_id={session_id}"
                        )
                        await asyncio.sleep(0.1 * (attempt + 1))  # 지수 백오프
                    else:
                        logger.error(f"MongoDB 저장 최종 실패 (타임아웃): session_id={session_id}")

                except Exception as e:
                    # 중복 키 에러는 무시 (이미 저장됨)
                    if "duplicate key" in str(e).lower():
                        logger.debug(
                            f"MongoDB 중복 메시지 (이미 저장됨): "
                            f"message_id={message_doc['message_id']}"
                        )
                        return

                    if attempt < retry_count - 1:
                        logger.warning(
                            f"MongoDB 저장 오류 (재시도 {attempt + 1}/{retry_count}): {e}"
                        )
                        await asyncio.sleep(0.1 * (attempt + 1))
                    else:
                        raise

        except Exception as e:
            # DB 저장 실패해도 채팅은 계속 작동 (Fail-Safe)
            logger.error(f"MongoDB 채팅 히스토리 저장 실패: {e}", exc_info=True)
            # ❌ raise 하지 않음 → 채팅 중단 없음

    @observe(
        as_type="generation",
        name="Conversation Summary",
        capture_input=False,
        capture_output=False,
    )
    async def _summarize_conversations(self, messages: list) -> str:
        """
        대화 목록을 LLM으로 요약

        프롬프트는 session.yaml conversation_summary.summary_prompt_template로 외부화되며,
        미설정 시 코드 내장 한국어 기본값을 사용한다(회귀 0). 요약 결과는 컨텍스트의
        [이전 대화 요약] 블록으로 LLM에 삽입되므로 동작 영향 경로다.

        Args:
            messages: LangChain 메시지 리스트 (HumanMessage, AIMessage)

        Returns:
            요약 문자열 (2-3문장)

        예시:
            Input: [
                HumanMessage("환불은 어떻게 받나요?"),
                AIMessage("주문 내역에서 환불 신청..."),
                HumanMessage("처리 기간은 얼마나 걸리나요?"),
                AIMessage("영업일 기준 3~5일...")
            ]
            Output: "사용자가 환불 신청 방법과 처리 기간을 문의했습니다."
        """
        try:
            # 메시지를 텍스트로 변환. 발화 라벨은 context_labels로 외부화(미설정 시 한국어 기본).
            conversation_text = []
            for msg in messages:
                if isinstance(msg, HumanMessage):
                    conversation_text.append(f"{self.user_turn_label}: {msg.content}")
                elif isinstance(msg, AIMessage):
                    conversation_text.append(f"{self.ai_turn_label}: {msg.content}")

            full_text = "\n".join(conversation_text)

            # 요약 프롬프트(외부화). {full_text} 자리에 대화 본문을 주입한다.
            prompt = self.summary_prompt_template.format(full_text=full_text)

            # LLM 호출 (Gemini)
            import google.generativeai as genai

            model = genai.GenerativeModel(self.summary_llm_model)
            response = await asyncio.to_thread(
                model.generate_content,
                prompt,
                generation_config={
                    "temperature": 0.3,  # 안정적인 요약
                    "max_output_tokens": 200,  # 짧게
                },
            )

            summary = response.text.strip()
            logger.debug(f"대화 요약 생성 성공: {summary[:100]}...")
            # 대화 요약 LLM 호출의 토큰/비용을 Langfuse generation으로 기록한다.
            # genai 네이티브 SDK는 usage_metadata를 속성(prompt_token_count 등)으로 노출한다.
            um = getattr(response, "usage_metadata", None)
            if um is not None:
                record_generation(
                    model=self.summary_llm_model,
                    prompt_tokens=getattr(um, "prompt_token_count", 0) or 0,
                    completion_tokens=getattr(um, "candidates_token_count", 0) or 0,
                    total_tokens=getattr(um, "total_token_count", 0) or 0,
                    model_parameters={"temperature": 0.3, "max_output_tokens": 200},
                )
            return summary

        except Exception as e:
            logger.error(f"대화 요약 생성 실패: {e}", exc_info=True)
            # 폴백: 첫 사용자 메시지만 반환
            for msg in messages:
                if isinstance(msg, HumanMessage):
                    return f"사용자가 '{msg.content[:50]}...'에 대해 문의했습니다."
            return "이전 대화 내용"
