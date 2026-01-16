#!/usr/bin/env python3
"""
샘플 데이터 로드 스크립트

Quickstart 샘플 FAQ 데이터를 Weaviate에 직접 적재합니다.
로컬 임베딩 모델(Qwen3-Embedding-0.6B)을 사용하여 벡터를 생성합니다.
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

# 임베딩 설정 상수
DEFAULT_EMBEDDING_DIM = 1024  # Qwen3-Embedding-0.6B 기본 차원


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


def initialize_embedder():
    """
    로컬 임베딩 모델 초기화

    Returns:
        LocalEmbedder 인스턴스 또는 None (실패 시)
    """
    try:
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        print("🤖 로컬 임베딩 모델 초기화 중...")
        print("   (첫 실행 시 모델 다운로드에 1-2분 소요)")

        embedder = LocalEmbedder(
            model_name="Qwen/Qwen3-Embedding-0.6B",
            output_dimensionality=DEFAULT_EMBEDDING_DIM,
            batch_size=32,
            normalize=True,
        )

        print("✅ 임베딩 모델 로드 완료!")
        return embedder

    except ImportError as e:
        print(f"❌ 임베딩 모델 로드 실패: {e}")
        print("   uv sync 명령어로 의존성을 설치하세요.")
        return None
    except Exception as e:
        print(f"❌ 임베딩 모델 초기화 오류: {e}")
        return None


def load_sample_data() -> None:
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

    # 로컬 임베딩 모델 초기화
    embedder = initialize_embedder()
    if embedder is None:
        print("❌ 임베딩 모델 없이는 문서를 적재할 수 없습니다.")
        sys.exit(1)

    # Weaviate 클라이언트 연결
    try:
        import weaviate
        from weaviate.classes.config import Configure, DataType, Property, VectorDistances
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
        # 컬렉션 이름 - RAG 시스템 기본 컬렉션과 동일하게 설정
        collection_name = os.getenv("WEAVIATE_COLLECTION", "Documents")

        # 기존 컬렉션 삭제 (있으면)
        if client.collections.exists(collection_name):
            print(f"🗑️  기존 {collection_name} 컬렉션 삭제 중...")
            client.collections.delete(collection_name)

        # 새 컬렉션 생성 (RAG 시스템 호환 스키마)
        # RAG 시스템이 기대하는 프로퍼티: content, source_file, file_type, keywords
        print(f"📦 {collection_name} 컬렉션 생성 중...")
        collection = client.collections.create(
            name=collection_name,
            properties=[
                Property(name="content", data_type=DataType.TEXT),
                Property(name="source_file", data_type=DataType.TEXT),
                Property(name="file_type", data_type=DataType.TEXT),
                Property(name="keywords", data_type=DataType.TEXT_ARRAY),
                # 추가 메타데이터 (선택적)
                Property(name="source", data_type=DataType.TEXT),
            ],
            # 외부 임베딩 사용 (로컬 Qwen3 모델)
            vectorizer_config=Configure.Vectorizer.none(),
            # 벡터 인덱스 설정 (1024차원, 코사인 유사도)
            vector_index_config=Configure.VectorIndex.hnsw(
                distance_metric=VectorDistances.COSINE,
            ),
            # BM25 설정 (하이브리드 검색용)
            inverted_index_config=Configure.inverted_index(
                bm25_b=0.75,
                bm25_k1=1.2,
            ),
        )

        # 문서 텍스트 준비 및 임베딩 생성
        print("🔢 임베딩 생성 중...")
        texts_to_embed = []
        properties_list = []

        for doc in documents:
            # title + content를 합쳐서 content로 저장 (검색 최적화)
            full_content = f"{doc['title']}\n\n{doc['content']}"
            texts_to_embed.append(full_content)
            properties_list.append({
                "content": full_content,
                "source_file": doc["title"],  # 제목을 source_file로
                "file_type": doc.get("metadata", {}).get("category", "FAQ"),
                "keywords": doc.get("metadata", {}).get("tags", []),
                "source": "quickstart_sample",
            })

        # 배치 임베딩 생성
        embeddings = embedder.embed_documents(texts_to_embed)
        print(f"✅ {len(embeddings)}개 임베딩 생성 완료 (차원: {len(embeddings[0])})")

        # 데이터 삽입 (벡터 포함)
        print("📥 문서 삽입 중...")
        with collection.batch.dynamic() as batch:
            for props, vector in zip(properties_list, embeddings):
                batch.add_object(
                    properties=props,
                    vector=vector,
                )

        print(f"✅ {len(documents)}개 문서 적재 완료!")
        print()
        print("🎉 RAG_Standard 가이드 챗봇 준비 완료!")
        print()
        print("테스트 방법:")
        print("  1. 브라우저에서 http://localhost:8000/docs 접속")
        print("  2. /chat/query 엔드포인트에서 질문 테스트")
        print()
        print("💬 예시 질문 (6개 카테고리 25개 문서):")
        print("  [시작하기] RAG_Standard 어떻게 설치해?")
        print("  [API 사용법] 채팅 API 사용법 알려줘")
        print("  [설정 가이드] 환경변수 뭐 설정해야 돼?")
        print("  [아키텍처] DI 컨테이너가 뭐야?")
        print("  [개발자 가이드] 테스트 어떻게 실행해?")

    finally:
        client.close()


if __name__ == "__main__":
    load_sample_data()
