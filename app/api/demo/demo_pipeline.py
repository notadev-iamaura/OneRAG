"""
DemoPipeline — 데모용 경량 RAG 파이프라인

세션별 문서 인제스트, 벡터 검색, LLM 답변 생성을 수행합니다.
기존 DocumentProcessor의 복잡한 의존성을 건너뛰고
GeminiEmbedder + ChromaVectorStore를 직접 사용합니다.

주요 기능:
- 파일 업로드 → 텍스트 추출 → 청킹 → 임베딩 → ChromaDB 저장
- 질문 → 임베딩 → ChromaDB 검색 → Gemini LLM 답변 생성
- SSE 스트리밍 답변 지원
"""

import asyncio
import hashlib
import tempfile
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.lib.logger import get_logger

from .session_manager import DemoSession, DemoSessionManager

logger = get_logger(__name__)

# =============================================================================
# 상수
# =============================================================================

# 청킹 설정
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100

# 검색 설정
TOP_K = 5

# RAG 프롬프트
RAG_SYSTEM_PROMPT = """당신은 RAG(Retrieval-Augmented Generation) 기반 AI 어시스턴트입니다.
주어진 문서 컨텍스트를 기반으로 정확하고 도움이 되는 답변을 제공하세요.

규칙:
1. 문서에 있는 정보만 사용하여 답변하세요.
2. 문서에 관련 정보가 없으면 솔직히 "제공된 문서에서 관련 정보를 찾을 수 없습니다"라고 답하세요.
3. 가능하면 구체적인 내용을 인용하여 답변하세요.
4. 답변은 한국어 또는 질문의 언어로 작성하세요."""

RAG_USER_TEMPLATE = """다음 문서 컨텍스트를 참고하여 질문에 답변해주세요.

## 문서 컨텍스트
{context}

## 질문
{question}

## 답변"""

# 지원 파일 형식
ALLOWED_EXTENSIONS = {"pdf", "txt", "md", "csv", "docx"}


# =============================================================================
# 텍스트 추출기
# =============================================================================


async def extract_text_from_file(file_path: str, file_ext: str) -> str:
    """
    파일에서 텍스트를 추출합니다.

    Args:
        file_path: 파일 경로
        file_ext: 파일 확장자 (점 없이, 예: "pdf")

    Returns:
        추출된 텍스트
    """
    if file_ext == "pdf":
        return await _extract_pdf(file_path)
    elif file_ext == "docx":
        return await _extract_docx(file_path)
    elif file_ext in ("txt", "md", "csv"):
        return await _extract_text(file_path)
    else:
        raise ValueError(f"지원하지 않는 파일 형식: {file_ext}")


async def _extract_pdf(file_path: str) -> str:
    """PDF에서 텍스트 추출"""
    from pypdf import PdfReader

    def _read() -> str:
        reader = PdfReader(file_path)
        texts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                texts.append(text)
        return "\n\n".join(texts)

    return await asyncio.to_thread(_read)


async def _extract_docx(file_path: str) -> str:
    """DOCX에서 텍스트 추출"""
    from docx import Document as DocxDocument

    def _read() -> str:
        doc = DocxDocument(file_path)
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

    return await asyncio.to_thread(_read)


async def _extract_text(file_path: str) -> str:
    """일반 텍스트 파일 읽기"""
    def _read() -> str:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            return f.read()

    return await asyncio.to_thread(_read)


# =============================================================================
# DemoPipeline
# =============================================================================


class DemoPipeline:
    """
    데모용 경량 RAG 파이프라인

    세션별 독립된 ChromaDB 컬렉션을 사용하여
    문서 인제스트, 벡터 검색, LLM 답변 생성을 수행합니다.

    사용 예시:
        pipeline = DemoPipeline(
            session_manager=manager,
            embedder=embedder,
            chroma_client=client,
            llm_client=llm_client,
        )

        result = await pipeline.ingest_document(session_id, file_bytes, "test.pdf")
        answer = await pipeline.query(session_id, "질문입니다")
    """

    def __init__(
        self,
        session_manager: DemoSessionManager,
        embedder: Any,  # GeminiEmbedder (IEmbedder Protocol)
        chroma_client: Any,  # chromadb.Client
        llm_client: Any,  # BaseLLMClient
    ) -> None:
        """
        파이프라인 초기화

        Args:
            session_manager: 세션 관리자
            embedder: 임베딩 모델 (embed_documents, embed_query 메서드 필요)
            chroma_client: ChromaDB 클라이언트 (인메모리)
            llm_client: LLM 클라이언트 (generate_text, stream_text 메서드 필요)
        """
        self._session_manager = session_manager
        self._embedder = embedder
        self._chroma_client = chroma_client
        self._llm_client = llm_client
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        logger.info("DemoPipeline 초기화 완료")

    # =========================================================================
    # 문서 인제스트
    # =========================================================================

    async def ingest_document(
        self,
        session_id: str,
        file_bytes: bytes,
        filename: str,
    ) -> dict[str, Any]:
        """
        파일을 세션의 ChromaDB 컬렉션에 인제스트합니다.

        Args:
            session_id: 세션 ID
            file_bytes: 파일 바이트
            filename: 원본 파일명

        Returns:
            {"chunks": int, "filename": str, "collection": str}

        Raises:
            ValueError: 세션 미존재, 파일 형식 미지원, 문서 수 제한 초과
        """
        # 세션 확인
        session = await self._session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"세션을 찾을 수 없습니다: {session_id}")

        # 파일명 경로 순회 방어 (basename만 추출)
        safe_filename = Path(filename).name
        file_ext = Path(safe_filename).suffix.lstrip(".").lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"지원하지 않는 파일 형식입니다: .{file_ext}. "
                f"지원 형식: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        # 임시 파일에 저장 후 텍스트 추출 (delete=False + finally 패턴으로 확실한 삭제)
        tmp = tempfile.NamedTemporaryFile(
            suffix=f".{file_ext}", delete=False
        )
        tmp_path = tmp.name
        try:
            tmp.write(file_bytes)
            tmp.flush()
            tmp.close()
            text = await extract_text_from_file(tmp_path, file_ext)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        if not text.strip():
            raise ValueError("파일에서 텍스트를 추출할 수 없습니다.")

        # 청킹
        chunks = self._splitter.split_text(text)
        if not chunks:
            raise ValueError("텍스트를 청크로 분할할 수 없습니다.")

        # 세션 문서 카운터 증가 (저장 전에 검증하여 데이터 불일치 방지)
        added = await self._session_manager.increment_document_count(
            session_id, safe_filename, len(chunks)
        )
        if not added:
            raise ValueError(
                f"세션당 최대 {self._session_manager.max_docs_per_session}개 "
                "문서만 업로드할 수 있습니다."
            )

        # 임베딩 생성
        raw_embeddings = await asyncio.to_thread(
            self._embedder.embed_documents, chunks
        )
        # 중첩 리스트 방어: 각 임베딩이 flat list[float]인지 확인
        embeddings = [
            emb[0] if isinstance(emb, list) and emb and isinstance(emb[0], list)
            else emb
            for emb in raw_embeddings
        ]

        # ChromaDB에 저장
        collection = self._chroma_client.get_or_create_collection(
            name=session.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        ids = [
            f"{session_id}_{hashlib.sha256(c.encode()).hexdigest()[:8]}_{i}"
            for i, c in enumerate(chunks)
        ]
        metadatas = [
            {
                "source": safe_filename,
                "chunk_index": i,
                "content": chunk[:500],  # 검색 결과 반환용 (500자 제한)
            }
            for i, chunk in enumerate(chunks)
        ]

        await asyncio.to_thread(
            collection.upsert,
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )

        logger.info(
            f"문서 인제스트 완료: {safe_filename} → {len(chunks)}개 청크 "
            f"(세션: {session_id[:8]})"
        )

        return {
            "chunks": len(chunks),
            "filename": safe_filename,
            "collection": session.collection_name,
        }

    # =========================================================================
    # 샘플 데이터 인제스트
    # =========================================================================

    async def ingest_sample_data(
        self,
        session_id: str,
        documents: list[dict[str, Any]],
    ) -> int:
        """
        샘플 데이터를 세션에 인제스트합니다.

        Args:
            session_id: 세션 ID
            documents: [{"id": str, "title": str, "content": str, "metadata": dict}]

        Returns:
            인제스트된 문서 수
        """
        session = await self._session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"세션을 찾을 수 없습니다: {session_id}")

        # title + content 병합
        texts = []
        ids = []
        metadatas = []
        for doc in documents:
            title = doc.get("title", "")
            content = doc.get("content", "")
            full_text = f"{title}\n\n{content}" if title else content

            if not full_text.strip():
                continue

            texts.append(full_text)
            ids.append(doc.get("id", uuid.uuid4().hex[:8]))
            metadatas.append({
                "source": "sample_data",
                "title": title[:200],
                "content": full_text[:500],
                "category": doc.get("metadata", {}).get("category", ""),
            })

        if not texts:
            return 0

        # 세션 문서 카운터 갱신 (샘플 데이터를 하나의 문서로 취급)
        await self._session_manager.increment_document_count(
            session_id, "sample_data", len(texts)
        )

        # 임베딩 생성
        raw_embeddings = await asyncio.to_thread(
            self._embedder.embed_documents, texts
        )
        # 중첩 리스트 방어: 각 임베딩이 flat list[float]인지 확인
        embeddings = [
            emb[0] if isinstance(emb, list) and emb and isinstance(emb[0], list)
            else emb
            for emb in raw_embeddings
        ]

        # ChromaDB에 저장
        collection = self._chroma_client.get_or_create_collection(
            name=session.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        await asyncio.to_thread(
            collection.upsert,
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

        logger.info(
            f"샘플 데이터 인제스트 완료: {len(texts)}개 문서 "
            f"(세션: {session_id[:8]})"
        )

        return len(texts)

    # =========================================================================
    # RAG 검색 + 답변 생성
    # =========================================================================

    async def query(
        self,
        session_id: str,
        question: str,
    ) -> dict[str, Any]:
        """
        RAG 질문 답변 (비스트리밍)

        Args:
            session_id: 세션 ID
            question: 사용자 질문

        Returns:
            {"answer": str, "sources": list, "chunks_used": int}

        Raises:
            ValueError: 세션 미존재
        """
        session = await self._session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"세션을 찾을 수 없습니다: {session_id}")

        # 검색
        sources = await self._search(session, question)

        # 컨텍스트 조합
        context = self._build_context(sources)

        # LLM 답변 생성
        prompt = RAG_USER_TEMPLATE.format(context=context, question=question)
        answer = await self._llm_client.generate_text(
            prompt=prompt,
            system_prompt=RAG_SYSTEM_PROMPT,
        )

        return {
            "answer": answer,
            "sources": [
                {
                    "content": s.get("content", "")[:200],
                    "source": s.get("source", ""),
                }
                for s in sources
            ],
            "chunks_used": len(sources),
        }

    async def stream_query(
        self,
        session_id: str,
        question: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        RAG 스트리밍 답변 생성

        SSE 이벤트 형식으로 yield합니다.

        Args:
            session_id: 세션 ID
            question: 사용자 질문

        Yields:
            {"event": str, "data": dict}
        """
        session = await self._session_manager.get_session(session_id)
        if session is None:
            raise ValueError(f"세션을 찾을 수 없습니다: {session_id}")

        # 검색
        sources = await self._search(session, question)

        # 메타데이터 이벤트
        yield {
            "event": "metadata",
            "data": {
                "session_id": session_id,
                "search_results": len(sources),
                "sources": [
                    {
                        "content": s.get("content", "")[:200],
                        "source": s.get("source", ""),
                    }
                    for s in sources
                ],
            },
        }

        # 컨텍스트 조합
        context = self._build_context(sources)
        prompt = RAG_USER_TEMPLATE.format(context=context, question=question)

        # 스트리밍 답변
        chunk_index = 0
        async for token in self._llm_client.stream_text(
            prompt=prompt,
            system_prompt=RAG_SYSTEM_PROMPT,
        ):
            yield {
                "event": "chunk",
                "data": {"token": token, "chunk_index": chunk_index},
            }
            chunk_index += 1

        # 완료 이벤트
        yield {
            "event": "done",
            "data": {
                "session_id": session_id,
                "total_chunks": chunk_index,
            },
        }

    # =========================================================================
    # 내부 메서드
    # =========================================================================

    async def _search(
        self, session: DemoSession, query: str
    ) -> list[dict[str, Any]]:
        """ChromaDB에서 유사 문서 검색"""
        # 쿼리 임베딩
        raw_query_embedding = await asyncio.to_thread(
            self._embedder.embed_query, query
        )
        # 중첩 리스트 방어
        query_embedding = (
            raw_query_embedding[0]
            if isinstance(raw_query_embedding, list)
            and raw_query_embedding
            and isinstance(raw_query_embedding[0], list)
            else raw_query_embedding
        )

        # ChromaDB 컬렉션 검색
        try:
            collection = self._chroma_client.get_collection(
                name=session.collection_name
            )
        except Exception:
            logger.warning(
                f"컬렉션을 찾을 수 없습니다: {session.collection_name}"
            )
            return []

        results = await asyncio.to_thread(
            collection.query,
            query_embeddings=[query_embedding],
            n_results=TOP_K,
            include=["documents", "metadatas", "distances"],
        )

        # 결과 변환
        sources: list[dict[str, Any]] = []
        if results and results.get("documents"):
            docs = results["documents"][0]
            metas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            for i, doc in enumerate(docs):
                meta = metas[i] if i < len(metas) else {}
                distance = distances[i] if i < len(distances) else 0.0
                sources.append({
                    "content": doc,
                    "source": meta.get("source", ""),
                    "title": meta.get("title", ""),
                    "distance": distance,
                })

        return sources

    def _build_context(self, sources: list[dict[str, Any]]) -> str:
        """검색 결과를 컨텍스트 문자열로 조합"""
        if not sources:
            return "관련 문서를 찾을 수 없습니다."

        parts = []
        for i, src in enumerate(sources, 1):
            source_name = src.get("source", "알 수 없는 출처")
            content = src.get("content", "")
            parts.append(f"[문서 {i}] ({source_name})\n{content}")

        return "\n\n---\n\n".join(parts)
