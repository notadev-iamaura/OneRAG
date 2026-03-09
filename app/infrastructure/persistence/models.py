"""
SQLAlchemy 데이터베이스 모델 정의

평가 시스템을 위한 PostgreSQL 테이블 스키마
"""

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.sql import func

from .connection import Base


class EvaluationModel(Base):
    """평가 데이터 모델"""

    __tablename__ = "evaluations"

    # Primary Key
    evaluation_id = Column(
        String,
        primary_key=True,
        default=lambda: f"eval_{uuid.uuid4().hex[:12]}",
        comment="평가 고유 ID",
    )

    # Foreign Keys (인덱스 추가)
    session_id = Column(String, nullable=False, index=True, comment="채팅 세션 ID")
    message_id = Column(String, nullable=False, unique=True, index=True, comment="메시지 고유 ID")

    # 평가 점수 필드 (1-5점)
    query_score = Column(Integer, nullable=True, comment="쿼리 품질 점수")
    response_score = Column(Integer, nullable=True, comment="응답 품질 점수")
    overall_score = Column(
        Integer, nullable=True, index=True, comment="전체 평가 점수"  # 검색 성능을 위한 인덱스
    )

    # 세부 평가 점수 (선택적)
    relevance_score = Column(Integer, nullable=True, comment="관련성 점수")
    accuracy_score = Column(Integer, nullable=True, comment="정확성 점수")
    completeness_score = Column(Integer, nullable=True, comment="완성도 점수")
    clarity_score = Column(Integer, nullable=True, comment="명확성 점수")

    # 피드백 및 메타데이터
    feedback = Column(Text, nullable=True, comment="사용자 피드백 텍스트")
    evaluator_id = Column(String, nullable=True, index=True, comment="평가자 ID")
    evaluation_type = Column(
        String, nullable=True, default="manual", comment="평가 유형 (manual, automatic)"
    )

    # 쿼리 및 응답 내용 저장
    query_text = Column(Text, nullable=True, comment="원본 쿼리 텍스트")
    response_text = Column(Text, nullable=True, comment="원본 응답 텍스트")

    # 추가 메타데이터 (JSON 필드)
    extra_metadata = Column(
        JSON, nullable=True, comment="추가 메타데이터 (응답 시간, 모델 정보 등)"
    )

    # 타임스탬프
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="생성 시간",
    )
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True, comment="수정 시간"
    )

    # 복합 인덱스 (성능 최적화)
    __table_args__ = (
        # 세션별 평가 조회 최적화
        Index("idx_session_created", "session_id", "created_at"),
        # 날짜 범위 + 점수 필터링 최적화
        Index("idx_score_date", "overall_score", "created_at"),
        # 평가자별 조회 최적화
        Index("idx_evaluator_created", "evaluator_id", "created_at"),
        # 피드백이 있는 평가 조회 최적화
        Index("idx_feedback_created", "created_at", postgresql_where=(feedback is not None)),
    )

    def to_dict(self) -> dict:
        """모델을 딕셔너리로 변환"""
        return {
            "evaluation_id": self.evaluation_id,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "query_score": self.query_score,
            "response_score": self.response_score,
            "overall_score": self.overall_score,
            "relevance_score": self.relevance_score,
            "accuracy_score": self.accuracy_score,
            "completeness_score": self.completeness_score,
            "clarity_score": self.clarity_score,
            "feedback": self.feedback,
            "evaluator_id": self.evaluator_id,
            "evaluation_type": self.evaluation_type,
            "query_text": self.query_text,
            "response_text": self.response_text,
            "metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def calculate_average_score(self) -> float | None:
        """평균 점수 계산"""
        scores = [
            self.query_score,
            self.response_score,
            self.overall_score,
            self.relevance_score,
            self.accuracy_score,
            self.completeness_score,
            self.clarity_score,
        ]

        valid_scores: list[float] = [float(s) for s in scores if s is not None]

        if not valid_scores:
            return None

        return sum(valid_scores) / len(valid_scores)

    def __repr__(self) -> str:
        return f"<Evaluation(id={self.evaluation_id}, session={self.session_id}, score={self.overall_score})>"


class EvaluationStatisticsCache(Base):
    """통계 캐시 테이블 (선택적)"""

    __tablename__ = "evaluation_statistics_cache"

    cache_id = Column(String, primary_key=True, default=lambda: f"cache_{uuid.uuid4().hex[:12]}")
    cache_key = Column(String, unique=True, nullable=False, comment="캐시 키")
    statistics_data = Column(JSON, nullable=False, comment="통계 데이터 JSON")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, comment="만료 시간")

    # 만료된 캐시 자동 정리를 위한 인덱스
    __table_args__ = (Index("idx_cache_expires", "expires_at"),)


class ChatSessionModel(Base):
    """채팅 세션 정보 저장 (IP 지역 포함)"""

    __tablename__ = "chat_sessions"

    # Primary Key
    session_id = Column(String, primary_key=True, comment="세션 고유 ID")

    # IP 정보 (해시만 저장)
    ip_hash = Column(
        String(64), nullable=False, index=True, comment="IP 주소 SHA256 해시"  # SHA256 = 64자
    )

    # 지역 정보 (GeoJS 결과)
    country = Column(String, nullable=True, index=True, comment="국가명 (예: South Korea)")
    country_code = Column(
        String(2), nullable=True, index=True, comment="국가 코드 (예: KR)"  # ISO 2자리 코드
    )
    city = Column(String, nullable=True, index=True, comment="도시명 (예: Seoul)")
    region = Column(String, nullable=True, comment="지역/주 (예: Seoul)")
    latitude = Column(Float, nullable=True, comment="위도")
    longitude = Column(Float, nullable=True, comment="경도")
    timezone = Column(String, nullable=True, comment="타임존 (예: Asia/Seoul)")
    is_private_ip = Column(Boolean, default=False, comment="사설 IP 여부")

    # 세션 통계
    message_count = Column(Integer, default=0, comment="메시지 수")
    total_tokens = Column(Integer, default=0, comment="총 토큰 사용량")
    total_processing_time = Column(Float, default=0.0, comment="총 처리 시간 (초)")

    # 사용자 에이전트
    user_agent = Column(String, nullable=True, comment="User-Agent 헤더")

    # 추가 메타데이터
    extra_metadata = Column(JSON, nullable=True, comment="추가 메타데이터 (JSON)")

    # 타임스탬프
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="세션 생성 시간",
    )
    last_accessed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="마지막 접속 시간",
    )

    # 복합 인덱스 (쿼리 최적화)
    __table_args__ = (
        # 국가별 통계 조회 최적화
        Index("idx_country_created", "country", "created_at"),
        # 국가 코드별 조회 최적화
        Index("idx_country_code_created", "country_code", "created_at"),
        # 도시별 조회 최적화
        Index("idx_city_created", "city", "created_at"),
        # IP 해시별 조회 (같은 IP의 세션 찾기)
        Index("idx_ip_hash_created", "ip_hash", "created_at"),
    )

    def to_dict(self) -> dict:
        """모델을 딕셔너리로 변환"""
        return {
            "session_id": self.session_id,
            "ip_hash": self.ip_hash,
            "country": self.country,
            "country_code": self.country_code,
            "city": self.city,
            "region": self.region,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timezone": self.timezone,
            "is_private_ip": self.is_private_ip,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
            "total_processing_time": self.total_processing_time,
            "user_agent": self.user_agent,
            "metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_accessed_at": (
                self.last_accessed_at.isoformat() if self.last_accessed_at else None
            ),
        }

    def __repr__(self) -> str:
        return f"<ChatSession(id={self.session_id}, country={self.country}, messages={self.message_count})>"


class PromptModel(Base):
    """프롬프트 데이터 모델 (PostgreSQL 마이그레이션)"""

    __tablename__ = "prompts"

    # Primary Key (UUID 형식의 문자열)
    id = Column(String, primary_key=True, comment="프롬프트 고유 ID (UUID)")

    # 프롬프트 기본 정보
    name = Column(String, unique=True, nullable=False, index=True, comment="프롬프트 이름 (고유)")
    content = Column(Text, nullable=False, comment="프롬프트 내용")
    description = Column(Text, nullable=True, comment="프롬프트 설명")

    # 분류 및 상태
    category = Column(
        String,
        nullable=False,
        default="system",
        index=True,
        comment="프롬프트 카테고리 (system, style 등)",
    )
    is_active = Column(Boolean, nullable=False, default=True, index=True, comment="활성화 여부")

    # 메타데이터 (JSON 필드로 확장 가능)
    # SQLAlchemy의 metadata 예약어를 피하기 위해 extra_metadata 사용
    extra_metadata = Column(JSON, nullable=True, default={}, comment="추가 메타데이터 (JSON)")

    # 타임스탬프
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="생성 시간",
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="수정 시간",
    )

    # 복합 인덱스 (쿼리 최적화)
    __table_args__ = (
        # 카테고리별 활성 프롬프트 조회 최적화
        Index("idx_category_active", "category", "is_active"),
        # 최근 수정된 프롬프트 조회 최적화
        Index("idx_updated_at", "updated_at"),
    )

    def to_dict(self) -> dict:
        """모델을 딕셔너리로 변환 (JSON 직렬화 가능)"""
        return {
            "id": self.id,
            "name": self.name,
            "content": self.content,
            "description": self.description,
            "category": self.category,
            "is_active": self.is_active,
            "metadata": self.extra_metadata if self.extra_metadata else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<Prompt(id={self.id}, name={self.name}, category={self.category}, active={self.is_active})>"


# ============================================================================
# 배치 크롤링 시스템 모델 (2025-11-19 추가)
# ============================================================================


class BatchRunModel(Base):
    """배치 실행 이력 모델"""

    __tablename__ = "batch_runs"

    # Primary Key
    run_id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="배치 실행 고유 ID (UUID)",
    )

    # 실행 시간
    started_at = Column(
        DateTime(timezone=True), nullable=False, index=True, comment="배치 시작 시간 (UTC)"
    )
    completed_at = Column(DateTime(timezone=True), nullable=True, comment="배치 완료 시간 (UTC)")

    # 실행 결과
    status = Column(
        String(20),
        nullable=False,
        index=True,
        comment="배치 실행 상태: running, success, partial_failure, failure",
    )
    total_duration_seconds = Column(Integer, nullable=True, comment="총 실행 시간 (초)")
    successful_sources = Column(
        Integer, nullable=False, default=0, comment="성공한 소스 개수 (최대 6개)"
    )

    # 타임스탬프
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="레코드 생성 시간",
    )

    # 복합 인덱스
    __table_args__ = (
        Index("idx_batch_runs_started_at", "started_at"),
        Index("idx_batch_runs_status", "status"),
    )

    def to_dict(self) -> dict:
        """모델을 딕셔너리로 변환"""
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "total_duration_seconds": self.total_duration_seconds,
            "successful_sources": self.successful_sources,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<BatchRun(run_id={self.run_id}, status={self.status}, sources={self.successful_sources}/6)>"


class BatchSourceLogModel(Base):
    """배치 소스별 실행 로그 모델"""

    __tablename__ = "batch_source_logs"

    # Primary Key
    log_id = Column(
        String, primary_key=True, default=lambda: str(uuid.uuid4()), comment="로그 고유 ID (UUID)"
    )

    # Foreign Key
    run_id = Column(String, nullable=False, index=True, comment="배치 실행 ID (FK → batch_runs)")

    # 소스 정보
    source_url = Column(Text, nullable=False, index=True, comment="크롤링 소스 URL")
    source_name = Column(
        String(100), nullable=False, index=True, comment="소스명 (예: source_page_1)"
    )

    # 실행 결과
    chunks_created = Column(Integer, nullable=False, default=0, comment="생성된 청크 개수")
    validation_passed = Column(
        Boolean, nullable=False, default=False, comment="청크 개수 validation 통과 여부"
    )

    # HTML 구조 변경 감지
    html_structure_hash = Column(String(64), nullable=True, comment="HTML 구조 해시값 (SHA256)")
    structure_changed = Column(
        Boolean, nullable=False, default=False, index=True, comment="HTML 구조 변경 여부"
    )

    # 에러 정보
    error_message = Column(Text, nullable=True, comment="에러 메시지 (실패 시)")

    # 실행 시간
    duration_seconds = Column(Integer, nullable=True, comment="소스별 실행 시간 (초)")

    # 타임스탬프
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="레코드 생성 시간",
    )

    # 복합 인덱스
    __table_args__ = (
        Index("idx_batch_source_logs_run_id", "run_id"),
        Index("idx_batch_source_logs_source_url", "source_url"),
        Index("idx_batch_source_logs_source_name", "source_name"),
        Index("idx_batch_source_logs_structure_changed", "source_url", "structure_changed"),
    )

    def to_dict(self) -> dict:
        """모델을 딕셔너리로 변환"""
        return {
            "log_id": self.log_id,
            "run_id": self.run_id,
            "source_url": self.source_url,
            "source_name": self.source_name,
            "chunks_created": self.chunks_created,
            "validation_passed": self.validation_passed,
            "html_structure_hash": self.html_structure_hash,
            "structure_changed": self.structure_changed,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<BatchSourceLog(source={self.source_name}, chunks={self.chunks_created}, valid={self.validation_passed})>"


class ParsingRuleModel(Base):
    """파싱 규칙 모델"""

    __tablename__ = "parsing_rules"

    # Primary Key
    rule_id = Column(
        String, primary_key=True, default=lambda: str(uuid.uuid4()), comment="규칙 고유 ID (UUID)"
    )

    # 소스 정보
    source_url = Column(
        Text, nullable=False, unique=True, index=True, comment="크롤링 소스 URL (UNIQUE)"
    )
    source_name = Column(
        String(100), nullable=False, index=True, comment="소스명 (예: source_page_1)"
    )

    # 파싱 규칙
    content_selector = Column(Text, nullable=False, comment="콘텐츠 추출 CSS Selector")
    remove_selectors = Column(
        JSON, nullable=False, default=[], comment="제거할 선택자 배열 (JSONB)"
    )
    validation_config = Column(
        JSON, nullable=False, default={}, comment="청크 개수 검증 설정 (min_chunks, max_chunks)"
    )

    # 검증 시간
    last_verified_at = Column(DateTime(timezone=True), nullable=True, comment="마지막 검증 시간")

    # 타임스탬프
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, comment="생성 시간"
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="수정 시간",
    )

    # 복합 인덱스
    __table_args__ = (
        Index("idx_parsing_rules_source_url", "source_url", unique=True),
        Index("idx_parsing_rules_source_name", "source_name"),
    )

    def to_dict(self) -> dict:
        """모델을 딕셔너리로 변환"""
        return {
            "rule_id": self.rule_id,
            "source_url": self.source_url,
            "source_name": self.source_name,
            "content_selector": self.content_selector,
            "remove_selectors": self.remove_selectors if self.remove_selectors else [],
            "validation_config": self.validation_config if self.validation_config else {},
            "last_verified_at": (
                self.last_verified_at.isoformat() if self.last_verified_at else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<ParsingRule(source={self.source_name}, selector={self.content_selector[:30]}...)>"
