"""채팅 메시지 영속화 저장소(ChatStore) 추상 인터페이스.

세션(MemoryService)이 구체적인 영속화 백엔드(PostgreSQL 등)에 직접 의존하지 않도록
구조적 타입(Protocol)으로 추상화합니다. 이를 통해:

- 기본(0-dependency): chat_store 미주입 → 인메모리만 사용(추가 인프라 불필요).
- 선택(Postgres): config opt-in 시 `PostgresChatStore`를 주입 → 영속/복원 활성화.
- 테스트: Fake/Mock 구현체를 손쉽게 교체 가능.

설계 원칙(반드시 준수):
- 영속화 실패는 채팅 응답을 절대 실패시키지 않는다(graceful). 구현체는 내부에서
  예외를 흡수하고(로깅 후) no-op/빈 결과를 반환한다.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChatStore(Protocol):
    """채팅 메시지 영속화 백엔드의 최소 인터페이스.

    `MemoryService`가 사용하는 메서드만 노출합니다. 모든 메서드는 graceful 하게
    동작해야 하며(예외 전파 금지), 백엔드 미연결 시 저장은 no-op, 조회는 빈 결과를
    반환합니다.
    """

    async def save_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        user_metadata: dict[str, Any] | None = None,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> None:
        """user/assistant 교환 1쌍을 단일 트랜잭션으로 원자적으로 저장한다."""
        ...

    async def get_session_messages(
        self,
        session_id: str,
        limit: int | None = None,
        company_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """세션의 메시지를 시간순으로 복원한다. 백엔드 미연결/실패 시 빈 리스트."""
        ...
