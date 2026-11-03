"""Weaviate 샘플 데이터 일괄 인덱싱 (scripts/index_all_data.py 에서 이동).

운영 코드(main.py 의 WEAVIATE_AUTO_INDEX, 관리자 라우터의 수동 인덱싱)가 scripts/ 패키지를
import 하던 계층 위반을 없애기 위해 app 패키지 안으로 옮겼다. scripts/index_all_data.py 는
이 모듈을 호출하는 얇은 CLI 래퍼다.
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import UTC, datetime
from typing import Any

from app.lib.logger import get_logger
from app.lib.weaviate_client import get_weaviate_client

logger = get_logger(__name__)

# 샘플 데이터 (실제 데이터 파일이 없을 경우 사용)
SAMPLE_ENTITIES = [
    {
        "name": "강남 지점",
        "location": "서울 강남구",
        "description": "강남역 인근의 메인 지점. 최신 시설과 전문 인력을 보유하고 있습니다.",
        "price": "50,000",
        "capacity": "100",
        "rating": "4.5",
    },
    {
        "name": "부산 지점",
        "location": "부산 해운대구",
        "description": "바다를 조망할 수 있는 지역 거점. 넓은 공간과 쾌적한 환경이 특징입니다.",
        "price": "40,000",
        "capacity": "80",
        "rating": "4.2",
    },
]


async def index_all_data() -> dict[str, Any]:
    """데이터 인덱싱 통합 함수"""
    start_time = time.time()
    logger.info("🚀 데이터 인덱싱 시작")

    try:
        # 1. Weaviate 클라이언트 연결
        weaviate_client = get_weaviate_client()
        if weaviate_client.client is None:
            logger.error("❌ Weaviate 연결 실패")
            return {"count": 0, "duration": 0}

        client = weaviate_client.client

        # 2. Documents 컬렉션 확인
        collection_name = "Documents"
        if not client.collections.exists(collection_name):
            logger.info(f"🔧 {collection_name} 컬렉션이 없어 생성합니다.")
            from app.lib.weaviate_setup import create_schema

            await create_schema()

        collection = client.collections.get(collection_name)

        # 3. 데이터 준비 및 업로드
        count = 0
        for entity in SAMPLE_ENTITIES:
            # 더미 벡터 생성 (실제 운영 시에는 임베딩 모델 사용)

            vector = [0.1 * random.random() for _ in range(3072)]

            properties = {
                "content": f"{entity['name']} - {entity['description']} 위치: {entity['location']}",
                "entity_name": entity["name"],
                "location": entity["location"],
                "price": entity["price"],
                "capacity": entity["capacity"],
                "rating": entity["rating"],
                "source": "sample_data",
                "created_at": datetime.now(UTC).isoformat(),
            }

            # Weaviate에 삽입
            await asyncio.to_thread(collection.data.insert, properties=properties, vector=vector)
            count += 1

        duration = time.time() - start_time
        logger.info(f"✅ 인덱싱 완료: {count}개 문서 ({duration:.2f}초)")

        return {"count": count, "duration": duration}

    except Exception as e:
        logger.error(f"❌ 인덱싱 중 오류 발생: {e}", exc_info=True)
        return {"count": 0, "duration": 0}



__all__ = ["SAMPLE_ENTITIES", "index_all_data"]
