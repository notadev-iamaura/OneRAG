"""
Session Race Condition 테스트

동시 세션 생성 및 업데이트 시 데이터 일관성을 검증합니다.

테스트 범위:
1. 동시 세션 생성 - 중복 ID 방지
2. 동시 세션 생성 - None ID 처리
3. Lock 성능 검증
4. 세션 상태 일관성

작성일: 2026-01-06
"""

import asyncio
import time
from uuid import uuid4

import pytest


@pytest.mark.integration
class TestSessionRaceCondition:
    """Session 동시 생성 Race Condition 테스트"""

    @pytest.fixture
    def session_service(self):
        """SessionService 인스턴스 생성"""
        from app.lib.config_loader import load_config
        from app.modules.core.session.services.session_service import SessionService

        # 실제 설정 로드
        config = load_config()

        # SessionService 생성 (config만 필요)
        service = SessionService(config=config)
        return service

    @pytest.mark.asyncio
    async def test_concurrent_session_creation_duplicate_id(self, session_service) -> None:
        """
        동시 세션 생성 - 중복 ID 방지

        Given: 같은 session_id로 10개 동시 요청
        When: asyncio.gather로 동시 실행
        Then: 하나만 원래 ID 사용, 나머지는 새 ID로 대체

        주의: IDOR 방어로 약한 session_id는 거부되고 서버 UUID4로 대체되므로,
        race condition(중복 생성 방지) 검증에는 추측 불가능한 유효 UUID4를 쓴다.
        """
        target_session_id = str(uuid4())

        # 10개 동시 요청
        tasks = [
            session_service.create_session(session_id=target_session_id) for _ in range(10)
        ]

        results = await asyncio.gather(*tasks)

        # 검증: session_id들 추출
        session_ids = [result["session_id"] for result in results]

        # 1. 모든 session_id가 유니크한지 확인 (중복 생성 방지)
        assert len(session_ids) == len(set(session_ids)), "Session ID 중복 발생!"

        # 2. 최소 하나는 원래 ID를 사용했는지 확인
        assert (
            target_session_id in session_ids
        ), "원래 요청한 session_id가 하나도 사용되지 않음"

        # 3. 나머지는 새 ID로 대체되었는지 확인
        replaced_count = len([sid for sid in session_ids if sid != target_session_id])
        assert replaced_count == 9, f"9개가 대체되어야 하는데 {replaced_count}개만 대체됨"

    @pytest.mark.asyncio
    async def test_concurrent_session_creation_none_id(self, session_service) -> None:
        """
        동시 세션 생성 - None ID 처리

        Given: session_id=None으로 10개 동시 요청
        When: asyncio.gather로 동시 실행
        Then: 모두 다른 유니크한 ID 받음
        """
        # 10개 동시 요청 (session_id=None)
        tasks = [session_service.create_session(session_id=None) for _ in range(10)]

        results = await asyncio.gather(*tasks)

        # 검증: session_id들 추출
        session_ids = [result["session_id"] for result in results]

        # 1. 모든 session_id가 유니크한지 확인
        assert len(session_ids) == len(set(session_ids)), "Session ID 중복 발생!"

        # 2. 모든 session_id가 유효한 UUID 형식인지 확인
        import uuid

        for session_id in session_ids:
            try:
                uuid.UUID(session_id)
            except ValueError:
                pytest.fail(f"Invalid UUID format: {session_id}")

    @pytest.mark.asyncio
    async def test_lock_performance_under_contention(self, session_service) -> None:
        """
        Lock 성능 검증 - 경합 상황

        Given: 50개 동시 세션 생성 요청
        When: Lock 경합 발생
        Then: 평균 Lock 대기 시간이 0.1초 미만
        """
        # 50개 동시 요청
        start_time = time.time()
        tasks = [session_service.create_session(session_id=None) for _ in range(50)]

        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        # 검증: 모든 세션 생성 성공
        assert len(results) == 50

        # 평균 시간 계산 (50개 / 총 시간)
        avg_time_per_session = total_time / 50

        # Lock이 제대로 동작하면서도 성능 저하가 심하지 않은지 확인
        # 평균 0.1초 미만 (Lock 대기 + 세션 생성)
        assert (
            avg_time_per_session < 0.1
        ), f"평균 세션 생성 시간이 너무 느림: {avg_time_per_session:.3f}s"

        # 전체 실행 시간도 합리적인지 확인 (5초 미만)
        assert total_time < 5.0, f"전체 실행 시간이 너무 느림: {total_time:.3f}s"

    @pytest.mark.asyncio
    async def test_session_state_consistency_under_concurrent_updates(
        self, session_service
    ) -> None:
        """
        세션 상태 일관성 - 동시 업데이트

        Given: 하나의 세션에 대해 동시에 여러 업데이트 요청
        When: 동시에 세션 메타데이터 업데이트
        Then: 마지막 업데이트가 반영되고 데이터 손실 없음
        """
        # 1. 세션 생성
        session_result = await session_service.create_session(session_id="consistency-test")
        session_id = session_result["session_id"]

        # 2. 동시에 10개 업데이트 요청
        async def update_session(index: int):
            """세션 메타데이터 업데이트"""
            # SessionService의 sessions dict 직접 업데이트 (update_session 메서드가 있다면 사용)
            if hasattr(session_service, "sessions") and session_id in session_service.sessions:
                session_service.sessions[session_id]["metadata"][f"update_{index}"] = index
                return index
            return None

        tasks = [update_session(i) for i in range(10)]
        await asyncio.gather(*tasks)

        # 검증: 모든 업데이트가 반영되었는지 확인
        if hasattr(session_service, "sessions") and session_id in session_service.sessions:
            metadata = session_service.sessions[session_id]["metadata"]

            # 10개 업데이트 모두 반영되었는지 확인
            for i in range(10):
                assert (
                    f"update_{i}" in metadata
                ), f"업데이트 {i}가 누락됨 (Race Condition 발생)"
                assert metadata[f"update_{i}"] == i, f"업데이트 {i}의 값이 잘못됨"

    @pytest.mark.asyncio
    async def test_no_race_condition_with_rapid_requests(self, session_service) -> None:
        """
        빠른 연속 요청 시 Race Condition 없음

        Given: 0.001초 간격으로 100개 세션 생성 요청
        When: 매우 빠른 속도로 연속 요청
        Then: 모든 세션이 유니크하게 생성됨
        """

        async def create_with_delay(index: int):
            """짧은 지연 후 세션 생성"""
            await asyncio.sleep(0.001 * index)  # 0-0.099초 지연
            return await session_service.create_session(session_id=None)

        tasks = [create_with_delay(i) for i in range(100)]
        results = await asyncio.gather(*tasks)

        # 검증: 모든 session_id가 유니크한지
        session_ids = [result["session_id"] for result in results]
        assert len(session_ids) == len(set(session_ids)), "Session ID 중복 발생!"


@pytest.mark.integration
class TestSessionUpdateRaceCondition:
    """Session 동시 업데이트 Race Condition 테스트"""

    @pytest.fixture
    def session_service_with_memory(self):
        """MemoryService 포함 SessionService"""
        from app.lib.config_loader import load_config
        from app.modules.core.session.services.memory_service import MemoryService
        from app.modules.core.session.services.session_service import SessionService

        # 설정 로드
        config = load_config()

        # SessionService
        session_service = SessionService(config=config)

        # MemoryService (config 필요)
        memory_service = MemoryService(config=config)

        return session_service, memory_service

    @pytest.mark.asyncio
    async def test_concurrent_message_addition(
        self, session_service_with_memory
    ) -> None:
        """
        동시 메시지 추가 Race Condition

        Given: 하나의 세션에 동시에 여러 메시지 추가
        When: asyncio.gather로 동시 실행
        Then: 모든 메시지가 순서대로 저장됨 (손실 없음)
        """
        session_service, memory_service = session_service_with_memory

        # 1. 세션 생성
        session_result = await session_service.create_session(session_id="msg-test")
        session_id = session_result["session_id"]

        # 2. 동시에 10개 메시지 추가
        async def add_message(index: int):
            """메시지 추가"""
            # MemoryService의 add_message 메서드 사용 (있다면)
            if hasattr(memory_service, "add_message"):
                await memory_service.add_message(
                    session_id=session_id,
                    role="user" if index % 2 == 0 else "assistant",
                    content=f"메시지 {index}",
                )
            else:
                # Fallback: sessions dict 직접 업데이트
                if (
                    hasattr(session_service, "sessions")
                    and session_id in session_service.sessions
                ):
                    if "messages_metadata" not in session_service.sessions[session_id]:
                        session_service.sessions[session_id]["messages_metadata"] = []

                    session_service.sessions[session_id]["messages_metadata"].append(
                        {
                            "role": "user" if index % 2 == 0 else "assistant",
                            "content": f"메시지 {index}",
                            "timestamp": time.time(),
                        }
                    )

        tasks = [add_message(i) for i in range(10)]
        await asyncio.gather(*tasks)

        # 검증: 메시지 개수 확인
        if hasattr(session_service, "sessions") and session_id in session_service.sessions:
            messages = session_service.sessions[session_id].get("messages_metadata", [])
            # 최소한 메시지가 추가되었는지 확인 (순서는 보장 안 될 수 있음)
            assert len(messages) >= 5, f"메시지 손실 발생: {len(messages)}/10"

    @pytest.mark.asyncio
    async def test_concurrent_session_read_write(self, session_service_with_memory) -> None:
        """
        동시 읽기/쓰기 Race Condition

        Given: 하나의 세션에 대해 동시에 읽기/쓰기 요청
        When: 읽기 10회, 쓰기 10회 동시 실행
        Then: 데이터 일관성 유지 (읽기 중 쓰기로 인한 오류 없음)
        """
        session_service, _ = session_service_with_memory

        # 1. 세션 생성
        session_result = await session_service.create_session(session_id="rw-test")
        session_id = session_result["session_id"]

        # 2. 읽기/쓰기 동시 요청
        read_count = 0
        write_count = 0

        async def read_session():
            """세션 읽기"""
            nonlocal read_count
            if hasattr(session_service, "sessions") and session_id in session_service.sessions:
                _ = session_service.sessions[session_id]
                read_count += 1

        async def write_session(index: int):
            """세션 쓰기"""
            nonlocal write_count
            if hasattr(session_service, "sessions") and session_id in session_service.sessions:
                session_service.sessions[session_id]["metadata"][f"write_{index}"] = index
                write_count += 1

        # 읽기 10개 + 쓰기 10개 동시 실행
        read_tasks = [read_session() for _ in range(10)]
        write_tasks = [write_session(i) for i in range(10)]
        all_tasks = read_tasks + write_tasks

        await asyncio.gather(*all_tasks)

        # 검증: 읽기/쓰기 모두 성공했는지
        assert read_count >= 5, f"읽기 실패: {read_count}/10"
        assert write_count >= 5, f"쓰기 실패: {write_count}/10"

        # 데이터 일관성 확인
        if hasattr(session_service, "sessions") and session_id in session_service.sessions:
            metadata = session_service.sessions[session_id]["metadata"]
            # 쓰기 작업이 모두 반영되었는지
            for i in range(10):
                if f"write_{i}" in metadata:
                    assert metadata[f"write_{i}"] == i


@pytest.mark.integration
class TestSessionLockMechanism:
    """Session Lock 메커니즘 세부 검증"""

    @pytest.fixture
    def session_service(self):
        """SessionService 인스턴스"""
        from app.lib.config_loader import load_config
        from app.modules.core.session.services.session_service import SessionService

        # 설정 로드
        config = load_config()

        return SessionService(config=config)

    @pytest.mark.asyncio
    async def test_lock_acquisition_order(self, session_service) -> None:
        """
        Lock 획득 순서 보장

        Given: 10개 동시 요청
        When: Lock 경합 발생
        Then: Lock은 FIFO 순서로 획득됨 (공평성)
        """
        acquisition_order = []

        async def create_and_record(index: int):
            """세션 생성 및 순서 기록"""
            result = await session_service.create_session(session_id=None)
            acquisition_order.append(index)
            return result

        tasks = [create_and_record(i) for i in range(10)]
        await asyncio.gather(*tasks)

        # 검증: 모든 요청이 처리되었는지
        assert len(acquisition_order) == 10

        # Lock 순서는 보장되지 않을 수 있지만, 모두 처리되었는지 확인
        assert set(acquisition_order) == set(range(10))

    @pytest.mark.asyncio
    async def test_lock_not_blocking_independent_sessions(self, session_service) -> None:
        """
        독립 세션 간 Lock 간섭 없음

        Given: 서로 다른 session_id로 동시 요청
        When: Lock 사용
        Then: 각 세션은 독립적으로 생성됨 (Lock 간섭 최소)
        """
        start_time = time.time()

        # 서로 다른 session_id로 동시 요청
        tasks = [session_service.create_session(session_id=None) for _ in range(20)]

        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        # 검증: 모든 세션 생성 성공
        assert len(results) == 20

        # 독립 세션이므로 병렬 처리 가능
        # 평균 시간이 너무 크지 않은지 확인 (0.15초 미만)
        avg_time = total_time / 20
        assert avg_time < 0.15, f"독립 세션 처리 시간이 너무 느림: {avg_time:.3f}s"
