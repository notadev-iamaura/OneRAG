"""
Dynamic YAML Rule Manager
YAML 파일 기반 동적 라우팅 규칙 관리 시스템
"""

import asyncio
import re
import time
from pathlib import Path
from typing import Any

import yaml

from ....lib.logger import get_logger

logger = get_logger(__name__)


class DynamicRuleManager:
    """
    동적 YAML 규칙 관리자

    YAML 파일에서 라우팅 규칙을 로드하고, 주기적으로 자동 리로드하여
    배포 없이 실시간으로 규칙을 수정할 수 있게 함.

    Features:
        - YAML 파일 기반 규칙 정의
        - 자동 리로드 (기본 5분 간격)
        - 다국어 키워드 지원 (ko, en)
        - 우선순위 기반 규칙 매칭
        - 부분 일치 및 대소문자 무시 옵션

    Usage:
        manager = DynamicRuleManager(rule_path="config/routing_rules.yaml")
        await manager.load_rules()
        asyncio.create_task(manager.auto_reload())  # 백그라운드 자동 리로드

        action = manager.match_rule("해킹 방법")
        # action = "security_check"
    """

    def __init__(self, rule_path: str | Path, auto_reload: bool = True):
        """
        Args:
            rule_path: YAML 규칙 파일 경로
            auto_reload: 자동 리로드 활성화 여부
        """
        self.rule_path = Path(rule_path)
        self.rules: dict[str, Any] = {}
        self.settings: dict[str, Any] = {}
        self.last_load_time = 0.0
        self.auto_reload_enabled = auto_reload
        self._reload_task: asyncio.Task | None = None

        # 통계
        self.stats: dict[str, int | float] = {
            "load_count": 0,
            "last_load_time": 0.0,
            "match_count": 0,
            "cache_hit_count": 0,
        }

    def load_rules(self) -> bool:
        """
        YAML 파일에서 규칙 로드 (동기 함수)

        Returns:
            로드 성공 여부
        """
        try:
            if not self.rule_path.exists():
                logger.error(f"Rule file not found: {self.rule_path}")
                return False

            with open(self.rule_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)

            self.rules = config.get("rules", {})
            self.settings = config.get("settings", {})
            self.last_load_time = time.time()
            self.stats["load_count"] += 1
            self.stats["last_load_time"] = self.last_load_time

            logger.info(f"Rules loaded successfully: {len(self.rules)} rules from {self.rule_path}")
            logger.debug(f"Loaded rules: {list(self.rules.keys())}")

            return True

        except Exception as e:
            logger.error(f"Failed to load rules from {self.rule_path}: {e}")
            return False

    async def auto_reload(self) -> None:
        """
        주기적 자동 리로드 (백그라운드 태스크)

        설정된 간격(기본 5분)마다 YAML 파일을 다시 로드하여
        변경사항을 자동으로 반영함.
        """
        if not self.auto_reload_enabled:
            logger.info("Auto-reload is disabled")
            return

        reload_interval = self.settings.get("auto_reload_interval", 300)  # 기본 5분

        logger.info(f"Starting auto-reload task (interval: {reload_interval}s)")

        while True:
            try:
                await asyncio.sleep(reload_interval)
                logger.debug("Auto-reloading routing rules...")

                success = self.load_rules()  # 동기 함수로 변경
                if success:
                    logger.info("✓ Routing rules auto-reloaded successfully")
                else:
                    logger.warning("✗ Routing rules auto-reload failed")

            except asyncio.CancelledError:
                logger.info("Auto-reload task cancelled")
                break
            except Exception as e:
                logger.error(f"Auto-reload task error: {e}")
                await asyncio.sleep(60)  # 에러 시 1분 대기 후 재시도

    def match_rule(self, query: str, language: str = "ko") -> dict[str, Any] | None:
        """
        쿼리와 매칭되는 규칙 찾기

        Args:
            query: 사용자 쿼리
            language: 언어 코드 ('ko' 또는 'en')

        Returns:
            매칭된 규칙 정보 (action, priority, response 등)
            매칭 실패 시 None
        """
        if not self.rules:
            logger.warning("No rules loaded")
            return None

        self.stats["match_count"] += 1

        # 대소문자 무시 설정
        case_sensitive = self.settings.get("case_sensitive", False)
        query_normalized = query if case_sensitive else query.lower()
        utterance = " ".join(re.sub(r"^[^\w]+|[^\w]+$", "", query_normalized).split())

        # 우선순위 순으로 정렬
        sorted_rules = sorted(self.rules.items(), key=lambda x: x[1].get("priority", 999))

        for rule_name, rule_config in sorted_rules:
            keywords = rule_config.get("keywords", {}).get(language, [])
            whole_message = rule_config.get("match_mode") == "whole_message"

            for keyword in keywords:
                keyword_normalized = keyword if case_sensitive else keyword.lower()

                matches = (
                    utterance == keyword_normalized if whole_message
                    else keyword_normalized in query_normalized
                )
                if matches:
                    logger.info(f"Rule matched: '{rule_name}' (keyword: '{keyword}')")

                    return {
                        "rule_name": rule_name,
                        "action": rule_config.get("action"),
                        "priority": rule_config.get("priority"),
                        "response": rule_config.get("response", {}).get(language),
                        "description": rule_config.get("description"),
                        "matched_keyword": keyword,
                    }

        # 매칭 실패 시 기본 액션
        default_action = self.settings.get("default_action", "rag")
        logger.debug(f"No rule matched, using default action: {default_action}")

        return {"rule_name": "default", "action": default_action, "priority": 999}

    def get_rule_info(self, rule_name: str) -> dict[str, Any] | None:
        """
        특정 규칙의 전체 정보 반환

        Args:
            rule_name: 규칙 이름

        Returns:
            규칙 정보 딕셔너리
        """
        return self.rules.get(rule_name)

    def get_all_rules(self) -> dict[str, Any]:
        """
        모든 규칙 반환

        Returns:
            전체 규칙 딕셔너리
        """
        return self.rules

    def get_stats(self) -> dict[str, Any]:
        """
        통계 정보 반환

        Returns:
            통계 딕셔너리
        """
        return {
            **self.stats,
            "rule_count": len(self.rules),
            "last_load_timestamp": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(self.last_load_time)
            ),
        }

    async def start(self) -> None:
        """
        Rule Manager 시작 (로드 + 자동 리로드 태스크 시작)
        """
        self.load_rules()  # 동기 함수로 변경

        if self.auto_reload_enabled:
            self._reload_task = asyncio.create_task(self.auto_reload())
            logger.info("DynamicRuleManager started with auto-reload")
        else:
            logger.info("DynamicRuleManager started without auto-reload")

    async def stop(self) -> None:
        """
        Rule Manager 종료 (자동 리로드 태스크 취소)
        """
        if self._reload_task and not self._reload_task.done():
            self._reload_task.cancel()
            try:
                await self._reload_task
            except asyncio.CancelledError:
                pass

        logger.info("DynamicRuleManager stopped")
