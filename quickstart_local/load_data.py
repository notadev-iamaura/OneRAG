#!/usr/bin/env python3
"""
ChromaDB 전용 샘플 데이터 로드 스크립트

Docker 없이 ChromaDB에 샘플 FAQ 데이터를 적재합니다.
BM25 인덱스도 함께 구축하여 하이브리드 검색을 준비합니다.

사용법:
    uv run python quickstart_local/load_data.py

의존성:
    - chromadb: 벡터 스토어
    - sentence-transformers: 로컬 임베딩
    - kiwipiepy, rank-bm25: BM25 인덱스 (선택적)
"""

import asyncio
import json
import pickle
import sys
from pathlib import Path
from typing import Any

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 상수
CHROMA_PERSIST_DIR = str(project_root / "quickstart_local" / ".chroma_data")
BM25_INDEX_PATH = str(project_root / "quickstart_local" / ".bm25_index.pkl")
COLLECTION_NAME = "documents"
SAMPLE_DATA_PATH = project_root / "quickstart" / "sample_data.json"


def prepare_documents(raw_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    sample_data.json 문서를 ChromaDB 적재 형식으로 변환

    Args:
        raw_docs: sample_data.json의 문서 리스트

    Returns:
        ChromaDB 호환 형식의 문서 리스트
        각 문서: {"id": str, "content": str, "metadata": dict}
    """
    result: list[dict[str, Any]] = []

    for doc in raw_docs:
        # title + content 병합 (검색 최적화)
        full_content = f"{doc['title']}\n\n{doc['content']}"

        metadata: dict[str, Any] = {
            "source_file": doc["title"],
            "file_type": doc.get("metadata", {}).get("category", "FAQ"),
            "source": "quickstart_sample",
        }

        # category 추가
        category = doc.get("metadata", {}).get("category", "")
        if category:
            metadata["category"] = category

        result.append({
            "id": doc["id"],
            "content": full_content,
            "metadata": metadata,
        })

    return result


def build_bm25_index(docs: list[dict[str, Any]]) -> Any:
    """
    BM25 인덱스를 구축합니다.

    Args:
        docs: 문서 리스트 (id, content, metadata 포함)

    Returns:
        BM25Index 인스턴스

    Raises:
        ImportError: kiwipiepy 또는 rank-bm25가 미설치된 경우
    """
    from app.modules.core.retrieval.bm25_engine import BM25Index, KoreanTokenizer

    # 불용어 필터 연동 (있으면)
    stopword_filter = None
    try:
        from app.modules.core.retrieval.bm25.stopwords import StopwordFilter
        stopword_filter = StopwordFilter(use_defaults=True, enabled=True)
    except ImportError:
        pass

    tokenizer = KoreanTokenizer(stopword_filter=stopword_filter)
    index = BM25Index(tokenizer=tokenizer)
    index.build(docs)

    return index


async def load_to_chroma(
    docs: list[dict[str, Any]],
    embeddings: list[list[float]],
    persist_dir: str = CHROMA_PERSIST_DIR,
    collection_name: str = COLLECTION_NAME,
) -> int:
    """
    ChromaDB에 문서 적재

    Args:
        docs: 준비된 문서 리스트
        embeddings: 임베딩 벡터 리스트
        persist_dir: ChromaDB 영속 디렉토리
        collection_name: 컬렉션 이름

    Returns:
        적재된 문서 수
    """
    from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

    store = ChromaVectorStore(persist_directory=persist_dir)

    # ChromaVectorStore 형식으로 변환
    chroma_docs = []
    for doc, vector in zip(docs, embeddings, strict=True):
        chroma_docs.append({
            "id": doc["id"],
            "vector": vector,
            "metadata": {
                **doc["metadata"],
                "content": doc["content"],  # 검색 결과에서 내용 반환용
            },
        })

    count = await store.add_documents(
        collection=collection_name,
        documents=chroma_docs,
    )

    return count


def save_bm25_index(index: Any, path: str = BM25_INDEX_PATH) -> None:
    """
    BM25 인덱스 데이터를 파일로 저장

    Kiwi(C 확장)는 pickle 불가이므로, 재구축에 필요한
    문서와 토큰화 결과만 저장합니다.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    serializable_data = {
        "documents": index._documents,
        "tokenized_corpus": index._tokenized_corpus,
    }
    with open(path, "wb") as f:
        pickle.dump(serializable_data, f)


def load_bm25_index(path: str = BM25_INDEX_PATH) -> Any:
    """
    저장된 BM25 인덱스 데이터로 BM25Index를 재구축

    pickle에서 문서 + 토큰화 결과를 로드한 후
    BM25Plus 인스턴스만 재생성합니다 (토큰화 과정 생략).
    """
    from rank_bm25 import BM25Plus

    from app.modules.core.retrieval.bm25_engine import BM25Index, KoreanTokenizer

    with open(path, "rb") as f:
        data = pickle.load(f)  # noqa: S301

    # 토크나이저는 검색 시 쿼리 토큰화에만 사용
    tokenizer = KoreanTokenizer()
    index = BM25Index(tokenizer=tokenizer)

    # 저장된 데이터로 내부 상태 복원 (재토큰화 없이)
    index._documents = data["documents"]
    index._tokenized_corpus = data["tokenized_corpus"]
    index._bm25 = BM25Plus(data["tokenized_corpus"])

    return index


async def main() -> None:
    """메인 실행 함수"""
    print("🚀 Docker-Free 로컬 퀵스타트 - 데이터 로드")
    print()

    # 1. 샘플 데이터 로드
    if not SAMPLE_DATA_PATH.exists():
        print(f"❌ 샘플 데이터 파일을 찾을 수 없습니다: {SAMPLE_DATA_PATH}")
        sys.exit(1)

    with open(SAMPLE_DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    raw_docs = data.get("documents", [])
    print(f"📄 {len(raw_docs)}개 문서 로드")

    # 2. 문서 준비
    docs = prepare_documents(raw_docs)

    # 3. 로컬 임베딩 생성
    print("🤖 로컬 임베딩 모델 초기화 중...")
    print("   (첫 실행 시 모델 다운로드에 1-2분 소요)")

    from app.modules.core.embedding.local_embedder import LocalEmbedder

    embedder = LocalEmbedder(
        model_name="Qwen/Qwen3-Embedding-0.6B",
        output_dimensionality=1024,
        batch_size=32,
        normalize=True,
    )
    print("✅ 임베딩 모델 로드 완료!")

    texts = [doc["content"] for doc in docs]
    print("🔢 임베딩 생성 중...")
    embeddings = embedder.embed_documents(texts)
    print(f"✅ {len(embeddings)}개 임베딩 생성 완료 (차원: {len(embeddings[0])})")

    # 4. ChromaDB 적재
    print("📥 ChromaDB에 문서 적재 중...")
    count = await load_to_chroma(docs, embeddings)
    print(f"✅ {count}개 문서 ChromaDB 적재 완료 ({CHROMA_PERSIST_DIR})")

    # 5. BM25 인덱스 구축
    print("🔍 BM25 인덱스 구축 중...")
    try:
        bm25_index = build_bm25_index(docs)
        save_bm25_index(bm25_index)
        print(f"✅ BM25 인덱스 구축 완료 ({BM25_INDEX_PATH})")
    except ImportError:
        print("⚠️  BM25 의존성 미설치 - Dense 검색만 사용합니다")
        print("   설치: uv sync --extra bm25")

    print()
    print("🎉 데이터 로드 완료!")


if __name__ == "__main__":
    asyncio.run(main())
