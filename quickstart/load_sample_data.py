#!/usr/bin/env python3
"""
샘플 데이터 로드 스크립트

Quickstart 샘플 FAQ 데이터를 Weaviate에 직접 적재합니다.
make quickstart-load 또는 make quickstart 명령어에서 자동 실행됩니다.
"""

import json
import os
import sys
import time
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def wait_for_weaviate(url: str, max_retries: int = 30, delay: float = 2.0) -> bool:
    """
    Weaviate가 준비될 때까지 대기

    Args:
        url: Weaviate URL
        max_retries: 최대 재시도 횟수
        delay: 재시도 간격 (초)

    Returns:
        준비 완료 여부
    """
    import urllib.error
    import urllib.request

    ready_url = f"{url}/v1/.well-known/ready"
    print(f"⏳ Weaviate 준비 대기 중... ({url})")

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(ready_url)
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    print("✅ Weaviate 준비 완료!")
                    return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            pass

        if attempt < max_retries - 1:
            print(f"   재시도 {attempt + 1}/{max_retries}...")
            time.sleep(delay)

    print("❌ Weaviate 연결 실패")
    return False


def load_sample_data():
    """
    샘플 FAQ 데이터를 Weaviate에 적재
    """
    # 환경 변수에서 Weaviate URL 가져오기
    weaviate_url = os.getenv("WEAVIATE_URL", "http://localhost:8080")
    weaviate_grpc_host = os.getenv("WEAVIATE_GRPC_HOST", "localhost")
    weaviate_grpc_port = int(os.getenv("WEAVIATE_GRPC_PORT", "50051"))

    # Weaviate 준비 대기
    if not wait_for_weaviate(weaviate_url):
        print("❌ Weaviate에 연결할 수 없습니다.")
        print("   docker compose up -d weaviate 명령어로 Weaviate를 먼저 시작하세요.")
        sys.exit(1)

    # 샘플 데이터 로드
    sample_data_path = Path(__file__).parent / "sample_data.json"
    if not sample_data_path.exists():
        print(f"❌ 샘플 데이터 파일을 찾을 수 없습니다: {sample_data_path}")
        sys.exit(1)

    with open(sample_data_path, encoding="utf-8") as f:
        data = json.load(f)

    documents = data.get("documents", [])
    print(f"📄 {len(documents)}개 문서 로드 중...")

    # Weaviate 클라이언트 연결
    try:
        import weaviate
        from weaviate.classes.config import Configure, DataType, Property
        from weaviate.classes.data import DataObject
    except ImportError:
        print("❌ weaviate 패키지가 설치되지 않았습니다.")
        print("   uv sync 명령어로 의존성을 설치하세요.")
        sys.exit(1)

    # Weaviate v4 클라이언트 연결
    client = weaviate.connect_to_custom(
        http_host=weaviate_url.replace("http://", "").replace("https://", "").split(":")[0],
        http_port=int(weaviate_url.split(":")[-1]) if ":" in weaviate_url.split("/")[-1] else 8080,
        http_secure=weaviate_url.startswith("https"),
        grpc_host=weaviate_grpc_host,
        grpc_port=weaviate_grpc_port,
        grpc_secure=False,
    )

    try:
        # 컬렉션 이름
        collection_name = "QuickstartFAQ"

        # 기존 컬렉션 삭제 (있으면)
        if client.collections.exists(collection_name):
            print(f"🗑️  기존 {collection_name} 컬렉션 삭제 중...")
            client.collections.delete(collection_name)

        # 새 컬렉션 생성
        print(f"📦 {collection_name} 컬렉션 생성 중...")
        collection = client.collections.create(
            name=collection_name,
            properties=[
                Property(name="doc_id", data_type=DataType.TEXT),
                Property(name="title", data_type=DataType.TEXT),
                Property(name="content", data_type=DataType.TEXT),
                Property(name="category", data_type=DataType.TEXT),
                Property(name="tags", data_type=DataType.TEXT_ARRAY),
            ],
            # 한국어 BM25 토크나이저 설정
            vectorizer_config=Configure.Vectorizer.none(),  # 외부 임베딩 사용
            inverted_index_config=Configure.inverted_index(
                bm25_b=0.75,
                bm25_k1=1.2,
            ),
        )

        # 데이터 삽입
        print("📥 문서 삽입 중...")
        objects_to_insert = []
        for doc in documents:
            obj = DataObject(
                properties={
                    "doc_id": doc["id"],
                    "title": doc["title"],
                    "content": doc["content"],
                    "category": doc.get("metadata", {}).get("category", ""),
                    "tags": doc.get("metadata", {}).get("tags", []),
                }
            )
            objects_to_insert.append(obj)

        # 배치 삽입
        collection.data.insert_many(objects_to_insert)

        print(f"✅ {len(documents)}개 문서 적재 완료!")
        print()
        print("🎉 Quickstart 준비 완료!")
        print()
        print("테스트 방법:")
        print("  1. 브라우저에서 http://localhost:8000/docs 접속")
        print("  2. /chat/query 엔드포인트에서 질문 테스트")
        print()
        print("예시 질문:")
        print("  - RAG 시스템이 뭐야?")
        print("  - 하이브리드 검색의 장점은?")
        print("  - GraphRAG가 뭐야?")

    finally:
        client.close()


if __name__ == "__main__":
    load_sample_data()
