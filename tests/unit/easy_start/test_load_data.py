"""
easy_start 데이터 로드 스크립트 단위 테스트

ChromaDB에 샘플 데이터를 올바르게 적재하는지 검증합니다.
"""


import pytest


class TestPrepareDocuments:
    """문서 준비 함수 테스트"""

    def test_returns_list_with_correct_fields(self):
        """
        샘플 데이터를 ChromaDB 형식으로 변환

        Given: sample_data.json의 문서 1개
        When: prepare_documents() 호출
        Then: id, content, metadata 필드를 가진 리스트 반환
        """
        from easy_start.load_data import prepare_documents

        raw_docs = [
            {
                "id": "faq-001",
                "title": "RAG 시스템이란?",
                "content": "RAG는 검색 증강 생성 기술입니다.",
                "metadata": {"category": "기술 소개", "tags": ["RAG"]},
            }
        ]

        result = prepare_documents(raw_docs)

        assert len(result) == 1
        assert result[0]["id"] == "faq-001"
        assert "RAG 시스템이란?" in result[0]["content"]
        assert "RAG는 검색 증강 생성" in result[0]["content"]
        assert result[0]["metadata"]["category"] == "기술 소개"
        assert result[0]["metadata"]["source"] == "quickstart_sample"

    def test_merges_title_and_content(self):
        """
        title + content를 합쳐서 content 필드 생성

        Given: title과 content가 별도인 문서
        When: prepare_documents() 호출
        Then: "title\n\ncontent" 형식으로 병합
        """
        from easy_start.load_data import prepare_documents

        raw_docs = [
            {
                "id": "test-001",
                "title": "제목",
                "content": "본문 내용",
                "metadata": {"category": "테스트"},
            }
        ]

        result = prepare_documents(raw_docs)
        assert result[0]["content"] == "제목\n\n본문 내용"

    def test_empty_list(self):
        """
        빈 문서 리스트 처리

        Given: 빈 리스트
        When: prepare_documents() 호출
        Then: 빈 리스트 반환
        """
        from easy_start.load_data import prepare_documents

        result = prepare_documents([])
        assert result == []

    def test_skips_documents_without_id(self):
        """
        id가 없는 문서는 건너뜀

        Given: id 필드가 없는 문서
        When: prepare_documents() 호출
        Then: 해당 문서 스킵
        """
        from easy_start.load_data import prepare_documents

        raw_docs = [
            {"title": "제목", "content": "내용"},  # id 없음
            {"id": "ok-001", "title": "정상", "content": "정상 문서"},
        ]

        result = prepare_documents(raw_docs)
        assert len(result) == 1
        assert result[0]["id"] == "ok-001"

    def test_skips_documents_without_content(self):
        """
        content가 없는 문서는 건너뜀

        Given: content 필드가 없는 문서
        When: prepare_documents() 호출
        Then: 해당 문서 스킵
        """
        from easy_start.load_data import prepare_documents

        raw_docs = [
            {"id": "no-content", "title": "제목만"},
        ]

        result = prepare_documents(raw_docs)
        assert result == []

    def test_handles_missing_metadata(self):
        """
        metadata가 없는 문서도 정상 처리

        Given: metadata 필드가 없는 문서
        When: prepare_documents() 호출
        Then: 기본 metadata로 변환
        """
        from easy_start.load_data import prepare_documents

        raw_docs = [
            {"id": "no-meta", "title": "제목", "content": "내용"},
        ]

        result = prepare_documents(raw_docs)
        assert len(result) == 1
        assert result[0]["metadata"]["source"] == "quickstart_sample"
        assert result[0]["metadata"]["file_type"] == "FAQ"  # 기본값

    def test_handles_missing_title(self):
        """
        title이 없는 문서도 content만으로 처리

        Given: title 없는 문서
        When: prepare_documents() 호출
        Then: content만으로 full_content 구성
        """
        from easy_start.load_data import prepare_documents

        raw_docs = [
            {"id": "no-title", "content": "본문만 있음"},
        ]

        result = prepare_documents(raw_docs)
        assert len(result) == 1
        assert result[0]["content"] == "본문만 있음"


class TestBm25Index:
    """BM25 인덱스 관련 테스트"""

    def test_build_bm25_index(self):
        """
        BM25 인덱스 구축 후 검색 가능

        Given: 문서 리스트
        When: build_bm25_index() 호출
        Then: 검색 가능한 BM25Index 인스턴스 반환
        """
        pytest.importorskip("kiwipiepy")
        pytest.importorskip("rank_bm25")

        from easy_start.load_data import build_bm25_index

        docs = [
            {"id": "1", "content": "RAG 시스템 설치 가이드", "metadata": {}},
            {"id": "2", "content": "채팅 API 사용법", "metadata": {}},
        ]

        index = build_bm25_index(docs)

        assert hasattr(index, "search")
        results = index.search("설치", top_k=2)
        assert len(results) > 0

    def test_save_and_load_bm25_index(self, tmp_path):
        """
        BM25 인덱스 저장/로드 왕복 테스트

        Given: 구축된 BM25 인덱스
        When: save → load 수행
        Then: 로드된 인덱스로 동일한 검색 결과 반환
        """
        pytest.importorskip("kiwipiepy")
        pytest.importorskip("rank_bm25")

        from easy_start.load_data import (
            build_bm25_index,
            load_bm25_index,
            save_bm25_index,
        )

        docs = [
            {"id": "1", "content": "RAG 시스템 설치 가이드", "metadata": {}},
            {"id": "2", "content": "채팅 API 사용법", "metadata": {}},
        ]

        # 구축 → 저장
        index = build_bm25_index(docs)
        index_path = str(tmp_path / "test_bm25.pkl")
        save_bm25_index(index, index_path)

        # 로드 → 검색
        loaded = load_bm25_index(index_path)
        assert hasattr(loaded, "search")
        results = loaded.search("설치", top_k=2)
        assert len(results) > 0


class TestLoadSafety:
    """easy-start 로더의 비파괴 기본 동작 테스트"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("reset", "expected_reset_calls"),
        [
            (False, 0),
            (True, 1),
        ],
    )
    async def test_main_resets_chroma_only_when_explicit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        reset: bool,
        expected_reset_calls: int,
    ) -> None:
        from app.modules.core.embedding import local_embedder
        from easy_start import load_data

        sample_path = tmp_path / "sample_data.json"
        sample_path.write_text(
            """
            {
              "documents": [
                {
                  "id": "faq-001",
                  "title": "제목",
                  "content": "본문",
                  "metadata": {"category": "FAQ"}
                }
              ]
            }
            """,
            encoding="utf-8",
        )

        reset_calls: list[bool] = []
        loaded_counts: list[int] = []

        class FakeEmbedder:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.1, 0.2] for _ in texts]

        async def fake_load_to_chroma(docs, embeddings, **kwargs) -> int:
            loaded_counts.append(len(docs))
            return len(docs)

        monkeypatch.setattr(load_data, "_resolve_sample_data_path", lambda: sample_path)
        monkeypatch.setattr(load_data, "BM25_INDEX_PATH", str(tmp_path / "bm25.pkl"))
        monkeypatch.setattr(
            load_data,
            "build_load_manifest",
            lambda sample_data_path, document_count: {
                "sample_data_path": str(sample_data_path),
                "document_count": document_count,
            },
        )
        monkeypatch.setattr(local_embedder, "LocalEmbedder", FakeEmbedder)
        monkeypatch.setattr(load_data, "reset_chroma_collection", lambda: reset_calls.append(True))
        monkeypatch.setattr(load_data, "load_to_chroma", fake_load_to_chroma)
        monkeypatch.setattr(load_data, "build_bm25_index", lambda docs: object())
        monkeypatch.setattr(load_data, "save_bm25_index", lambda index: None)
        monkeypatch.setattr(load_data, "save_manifest", lambda manifest: None)

        await load_data.main(reset=reset)

        assert len(reset_calls) == expected_reset_calls
        assert loaded_counts == [1]

    def test_parse_args_accepts_explicit_reset(self) -> None:
        from easy_start.load_data import parse_args

        args = parse_args(["--reset"])

        assert args.reset is True

    def test_cli_allows_env_reset_when_cli_reset_absent(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from easy_start import load_data

        calls: list[bool | None] = []
        monkeypatch.setattr(load_data.asyncio, "run", lambda coro: None)
        monkeypatch.setattr(load_data, "main", lambda reset=None: calls.append(reset))

        load_data.cli([])

        assert calls == [None]

    def test_reset_chroma_collection_raises_on_unexpected_delete_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from easy_start import load_data

        class FakeClient:
            def delete_collection(self, collection_name: str) -> None:
                raise PermissionError("permission denied")

        monkeypatch.setattr(
            "chromadb.PersistentClient",
            lambda path, settings: FakeClient(),
        )

        with pytest.raises(RuntimeError, match="Chroma 컬렉션 초기화 실패"):
            load_data.reset_chroma_collection()
