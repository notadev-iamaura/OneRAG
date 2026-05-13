#!/usr/bin/env python3
"""
샘플 데이터 로드 스크립트

Quickstart 샘플 FAQ 데이터를 Weaviate에 직접 적재합니다.
애플리케이션 설정과 동일한 임베딩 모델을 사용하여 벡터를 생성합니다.
make start-load 또는 make start 명령어에서 자동 실행됩니다.
"""

import json
import os
import sys
import time
from argparse import ArgumentParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

if TYPE_CHECKING:
    from app.modules.core.embedding.interfaces import IEmbedder

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

RESET_ENV_VAR = "ONERAG_QUICKSTART_RESET"


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


def initialize_embedder() -> "IEmbedder | None":
    """
    애플리케이션 설정과 동일한 임베딩 모델 초기화

    Returns:
        IEmbedder 인스턴스 또는 None (실패 시)
    """
    try:
        from app.lib.config_loader import ConfigLoader
        from app.modules.core.embedding.factory import EmbedderFactory

        config = ConfigLoader().load_config()
        embedder = EmbedderFactory.create(config)
        embeddings_config = config.get("embeddings", {})
        provider = embeddings_config.get("provider", "unknown")

        print("🤖 임베딩 모델 초기화 완료!")
        print(f"   provider={provider}, model={embedder.model_name}, dim={embedder.output_dimensionality}")

        return embedder

    except ImportError as e:
        print(f"❌ 임베딩 모델 로드 실패: {e}")
        print("   uv sync 명령어로 의존성을 설치하세요.")
        return None
    except Exception as e:
        print(f"❌ 임베딩 모델 초기화 오류: {e}")
        return None


def env_flag_enabled(value: str | None) -> bool:
    """Parse common truthy env/CLI flag values."""
    return bool(value and value.strip().lower() in {"1", "true", "yes", "y", "on"})


def sample_document_uuid(collection_name: str, doc_id: str) -> str:
    """Return a deterministic UUID so repeated quickstart loads are idempotent."""
    return str(uuid5(NAMESPACE_URL, f"onerag:quickstart:{collection_name}:{doc_id}"))


def create_documents_collection(client: Any, collection_name: str) -> Any:
    """Create the Weaviate collection expected by OneRAG quickstart."""
    from weaviate.classes.config import Configure, VectorDistances

    print(f"📦 {collection_name} 컬렉션 생성 중...")
    return client.collections.create(
        name=collection_name,
        properties=quickstart_schema_properties(),
        # 외부 임베딩 사용 (애플리케이션 설정과 동일한 모델)
        vector_config=Configure.Vectors.self_provided(
            # 벡터 인덱스 설정 (애플리케이션 임베딩 차원, 코사인 유사도)
            vector_index_config=Configure.VectorIndex.hnsw(
                distance_metric=VectorDistances.COSINE,
            )
        ),
        # BM25 설정 (하이브리드 검색용)
        inverted_index_config=Configure.inverted_index(
            bm25_b=0.75,
            bm25_k1=1.2,
        ),
    )


def quickstart_schema_properties() -> list[Any]:
    """Return the properties required by this loader."""
    from weaviate.classes.config import DataType, Property

    return [
        Property(name="content", data_type=DataType.TEXT),
        Property(name="source_file", data_type=DataType.TEXT),
        Property(name="file_type", data_type=DataType.TEXT),
        Property(name="keywords", data_type=DataType.TEXT_ARRAY),
        Property(name="source", data_type=DataType.TEXT),
    ]


def collection_property_names(collection: Any) -> set[str]:
    """Read property names from a Weaviate v4 collection config."""
    config = collection.config.get(simple=True)
    properties = getattr(config, "properties", {})
    if isinstance(properties, dict):
        return {str(name) for name in properties}
    return {str(prop.name) for prop in properties if getattr(prop, "name", None)}


def ensure_quickstart_schema(collection: Any, collection_name: str) -> int:
    """Add missing quickstart properties without deleting existing data."""
    try:
        existing_names = collection_property_names(collection)
        added_count = 0
        for prop in quickstart_schema_properties():
            if prop.name in existing_names:
                continue
            collection.config.add_property(prop)
            existing_names.add(prop.name)
            added_count += 1
        if added_count:
            print(f"🔧 {collection_name} 컬렉션 누락 프로퍼티 {added_count}개 추가 완료")
        return added_count
    except Exception as e:
        raise RuntimeError(
            f"{collection_name} 컬렉션 스키마가 quickstart 적재와 호환되지 않습니다. "
            "기존 데이터를 보존하려면 스키마를 확인하고, 전체 초기화가 필요할 때만 "
            "--reset 옵션을 사용하세요."
        ) from e


def ensure_documents_collection(client: Any, collection_name: str, reset: bool = False) -> Any:
    """Return a collection without deleting existing data unless reset is explicit."""
    exists = client.collections.exists(collection_name)
    if exists and reset:
        print(f"🗑️  --reset 요청: 기존 {collection_name} 컬렉션 삭제 중...")
        client.collections.delete(collection_name)
        return create_documents_collection(client, collection_name)

    if exists:
        print(f"📦 기존 {collection_name} 컬렉션 사용 중 (삭제하지 않음)")
        print(f"   전체 초기화가 필요하면 --reset 또는 {RESET_ENV_VAR}=true 를 사용하세요.")
        collection = client.collections.get(collection_name)
        ensure_quickstart_schema(collection, collection_name)
        return collection

    return create_documents_collection(client, collection_name)


def build_document_payload(doc: dict, collection_name: str) -> tuple[str, str, dict]:
    """Build deterministic UUID, embedding text, and Weaviate properties for one doc."""
    doc_id = str(doc["id"])
    full_content = f"{doc['title']}\n\n{doc['content']}"
    object_uuid = sample_document_uuid(collection_name, doc_id)
    properties = {
        "content": full_content,
        "source_file": doc["title"],  # 제목을 source_file로
        "file_type": doc.get("metadata", {}).get("category", "FAQ"),
        "keywords": doc.get("metadata", {}).get("tags", []),
        "source": "quickstart_sample",
    }
    return object_uuid, full_content, properties


def load_sample_data(reset: bool | None = None, collection_name: str | None = None) -> None:
    """
    샘플 FAQ 데이터를 Weaviate에 적재
    """
    # 환경 변수에서 Weaviate URL 가져오기
    weaviate_url = os.getenv("WEAVIATE_URL", "http://localhost:8080")
    weaviate_grpc_host = os.getenv("WEAVIATE_GRPC_HOST", "localhost")
    weaviate_grpc_port = int(os.getenv("WEAVIATE_GRPC_PORT", "50051"))
    reset = env_flag_enabled(os.getenv(RESET_ENV_VAR)) if reset is None else reset

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

    # 애플리케이션과 동일한 임베딩 모델 초기화
    embedder = initialize_embedder()
    if embedder is None:
        print("❌ 임베딩 모델 없이는 문서를 적재할 수 없습니다.")
        sys.exit(1)

    # Weaviate 클라이언트 연결
    try:
        import weaviate
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
        target_collection_name = collection_name if collection_name is not None else (
            os.getenv("WEAVIATE_COLLECTION") or "Documents"
        )
        collection = ensure_documents_collection(client, target_collection_name, reset=reset)

        # 문서 텍스트 준비 및 임베딩 생성
        print("🔢 임베딩 생성 중...")
        texts_to_embed = []
        properties_list = []
        object_uuids = []

        for doc in documents:
            object_uuid, full_content, properties = build_document_payload(
                doc,
                target_collection_name,
            )
            object_uuids.append(object_uuid)
            texts_to_embed.append(full_content)
            properties_list.append(properties)

        # 배치 임베딩 생성
        embeddings = embedder.embed_documents(texts_to_embed)
        print(f"✅ {len(embeddings)}개 임베딩 생성 완료 (차원: {len(embeddings[0])})")

        # 데이터 삽입/갱신 (벡터 포함)
        print("📥 문서 삽입 중...")
        updated_count = 0
        new_object_count = 0
        with collection.batch.dynamic() as batch:
            for object_uuid, props, vector in zip(
                object_uuids,
                properties_list,
                embeddings,
                strict=True,
            ):
                if collection.data.exists(object_uuid):
                    collection.data.replace(uuid=object_uuid, properties=props, vector=vector)
                    updated_count += 1
                    continue

                batch.add_object(
                    uuid=object_uuid,
                    properties=props,
                    vector=vector,
                )
                new_object_count += 1

        failed_objects = getattr(collection.batch, "failed_objects", [])
        if failed_objects:
            failed_ids = [
                str(getattr(obj, "original_uuid", getattr(obj, "uuid", "unknown")))
                for obj in failed_objects[:5]
            ]
            raise RuntimeError(
                f"샘플 문서 적재 중 Weaviate 배치 실패가 발생했습니다. "
                f"실패 {len(failed_objects)}개, 예시 ID: {failed_ids}"
            )

        print(f"✅ 샘플 문서 적재 완료! (신규: {new_object_count}개, 갱신: {updated_count}개)")
        print()
        print("🎉 OneRAG 가이드 챗봇 준비 완료!")
        print()
        print("테스트 방법:")
        print("  1. 브라우저에서 http://localhost:8000/docs 접속")
        print("  2. /chat/query 엔드포인트에서 질문 테스트")
        print()
        print("💬 예시 질문 (6개 카테고리 25개 문서):")
        print("  [시작하기] OneRAG 어떻게 설치해?")
        print("  [API 사용법] 채팅 API 사용법 알려줘")
        print("  [설정 가이드] 환경변수 뭐 설정해야 돼?")
        print("  [아키텍처] DI 컨테이너가 뭐야?")
        print("  [개발자 가이드] 테스트 어떻게 실행해?")

    finally:
        client.close()


def main(argv: list[str] | None = None) -> None:
    parser = ArgumentParser(description="Load OneRAG quickstart sample data into Weaviate.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the target collection before loading sample data.",
    )
    parser.add_argument(
        "--collection",
        default=os.getenv("WEAVIATE_COLLECTION", "Documents"),
        help="Target Weaviate collection name. Defaults to WEAVIATE_COLLECTION or Documents.",
    )
    args = parser.parse_args(argv)
    load_sample_data(reset=True if args.reset else None, collection_name=args.collection)


if __name__ == "__main__":
    main()
