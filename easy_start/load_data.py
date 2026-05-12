#!/usr/bin/env python3
"""
ChromaDB 전용 샘플 데이터 로드 스크립트

Docker 없이 ChromaDB에 샘플 FAQ 데이터를 적재합니다.
BM25 인덱스도 함께 구축하여 하이브리드 검색을 준비합니다.
다국어 지원: 선택된 언어에 맞는 샘플 데이터를 자동으로 로드합니다.

사용법:
    uv run python easy_start/load_data.py
    EASY_START_LANG=en uv run python easy_start/load_data.py

의존성:
    - chromadb: 벡터 스토어
    - sentence-transformers: 로컬 임베딩
    - kiwipiepy, rank-bm25: BM25 인덱스 (선택적)
"""

import asyncio
import hashlib
import json
import pickle
import sys
from pathlib import Path
from typing import Any

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from easy_start.i18n import get_sample_data_path, t  # noqa: E402

# 상수
CHROMA_PERSIST_DIR = str(project_root / "easy_start" / ".chroma_data")
BM25_INDEX_PATH = str(project_root / "easy_start" / ".bm25_index.pkl")
MANIFEST_PATH = str(project_root / "easy_start" / ".load_manifest.json")
COLLECTION_NAME = "documents"
DATASET_VERSION = "2026-05-12"


def _resolve_sample_data_path() -> Path:
    """
    언어별 샘플 데이터 파일 경로 반환

    i18n 모듈의 get_sample_data_path() 사용.
    없으면 기존 quickstart/sample_data.json으로 폴백.

    Returns:
        샘플 데이터 JSON 파일 경로
    """
    path = get_sample_data_path()
    if path.exists():
        return path

    # 폴백: 기존 경로
    fallback = project_root / "quickstart" / "sample_data.json"
    return fallback


def _file_sha256(path: Path) -> str:
    """파일 내용 SHA-256 해시 반환."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_load_manifest(sample_data_path: Path, document_count: int) -> dict[str, Any]:
    """
    현재 easy-start 샘플 데이터의 적재 매니페스트 생성.

    ChromaDB/BM25 캐시가 오래된 샘플 데이터에서 생성되었는지 판별하는 데 사용합니다.
    """
    return {
        "dataset_version": DATASET_VERSION,
        "language": sample_data_path.stem.removeprefix("sample_data_"),
        "sample_data_path": str(sample_data_path.relative_to(project_root)),
        "sample_sha256": _file_sha256(sample_data_path),
        "document_count": document_count,
        "collection": COLLECTION_NAME,
    }


def load_manifest(path: str = MANIFEST_PATH) -> dict[str, Any] | None:
    """저장된 easy-start 적재 매니페스트 로드."""
    manifest_path = Path(path)
    if not manifest_path.exists():
        return None
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def save_manifest(manifest: dict[str, Any], path: str = MANIFEST_PATH) -> None:
    """easy-start 적재 매니페스트 저장."""
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def expected_manifest() -> dict[str, Any]:
    """현재 언어 설정 기준으로 기대되는 easy-start 매니페스트 반환."""
    sample_data_path = _resolve_sample_data_path()
    if not sample_data_path.exists():
        return {}
    with open(sample_data_path, encoding="utf-8") as f:
        data = json.load(f)
    raw_docs = data.get("documents", [])
    document_count = len(raw_docs) if isinstance(raw_docs, list) else 0
    return build_load_manifest(sample_data_path, document_count)


def is_manifest_current(path: str = MANIFEST_PATH) -> bool:
    """저장된 매니페스트가 현재 샘플 데이터와 일치하는지 확인."""
    current = load_manifest(path)
    expected = expected_manifest()
    return bool(current and expected and current == expected)


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
        # 필수 필드 검증
        doc_id = doc.get("id", "")
        title = doc.get("title", "")
        content = doc.get("content", "")
        if not doc_id or not content:
            continue

        # title + content 병합 (검색 최적화)
        full_content = f"{title}\n\n{content}" if title else content

        metadata: dict[str, Any] = {
            "source_file": title,
            "file_type": doc.get("metadata", {}).get("category", "FAQ"),
            "source": "quickstart_sample",
        }

        # category 추가
        category = doc.get("metadata", {}).get("category", "")
        if category:
            metadata["category"] = category

        result.append({
            "id": doc_id,
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

    return int(count)


def reset_chroma_collection(
    persist_dir: str = CHROMA_PERSIST_DIR,
    collection_name: str = COLLECTION_NAME,
) -> None:
    """easy-start 샘플 컬렉션을 재생성할 수 있도록 기존 컬렉션을 제거."""
    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )
    try:
        client.delete_collection(collection_name)
    except Exception:
        return


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
    print(f"🚀 {t('load.title')}")
    print()

    # 1. 샘플 데이터 로드
    sample_data_path = _resolve_sample_data_path()
    if not sample_data_path.exists():
        print(f"❌ {t('load.sample_not_found', path=sample_data_path)}")
        sys.exit(1)

    with open(sample_data_path, encoding="utf-8") as f:
        data = json.load(f)

    raw_docs = data.get("documents", [])
    print(f"📄 {t('load.docs_loaded', count=len(raw_docs))}")
    manifest = build_load_manifest(sample_data_path, len(raw_docs))

    # 2. 문서 준비
    docs = prepare_documents(raw_docs)

    # 3. 로컬 임베딩 생성
    print(f"🤖 {t('load.embedding_init')}")
    print(f"   {t('load.embedding_init_note')}")

    from app.modules.core.embedding.local_embedder import LocalEmbedder

    embedder = LocalEmbedder(
        model_name="Qwen/Qwen3-Embedding-0.6B",
        output_dimensionality=1024,
        batch_size=32,
        normalize=True,
    )
    print(f"✅ {t('load.embedding_ready')}")

    texts = [doc["content"] for doc in docs]
    print(f"🔢 {t('load.embedding_generating')}")
    embeddings = embedder.embed_documents(texts)
    print(f"✅ {t('load.embedding_done', count=len(embeddings), dim=len(embeddings[0]))}")

    # 4. ChromaDB 적재
    print(f"📥 {t('load.chroma_loading')}")
    reset_chroma_collection()
    count = await load_to_chroma(docs, embeddings)
    print(f"✅ {t('load.chroma_done', count=count, path=CHROMA_PERSIST_DIR)}")

    # 5. BM25 인덱스 구축
    print(f"🔍 {t('load.bm25_building')}")
    Path(BM25_INDEX_PATH).unlink(missing_ok=True)
    try:
        bm25_index = build_bm25_index(docs)
        save_bm25_index(bm25_index)
        print(f"✅ {t('load.bm25_done', path=BM25_INDEX_PATH)}")
    except ImportError:
        print(f"⚠️  {t('load.bm25_missing')}")
        print(f"   {t('load.bm25_install')}")

    save_manifest(manifest)
    print()
    print(f"🎉 {t('load.complete')}")


if __name__ == "__main__":
    asyncio.run(main())
