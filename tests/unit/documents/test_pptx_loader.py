"""PPTXLoader 단위 테스트.

검증 대상:
- #6: presentation.xml sldIdLst 순서를 따른 슬라이드 정렬(+ rels 부재 시 파일명 폴백)
- #11: 한 슬라이드가 손상돼도 전체 로드가 중단되지 않고 해당 슬라이드만 건너뜀
- #33: 한 문단 내 런(run)은 이어붙이고 문단 경계는 줄바꿈으로 분리
- #1: 발표자 노트(notesSlide) 텍스트 추출 및 슬라이드 매핑(_rels 우선, 파일명 폴백)
"""

import zipfile
from pathlib import Path

import pytest

from app.modules.core.documents.loaders.pptx_loader import PPTXLoader

_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _slide_xml(paragraphs: list[list[str]]) -> bytes:
    """문단별 런 목록으로 슬라이드 XML 생성. paragraphs=[[run, run], [run]]"""
    body = ""
    for runs in paragraphs:
        run_xml = "".join(f"<a:r><a:t>{r}</a:t></a:r>" for r in runs)
        body += f"<a:p>{run_xml}</a:p>"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<p:sld xmlns:p="{_NS_P}" xmlns:a="{_NS_A}"><p:cSld><p:spTree>'
        f"{body}"
        f"</p:spTree></p:cSld></p:sld>"
    ).encode()


def _presentation_xml(slide_id_to_rid: list[tuple[int, str]]) -> bytes:
    ids = "".join(
        f'<p:sldId id="{sid}" r:id="{rid}"/>' for sid, rid in slide_id_to_rid
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<p:presentation xmlns:p="{_NS_P}" xmlns:r="{_NS_R}">'
        f"<p:sldIdLst>{ids}</p:sldIdLst></p:presentation>"
    ).encode()


def _rels_xml(rid_to_target: list[tuple[str, str]]) -> bytes:
    rels = "".join(
        f'<Relationship Id="{rid}" Type="http://x" Target="{tgt}"/>'
        for rid, tgt in rid_to_target
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{_NS_REL}">{rels}</Relationships>'
    ).encode()


def _write_pptx(tmp_path: Path, entries: dict[str, bytes]) -> Path:
    pptx_path = tmp_path / "deck.pptx"
    with zipfile.ZipFile(pptx_path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return pptx_path


@pytest.mark.asyncio
async def test_slide_order_follows_sldidlst(tmp_path: Path) -> None:
    # 파일명은 slide1=alpha, slide2=bravo이지만 sldIdLst는 slide2 -> slide1 순서
    entries = {
        "ppt/slides/slide1.xml": _slide_xml([["alpha"]]),
        "ppt/slides/slide2.xml": _slide_xml([["bravo"]]),
        "ppt/presentation.xml": _presentation_xml([(256, "rId2"), (257, "rId1")]),
        "ppt/_rels/presentation.xml.rels": _rels_xml(
            [("rId1", "slides/slide1.xml"), ("rId2", "slides/slide2.xml")]
        ),
    }
    docs = await PPTXLoader().load(_write_pptx(tmp_path, entries))

    assert len(docs) == 2
    # 시각적 순서(sldIdLst)대로 bravo가 먼저, alpha가 나중
    assert "bravo" in docs[0].page_content
    assert docs[0].metadata["slide_number"] == 1
    assert "alpha" in docs[1].page_content
    assert docs[1].metadata["slide_number"] == 2


@pytest.mark.asyncio
async def test_slide_order_fallback_when_rels_missing(tmp_path: Path) -> None:
    entries = {
        "ppt/slides/slide1.xml": _slide_xml([["first"]]),
        "ppt/slides/slide2.xml": _slide_xml([["second"]]),
    }
    docs = await PPTXLoader().load(_write_pptx(tmp_path, entries))

    assert [d.metadata["slide_number"] for d in docs] == [1, 2]
    assert "first" in docs[0].page_content
    assert "second" in docs[1].page_content


@pytest.mark.asyncio
async def test_one_malformed_slide_is_skipped_not_fatal(tmp_path: Path) -> None:
    entries = {
        "ppt/slides/slide1.xml": _slide_xml([["good1"]]),
        "ppt/slides/slide2.xml": b"<broken-xml without close",
        "ppt/slides/slide3.xml": _slide_xml([["good3"]]),
    }
    docs = await PPTXLoader().load(_write_pptx(tmp_path, entries))

    # 손상된 slide2만 건너뛰고 slide1/slide3은 정상 추출
    contents = " ".join(d.page_content for d in docs)
    assert "good1" in contents
    assert "good3" in contents
    assert len(docs) == 2


@pytest.mark.asyncio
async def test_runs_within_paragraph_are_concatenated(tmp_path: Path) -> None:
    entries = {
        "ppt/slides/slide1.xml": _slide_xml([["해당 ", "문장입니다"], ["둘째문단"]]),
    }
    docs = await PPTXLoader().load(_write_pptx(tmp_path, entries))

    assert len(docs) == 1
    content = docs[0].page_content
    # 한 문단 내 런은 이어붙어 한 줄
    assert "해당 문장입니다" in content
    # 문단 경계는 줄바꿈으로 분리
    assert "해당 문장입니다\n둘째문단" in content


@pytest.mark.asyncio
async def test_bad_zip_raises_valueerror(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pptx"
    bad.write_bytes(b"this is not a zip archive")

    with pytest.raises(ValueError):
        await PPTXLoader().load(bad)


# ============================================================
# #1: 발표자 노트(notesSlide) 추출
# ============================================================
@pytest.mark.asyncio
async def test_notes_merged_into_slide_via_rels(tmp_path: Path) -> None:
    """notesSlide의 _rels가 부모 슬라이드를 가리키면 해당 슬라이드 본문에 노트를 합친다."""
    entries = {
        "ppt/slides/slide1.xml": _slide_xml([["본문내용"]]),
        "ppt/notesSlides/notesSlide1.xml": _slide_xml([["발표자 노트입니다"]]),
        # notesSlide1 → slide1 매핑(_rels의 Type이 .../slide)
        "ppt/notesSlides/_rels/notesSlide1.xml.rels": _rels_xml(
            [
                (
                    "rId1",
                    "../slides/slide1.xml",
                )
            ]
        ),
    }
    docs = await PPTXLoader().load(_write_pptx(tmp_path, entries))

    assert len(docs) == 1
    content = docs[0].page_content
    assert "본문내용" in content
    assert "발표자 노트입니다" in content
    assert docs[0].metadata.get("has_notes") is True


@pytest.mark.asyncio
async def test_notes_fallback_to_filename_index_when_rels_missing(tmp_path: Path) -> None:
    """_rels가 없으면 파일명 인덱스(notesSlideN ↔ slideN)로 폴백 매핑한다."""
    entries = {
        "ppt/slides/slide1.xml": _slide_xml([["첫슬라이드"]]),
        "ppt/slides/slide2.xml": _slide_xml([["둘째슬라이드"]]),
        "ppt/notesSlides/notesSlide2.xml": _slide_xml([["둘째 노트"]]),
    }
    docs = await PPTXLoader().load(_write_pptx(tmp_path, entries))

    assert len(docs) == 2
    # slide2에만 노트가 붙어야 한다
    assert "둘째 노트" not in docs[0].page_content
    assert "둘째 노트" in docs[1].page_content
    assert docs[1].metadata.get("has_notes") is True


@pytest.mark.asyncio
async def test_slide_without_notes_keeps_original_output(tmp_path: Path) -> None:
    """노트 없는 슬라이드는 기존 출력과 메타를 그대로 유지한다(회귀 방지)."""
    entries = {
        "ppt/slides/slide1.xml": _slide_xml([["노트없음"]]),
    }
    docs = await PPTXLoader().load(_write_pptx(tmp_path, entries))

    assert len(docs) == 1
    assert docs[0].page_content == "슬라이드 1\n노트없음"
    assert "has_notes" not in docs[0].metadata or docs[0].metadata["has_notes"] is False
