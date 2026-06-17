"""PPTX Document Loader."""

import re
import zipfile
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from lxml import etree  # type: ignore[import-untyped]

from .....lib.logger import get_logger
from .base import DocumentLoaderStrategy
from .labels import get_loader_labels

logger = get_logger(__name__)

_SLIDE_PATH_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
# 발표자 노트 파트 경로(#1): ppt/notesSlides/notesSlideN.xml
_NOTES_PATH_RE = re.compile(r"^ppt/notesSlides/notesSlide(\d+)\.xml$")

# OpenXML 네임스페이스
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"  # drawingml(텍스트)
_NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"  # presentation
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_TEXT_TAG = f"{{{_NS_A}}}t"

_PRES_PATH = "ppt/presentation.xml"
_PRES_RELS_PATH = "ppt/_rels/presentation.xml.rels"
_MAX_SLIDE_XML_BYTES = 5 * 1024 * 1024


class PPTXLoader(DocumentLoaderStrategy):
    """PowerPoint `.pptx` presentation loader.

    The loader extracts text directly from Office Open XML slide files. It does
    not require `python-pptx`, and it avoids network/entity expansion while
    parsing slide XML. Slides are ordered by the presentation's `sldIdLst`
    (the visual order), falling back to the filename order when relationship
    metadata is missing/corrupt. A single malformed slide is skipped rather than
    aborting the whole presentation.
    """

    @property
    def supported_extensions(self) -> list[str]:
        return [".pptx", ".PPTX"]

    async def load(self, file_path: Path) -> list[Document]:
        """Load text from each non-empty slide in a PPTX file (visual order)."""
        try:
            labels = get_loader_labels()
            documents: list[Document] = []
            with zipfile.ZipFile(file_path) as archive:
                slide_names = self._ordered_slide_names(archive)
                if not slide_names:
                    logger.warning(f"PPTX has no slides: {file_path.name}")
                    return []

                # #1: 슬라이드 경로 → 발표자 노트 경로 매핑(_rels 우선, 파일명 인덱스 폴백)
                slide_to_notes = self._slide_to_notes_map(archive)

                for slide_number, slide_name in enumerate(slide_names, start=1):
                    try:
                        info = archive.getinfo(slide_name)
                        if info.file_size > _MAX_SLIDE_XML_BYTES:
                            # ✅ #11: 거대한 슬라이드는 전체 로드를 막지 않고 건너뛴다.
                            logger.warning(
                                f"Skipping oversized PPTX slide {slide_name} "
                                f"({info.file_size} bytes) in {file_path.name}"
                            )
                            continue
                        slide_text = self._extract_slide_text(archive.read(slide_name))
                    except Exception as exc:  # noqa: BLE001 - 슬라이드 단위 실패 격리(#11)
                        logger.warning(
                            f"Skipping malformed PPTX slide {slide_name} "
                            f"in {file_path.name}: {exc}"
                        )
                        continue

                    # #1: 해당 슬라이드의 발표자 노트를 동일한 오버사이즈/실패격리 가드로 추출.
                    notes_text = self._extract_notes_text(
                        archive, slide_to_notes.get(slide_name), file_path.name
                    )

                    if not slide_text and not notes_text:
                        continue

                    content = f"{labels['slide']} {slide_number}\n{slide_text}".rstrip()
                    metadata: dict[str, Any] = {"slide_number": slide_number}
                    if notes_text:
                        # 화자 스크립트/상세 설명을 본문에 합쳐 검색 대상에 포함한다.
                        content = f"{content}\n\n[{labels['notes']}]\n{notes_text}"
                        metadata["has_notes"] = True

                    documents.append(Document(page_content=content, metadata=metadata))

            if not documents:
                logger.warning(f"PPTX contains no extractable text: {file_path.name}")
                return []

            logger.info(f"PPTX loaded: {len(documents)} slides from {file_path.name}")
            return documents
        except zipfile.BadZipFile as e:
            logger.error(f"PPTX loading failed for {file_path}: invalid zip")
            raise ValueError("Failed to load PPTX file: invalid PowerPoint package") from e
        except Exception as e:
            logger.error(f"PPTX loading failed for {file_path}: {e}")
            raise ValueError(f"Failed to load PPTX file: {e}") from e

    @staticmethod
    def _safe_parse(xml_bytes: bytes) -> Any:
        """PPTX 내부 XML을 안전 파서로 파싱(외부 엔티티/네트워크/거대 트리 차단)."""
        parser = etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            recover=False,
            huge_tree=False,
        )
        return etree.fromstring(xml_bytes, parser=parser)

    @classmethod
    def _ordered_slide_names(cls, archive: zipfile.ZipFile) -> list[str]:
        """presentation.xml의 sldIdLst 순서를 따라 슬라이드 파일 경로를 정렬해 반환(#6).

        해석 실패(파일 누락/손상) 시 파일명 정수 정렬로 안전하게 폴백한다.
        """
        names = set(archive.namelist())
        if _PRES_PATH in names and _PRES_RELS_PATH in names:
            try:
                pres = cls._safe_parse(archive.read(_PRES_PATH))
                rels = cls._safe_parse(archive.read(_PRES_RELS_PATH))
                # rId -> 슬라이드 파트 경로 매핑 구성
                rid_to_target: dict[str, str] = {}
                for rel in rels.iter(f"{{{_NS_REL}}}Relationship"):
                    rid = rel.get("Id")
                    target = rel.get("Target")
                    if rid and target:
                        # Target은 ppt/ 기준 상대경로(예: slides/slide1.xml)
                        norm = target.lstrip("/")
                        if not norm.startswith("ppt/"):
                            norm = f"ppt/{norm}"
                        rid_to_target[rid] = norm
                ordered: list[str] = []
                for sld_id in pres.iter(f"{{{_NS_P}}}sldId"):
                    rid = sld_id.get(f"{{{_NS_R}}}id")
                    target = rid_to_target.get(rid or "")
                    if target and target in names:
                        ordered.append(target)
                if ordered:
                    return ordered
            except Exception as exc:  # noqa: BLE001 - 폴백을 위해 광범위 포착
                logger.warning(
                    f"PPTX slide order via presentation.xml failed, falling back: {exc}"
                )

        # 폴백: 파일명 정수 정렬
        infos = [(int(m.group(1)), name) for name in names if (m := _SLIDE_PATH_RE.match(name))]
        return [name for _, name in sorted(infos, key=lambda item: item[0])]

    @classmethod
    def _slide_to_notes_map(cls, archive: zipfile.ZipFile) -> dict[str, str]:
        """슬라이드 경로 → 발표자 노트 경로 매핑을 구성한다(#1).

        매핑 전략:
            1) _rels 우선: ppt/notesSlides/_rels/notesSlideN.xml.rels에서 Type이
               '.../slide'로 끝나는 Relationship의 Target(부모 슬라이드)을 정규화해 매핑.
            2) 폴백: rels가 없거나 해석 실패하면 파일명 인덱스(notesSlideN ↔ slideN)로 매핑.

        Returns:
            {슬라이드경로(ppt/slides/slideN.xml): 노트경로(ppt/notesSlides/notesSlideN.xml)}.
        """
        names = set(archive.namelist())
        notes_names = [name for name in names if _NOTES_PATH_RE.match(name)]
        if not notes_names:
            return {}

        mapping: dict[str, str] = {}
        for notes_name in notes_names:
            slide_target = cls._notes_parent_slide_via_rels(archive, notes_name, names)
            if slide_target is None:
                # 폴백: notesSlideN → slideN (파일명 인덱스)
                match = _NOTES_PATH_RE.match(notes_name)
                if match:
                    candidate = f"ppt/slides/slide{match.group(1)}.xml"
                    if candidate in names:
                        slide_target = candidate
            if slide_target is not None:
                mapping[slide_target] = notes_name
        return mapping

    @classmethod
    def _notes_parent_slide_via_rels(
        cls, archive: zipfile.ZipFile, notes_name: str, names: set[str]
    ) -> str | None:
        """notesSlide의 _rels에서 부모 슬라이드 경로를 해석한다(없으면 None)."""
        # ppt/notesSlides/notesSlideN.xml → ppt/notesSlides/_rels/notesSlideN.xml.rels
        base = notes_name.rsplit("/", 1)[-1]
        rels_path = f"ppt/notesSlides/_rels/{base}.rels"
        if rels_path not in names:
            return None
        try:
            rels = cls._safe_parse(archive.read(rels_path))
        except Exception as exc:  # noqa: BLE001 - 폴백을 위해 광범위 포착
            logger.warning(f"PPTX notes rels parse failed for {rels_path}: {exc}")
            return None
        for rel in rels.iter(f"{{{_NS_REL}}}Relationship"):
            rel_type = str(rel.get("Type") or "")
            target = rel.get("Target")
            if not target or not rel_type.endswith("/slide"):
                continue
            # Target은 보통 '../slides/slideN.xml' 형태의 상대경로
            norm: str = str(target).lstrip("/")
            if norm.startswith("../"):
                norm = norm[3:]
            if not norm.startswith("ppt/"):
                norm = f"ppt/{norm}"
            if norm in names:
                return norm
        return None

    @classmethod
    def _extract_notes_text(
        cls, archive: zipfile.ZipFile, notes_name: str | None, source_name: str
    ) -> str:
        """발표자 노트 XML에서 텍스트를 추출한다(슬라이드와 동일한 가드 적용) (#1).

        오버사이즈 가드 + 노트 단위 실패 격리를 적용하며, 실패 시 빈 문자열을 반환해
        슬라이드 본문 추출에는 영향을 주지 않는다.
        """
        if not notes_name:
            return ""
        try:
            info = archive.getinfo(notes_name)
            if info.file_size > _MAX_SLIDE_XML_BYTES:
                logger.warning(
                    f"Skipping oversized PPTX notes {notes_name} "
                    f"({info.file_size} bytes) in {source_name}"
                )
                return ""
            return cls._extract_slide_text(archive.read(notes_name))
        except Exception as exc:  # noqa: BLE001 - 노트 단위 실패 격리(슬라이드 본문 보존)
            logger.warning(
                f"Skipping malformed PPTX notes {notes_name} in {source_name}: {exc}"
            )
            return ""

    @classmethod
    def _extract_slide_text(cls, slide_xml: bytes) -> str:
        """슬라이드 XML에서 텍스트 추출.

        ✅ #33: a:p(문단) 경계는 줄바꿈, 문단 내 a:t(런)은 이어붙여 문장 분절을 방지한다.
        OpenXML에서 한 문단 내 런은 서식 경계로만 분리되므로 공백 없이 이어붙이면 원문 복원.
        """
        root = cls._safe_parse(slide_xml)
        paragraphs: list[str] = []
        for para in root.iter(f"{{{_NS_A}}}p"):
            runs = [str(t.text) for t in para.iter(_TEXT_TAG) if t.text and str(t.text).strip()]
            if runs:
                paragraphs.append("".join(runs).strip())
        return "\n".join(p for p in paragraphs if p)
