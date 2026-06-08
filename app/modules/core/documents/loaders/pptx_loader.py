"""PPTX Document Loader."""

import re
import zipfile
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from lxml import etree  # type: ignore[import-untyped]

from .....lib.logger import get_logger
from .base import DocumentLoaderStrategy

logger = get_logger(__name__)

_SLIDE_PATH_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")

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
            documents: list[Document] = []
            with zipfile.ZipFile(file_path) as archive:
                slide_names = self._ordered_slide_names(archive)
                if not slide_names:
                    logger.warning(f"PPTX has no slides: {file_path.name}")
                    return []

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

                    if not slide_text:
                        continue

                    documents.append(
                        Document(
                            page_content=f"슬라이드 {slide_number}\n{slide_text}",
                            metadata={"slide_number": slide_number},
                        )
                    )

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
