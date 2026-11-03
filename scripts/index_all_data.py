#!/usr/bin/env python3
"""
데이터 인덱싱 스크립트 (CLI 래퍼)

실제 로직은 app.modules.ingestion.bulk_index.index_all_data 에 있다.

실행 방법:
    python scripts/index_all_data.py

Railway 환경에서:
    환경변수 WEAVIATE_AUTO_INDEX=true 설정 시 서버 기동 중 자동 실행
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.modules.ingestion.bulk_index import index_all_data  # noqa: E402

if __name__ == "__main__":
    asyncio.run(index_all_data())
