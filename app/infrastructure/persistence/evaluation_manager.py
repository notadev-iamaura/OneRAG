"""
평가 데이터 관리 모듈

PostgreSQL을 사용하여 사용자 평가 데이터를 영구 저장하고 관리합니다.
FastAPI 평가 API (/api/evaluations)의 백엔드 데이터 계층입니다.

주요 기능:
- 평가 데이터 CRUD (생성, 조회, 수정, 삭제)
- 평가 통계 및 분석 (평균 점수, 트렌드, 분포)
- 필터링 및 페이지네이션 지원
- 데이터 내보내기 (JSON, CSV)
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, asc, delete, desc, func, select

from app.models.evaluation import (
    EvaluationCreate,
    EvaluationFilter,
    EvaluationResponse,
    EvaluationStatistics,
    EvaluationUpdate,
)

from .connection import db_manager
from .models import EvaluationModel

logger = logging.getLogger(__name__)


class DuplicateEvaluationError(Exception):
    """이미 동일한 메시지에 대한 평가가 존재할 때 발생."""

    def __init__(self, message_id: str, evaluation_id: str):
        self.message_id = message_id
        self.evaluation_id = evaluation_id
        super().__init__(f"메시지 {message_id}에 대한 평가 {evaluation_id}가 이미 존재합니다")


class EvaluationDataManager:
    """
    평가 데이터 관리자

    PostgreSQL을 사용한 평가 데이터의 영구 저장 및 관리를 담당합니다.
    Repository 패턴을 구현하여 데이터 접근 계층을 캡슐화합니다.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """
        평가 데이터 관리자 초기화

        Args:
            config: 설정 정보 (선택적)
        """
        self.config = config or {}
        self.db_manager = db_manager

    async def initialize(self) -> None:
        """모듈 초기화 (비동기)"""
        import os

        # 테스트 환경에서는 PostgreSQL 초기화 스킵
        if os.getenv("PYTEST_CURRENT_TEST"):
            logger.info("⚠️ 테스트 환경: PostgreSQL 평가 모듈 초기화 스킵")
            return

        logger.info("PostgreSQL 평가 모듈 초기화 중...")

        # 데이터베이스 연결 초기화
        await self.db_manager.initialize()

        # 테이블 생성 (필요시)
        await self.db_manager.create_tables()

        logger.info("PostgreSQL 평가 모듈 초기화 완료")

    async def cleanup(self) -> None:
        """모듈 정리"""
        logger.info("PostgreSQL 평가 모듈 정리 중...")
        # 데이터베이스 연결 종료는 메인 앱에서 처리
        logger.info("PostgreSQL 평가 모듈 정리 완료")

    async def create_evaluation(self, evaluation_data: EvaluationCreate) -> EvaluationResponse:
        """
        새 평가 생성

        Args:
            evaluation_data: 평가 생성 데이터

        Returns:
            생성된 평가 정보
        """
        async with self.db_manager.get_session() as session:
            # 중복 평가 확인
            existing = await session.execute(
                select(EvaluationModel).where(
                    EvaluationModel.message_id == evaluation_data.message_id
                )
            )
            existing_eval = existing.scalar_one_or_none()
            if existing_eval:
                raise DuplicateEvaluationError(
                    message_id=evaluation_data.message_id,
                    evaluation_id=str(existing_eval.evaluation_id),
                )

            # 새 평가 생성
            evaluation = EvaluationModel(
                session_id=evaluation_data.session_id,
                message_id=evaluation_data.message_id,
                query_score=evaluation_data.query_score,
                response_score=evaluation_data.response_score,
                overall_score=evaluation_data.overall_score,
                relevance_score=evaluation_data.relevance_score,
                accuracy_score=evaluation_data.accuracy_score,
                completeness_score=evaluation_data.completeness_score,
                clarity_score=evaluation_data.clarity_score,
                feedback=evaluation_data.feedback,
                evaluator_id=evaluation_data.evaluator_id,
                evaluation_type=evaluation_data.evaluator_type or "human",
                query_text=evaluation_data.query,
                response_text=evaluation_data.response,
                extra_metadata=evaluation_data.metadata,
            )

            session.add(evaluation)
            await session.commit()
            await session.refresh(evaluation)

            logger.info(f"평가 생성 완료: {evaluation.evaluation_id}")

            return EvaluationResponse(**evaluation.to_dict())

    async def get_evaluation(self, evaluation_id: str) -> EvaluationResponse | None:
        """
        평가 ID로 조회

        Args:
            evaluation_id: 평가 고유 ID

        Returns:
            평가 정보 또는 None
        """
        async with self.db_manager.get_session() as session:
            result = await session.execute(
                select(EvaluationModel).where(EvaluationModel.evaluation_id == evaluation_id)
            )
            evaluation = result.scalar_one_or_none()

            if evaluation:
                return EvaluationResponse(**evaluation.to_dict())
            return None

    async def get_evaluation_by_message(self, message_id: str) -> EvaluationResponse | None:
        """
        메시지 ID로 평가 조회

        Args:
            message_id: 메시지 고유 ID

        Returns:
            평가 정보 또는 None
        """
        async with self.db_manager.get_session() as session:
            result = await session.execute(
                select(EvaluationModel).where(EvaluationModel.message_id == message_id)
            )
            evaluation = result.scalar_one_or_none()

            if evaluation:
                return EvaluationResponse(**evaluation.to_dict())
            return None

    async def get_session_evaluations(
        self, session_id: str, skip: int = 0, limit: int = 20
    ) -> list[EvaluationResponse]:
        """
        세션의 평가 목록 조회

        Args:
            session_id: 세션 ID
            skip: 건너뛸 개수
            limit: 조회할 최대 개수

        Returns:
            평가 목록
        """
        async with self.db_manager.get_session() as session:
            query = (
                select(EvaluationModel)
                .where(EvaluationModel.session_id == session_id)
                .order_by(desc(EvaluationModel.created_at))
                .offset(skip)
                .limit(limit)
            )

            result = await session.execute(query)
            evaluations = result.scalars().all()

            return [EvaluationResponse(**e.to_dict()) for e in evaluations]

    async def get_all_evaluations(
        self,
        filter_params: EvaluationFilter | None = None,
        skip: int = 0,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """
        전체 평가 목록 조회 (필터링 및 페이지네이션 지원)

        Args:
            filter_params: 필터 조건
            skip: 건너뛸 개수
            limit: 조회할 최대 개수
            sort_by: 정렬 기준 필드
            sort_order: 정렬 순서 (asc/desc)

        Returns:
            평가 목록과 총 개수
        """
        async with self.db_manager.get_session() as session:
            # 기본 쿼리
            query = select(EvaluationModel)
            count_query = select(func.count()).select_from(EvaluationModel)

            # 필터 적용
            if filter_params:
                conditions = []

                if filter_params.session_id:
                    conditions.append(EvaluationModel.session_id == filter_params.session_id)

                if filter_params.evaluator_id:
                    conditions.append(EvaluationModel.evaluator_id == filter_params.evaluator_id)

                if filter_params.start_date:
                    conditions.append(EvaluationModel.created_at >= filter_params.start_date)

                if filter_params.end_date:
                    conditions.append(EvaluationModel.created_at <= filter_params.end_date)

                if filter_params.has_feedback is not None:
                    if filter_params.has_feedback:
                        conditions.append(EvaluationModel.feedback.is_not(None))
                    else:
                        conditions.append(EvaluationModel.feedback.is_(None))

                if filter_params.min_score:
                    conditions.append(EvaluationModel.overall_score >= filter_params.min_score)

                if filter_params.max_score:
                    conditions.append(EvaluationModel.overall_score <= filter_params.max_score)

                if conditions:
                    where_clause = and_(*conditions)
                    query = query.where(where_clause)
                    count_query = count_query.where(where_clause)

            # 총 개수 조회
            total_result = await session.execute(count_query)
            total_count = total_result.scalar()

            # 정렬 적용
            sort_column = getattr(EvaluationModel, sort_by, EvaluationModel.created_at)
            if sort_order == "asc":
                query = query.order_by(asc(sort_column))
            else:
                query = query.order_by(desc(sort_column))

            # 페이지네이션 적용
            query = query.offset(skip).limit(limit)

            # 데이터 조회
            result = await session.execute(query)
            evaluations = result.scalars().all()

            return {
                "total": total_count,
                "items": [EvaluationResponse(**e.to_dict()) for e in evaluations],
                "skip": skip,
                "limit": limit,
            }

    async def update_evaluation(
        self, evaluation_id: str, update_data: EvaluationUpdate
    ) -> EvaluationResponse | None:
        """
        평가 업데이트

        Args:
            evaluation_id: 평가 ID
            update_data: 업데이트 데이터

        Returns:
            업데이트된 평가 정보 또는 None
        """
        async with self.db_manager.get_session() as session:
            result = await session.execute(
                select(EvaluationModel).where(EvaluationModel.evaluation_id == evaluation_id)
            )
            evaluation = result.scalar_one_or_none()

            if not evaluation:
                return None

            # 업데이트 적용
            update_dict = update_data.model_dump(exclude_unset=True)
            if "metadata" in update_dict:
                update_dict["extra_metadata"] = update_dict.pop("metadata")
            for key, value in update_dict.items():
                if hasattr(evaluation, key):
                    setattr(evaluation, key, value)

            # updated_at는 SQLAlchemy의 onupdate=func.now()로 자동 관리됨
            # 명시적 설정 필요 시 아래 주석 해제
            # evaluation.updated_at = datetime.utcnow()  # type: ignore[assignment]

            await session.commit()
            await session.refresh(evaluation)

            logger.info(f"평가 업데이트 완료: {evaluation_id}")

            return EvaluationResponse(**evaluation.to_dict())

    async def delete_evaluation(self, evaluation_id: str) -> bool:
        """
        평가 삭제

        Args:
            evaluation_id: 평가 ID

        Returns:
            삭제 성공 여부
        """
        async with self.db_manager.get_session() as session:
            result = await session.execute(
                delete(EvaluationModel).where(EvaluationModel.evaluation_id == evaluation_id)
            )
            await session.commit()

            if result.rowcount > 0:
                logger.info(f"평가 삭제 완료: {evaluation_id}")
                return True
            return False

    async def get_statistics(
        self, filter_params: EvaluationFilter | None = None, use_cache: bool = True
    ) -> EvaluationStatistics:
        """
        평가 통계 조회

        Args:
            filter_params: 필터 조건
            use_cache: 캐시 사용 여부 (현재 미구현)

        Returns:
            평가 통계
        """
        async with self.db_manager.get_session() as session:
            # 기본 쿼리
            query = select(EvaluationModel)

            # 필터 적용
            if filter_params:
                conditions = []

                if filter_params.session_id:
                    conditions.append(EvaluationModel.session_id == filter_params.session_id)

                if filter_params.evaluator_id:
                    conditions.append(EvaluationModel.evaluator_id == filter_params.evaluator_id)

                if filter_params.start_date:
                    conditions.append(EvaluationModel.created_at >= filter_params.start_date)

                if filter_params.end_date:
                    conditions.append(EvaluationModel.created_at <= filter_params.end_date)

                if filter_params.has_feedback is not None:
                    if filter_params.has_feedback:
                        conditions.append(EvaluationModel.feedback.is_not(None))
                    else:
                        conditions.append(EvaluationModel.feedback.is_(None))

                if filter_params.min_score:
                    conditions.append(EvaluationModel.overall_score >= filter_params.min_score)

                if filter_params.max_score:
                    conditions.append(EvaluationModel.overall_score <= filter_params.max_score)

                if conditions:
                    query = query.where(and_(*conditions))

            result = await session.execute(query)
            evaluations = result.scalars().all()

            # 통계 계산
            stats = await self._calculate_statistics(list(evaluations))

            return stats

    async def _calculate_statistics(
        self, evaluations: list[EvaluationModel]
    ) -> EvaluationStatistics:
        """통계 계산"""
        # 명시적으로 기본값 전달 (mypy 타입 체크 호환)
        stats = EvaluationStatistics(
            total_evaluations=0,
            average_query_score=None,
            average_response_score=None,
            average_overall_score=None,
            average_relevance_score=None,
            average_accuracy_score=None,
            average_completeness_score=None,
            average_clarity_score=None,
            score_distribution={},
            feedback_count=0,
            feedback_rate=0.0,
            last_evaluation_at=None,
            evaluations_today=0,
            evaluations_this_week=0,
            evaluations_this_month=0,
            unique_sessions=0,
            average_evaluations_per_session=0.0,
        )

        if not evaluations:
            return stats

        stats.total_evaluations = len(evaluations)

        # 점수별 집계
        score_fields = [
            "query_score",
            "response_score",
            "overall_score",
            "relevance_score",
            "accuracy_score",
            "completeness_score",
            "clarity_score",
        ]

        score_sums: dict[str, float] = defaultdict(float)
        score_counts: dict[str, int] = defaultdict(int)
        stats.score_distribution = defaultdict(lambda: defaultdict(int))

        for evaluation in evaluations:
            for field in score_fields:
                score = getattr(evaluation, field)
                if score is not None:
                    score_sums[field] += score
                    score_counts[field] += 1
                    stats.score_distribution[field][score] += 1

        # 평균 계산
        for field in score_fields:
            if score_counts[field] > 0:
                avg_field = f"average_{field}"
                setattr(stats, avg_field, score_sums[field] / score_counts[field])

        # 피드백 통계
        feedback_evaluations = [e for e in evaluations if e.feedback]
        stats.feedback_count = len(feedback_evaluations)
        stats.feedback_rate = (
            stats.feedback_count / stats.total_evaluations if stats.total_evaluations > 0 else 0
        )

        # 시간 통계
        if evaluations:
            sorted_by_time = sorted(
                evaluations, key=lambda e: e.created_at or datetime.min, reverse=True
            )
            # SQLAlchemy Column 타입을 datetime으로 변환
            last_created_at = sorted_by_time[0].created_at
            if last_created_at is not None:
                stats.last_evaluation_at = (
                    last_created_at if isinstance(last_created_at, datetime) else None
                )

            now = datetime.utcnow()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=today_start.weekday())
            month_start = today_start.replace(day=1)

            # created_at 비교를 위한 안전한 필터링
            stats.evaluations_today = len(
                [e for e in evaluations if e.created_at and e.created_at >= today_start]
            )
            stats.evaluations_this_week = len(
                [e for e in evaluations if e.created_at and e.created_at >= week_start]
            )
            stats.evaluations_this_month = len(
                [e for e in evaluations if e.created_at and e.created_at >= month_start]
            )

        # 세션 통계
        unique_sessions = {e.session_id for e in evaluations}
        stats.unique_sessions = len(unique_sessions)
        stats.average_evaluations_per_session = (
            stats.total_evaluations / stats.unique_sessions if stats.unique_sessions > 0 else 0
        )

        return stats

    async def export_evaluations(
        self, format: str = "json", filter_params: EvaluationFilter | None = None
    ) -> str:
        """
        평가 데이터 내보내기

        Args:
            format: 내보내기 형식 (json, csv)
            filter_params: 필터 조건

        Returns:
            내보낸 데이터 (문자열)
        """
        async with self.db_manager.get_session() as session:
            query = select(EvaluationModel)

            # 필터 적용
            if filter_params:
                conditions = []

                if filter_params.session_id:
                    conditions.append(EvaluationModel.session_id == filter_params.session_id)

                if filter_params.start_date:
                    conditions.append(EvaluationModel.created_at >= filter_params.start_date)

                if filter_params.end_date:
                    conditions.append(EvaluationModel.created_at <= filter_params.end_date)

                if conditions:
                    query = query.where(and_(*conditions))

            result = await session.execute(query)
            evaluations = result.scalars().all()

            if format == "json":
                data = [e.to_dict() for e in evaluations]
                return json.dumps(data, ensure_ascii=False, indent=2, default=str)
            elif format == "csv":
                # CSV 형식으로 변환
                if not evaluations:
                    return ""

                import csv
                from io import StringIO

                output = StringIO()
                fieldnames = [
                    "evaluation_id",
                    "session_id",
                    "message_id",
                    "query_score",
                    "response_score",
                    "overall_score",
                    "feedback",
                    "created_at",
                ]

                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()

                for evaluation in evaluations:
                    row = {
                        "evaluation_id": evaluation.evaluation_id,
                        "session_id": evaluation.session_id,
                        "message_id": evaluation.message_id,
                        "query_score": evaluation.query_score,
                        "response_score": evaluation.response_score,
                        "overall_score": evaluation.overall_score,
                        "feedback": evaluation.feedback or "",
                        "created_at": (
                            evaluation.created_at.isoformat() if evaluation.created_at else ""
                        ),
                    }
                    writer.writerow(row)

                return output.getvalue()
            else:
                raise ValueError(f"지원하지 않는 형식: {format}")

    async def get_recent_evaluations(self, limit: int = 10) -> list[EvaluationResponse]:
        """
        최근 평가 목록 조회

        Args:
            limit: 조회할 최대 개수

        Returns:
            평가 목록
        """
        async with self.db_manager.get_session() as session:
            query = select(EvaluationModel).order_by(desc(EvaluationModel.created_at)).limit(limit)

            result = await session.execute(query)
            evaluations = result.scalars().all()

            return [EvaluationResponse(**e.to_dict()) for e in evaluations]
