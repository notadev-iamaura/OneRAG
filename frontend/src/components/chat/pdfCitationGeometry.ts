// PDF 인용 bbox 좌표 변환 유틸(#55).
//
// 백엔드가 제공한 CitationRegion(페이지 좌표계 bbox)을 PageDimensions(페이지 원본 크기)와 함께
// 퍼센트(%) 및 렌더 픽셀(px) 좌표로 변환한다.
// 모든 좌표는 언어/도메인 중립이며, 값이 비정상이면 안전하게 빈 배열을 반환한다(graceful).
import { CitationRegion, PageDimensions } from '../../types/chat';

// %(상대) 좌표 기반 하이라이트 박스.
export interface PdfCitationBox {
    key: string;
    label: string;
    leftPct: number;
    topPct: number;
    widthPct: number;
    heightPct: number;
    confidence?: number | null;
}

// 렌더된 캔버스 크기 기준 px(절대) 좌표를 포함한 박스.
export interface PdfCitationRenderBox extends PdfCitationBox {
    leftPx: number;
    topPx: number;
    widthPx: number;
    heightPx: number;
}

// 유한한 숫자인지 검사.
const isFiniteNumber = (value: unknown): value is number => (
    typeof value === 'number' && Number.isFinite(value)
);

// 값을 [min, max] 범위로 클램핑.
const clamp = (value: number, min: number, max: number): number => (
    Math.min(Math.max(value, min), max)
);

// 영역에 표시할 라벨을 결정(region_id > region_type > table-N > region-N 순).
const regionLabel = (region: CitationRegion, index: number): string => (
    region.region_id
    || region.region_type
    || (region.table_index != null ? `table-${region.table_index}` : `region-${index + 1}`)
);

/**
 * buildPdfCitationBoxes - bbox를 페이지 크기 대비 %(상대) 좌표로 변환한다.
 *
 * @param regions - 백엔드가 제공한 인용 영역 목록
 * @param pageDimensions - 페이지 원본 크기(없거나 비정상이면 빈 배열 반환 → graceful)
 * @param page - 특정 페이지로 필터링(미지정 시 전체)
 */
export const buildPdfCitationBoxes = (
    regions: CitationRegion[],
    pageDimensions: PageDimensions | null | undefined,
    page?: number | null,
): PdfCitationBox[] => {
    const pageWidth = pageDimensions?.width;
    const pageHeight = pageDimensions?.height;
    // 페이지 크기가 없으면 변환 불가 → 빈 배열(하이라이트 생략).
    if (!isFiniteNumber(pageWidth) || !isFiniteNumber(pageHeight) || pageWidth <= 0 || pageHeight <= 0) {
        return [];
    }

    return regions.flatMap((region, index) => {
        // 페이지 필터: 요청 페이지와 영역 페이지가 다르면 제외.
        if (page != null && region.page != null && region.page !== page) {
            return [];
        }
        const bbox = region.bbox;
        // bbox가 [x0,y0,x1,y1] 형태의 유한 숫자 4개가 아니면 제외(graceful).
        if (!Array.isArray(bbox) || bbox.length !== 4 || !bbox.every(isFiniteNumber)) {
            return [];
        }

        // 좌표를 정규화(min/max 보정) 후 페이지 범위로 클램핑.
        const x0 = clamp(Math.min(bbox[0], bbox[2]), 0, pageWidth);
        const y0 = clamp(Math.min(bbox[1], bbox[3]), 0, pageHeight);
        const x1 = clamp(Math.max(bbox[0], bbox[2]), 0, pageWidth);
        const y1 = clamp(Math.max(bbox[1], bbox[3]), 0, pageHeight);
        // 면적이 0 이하인 박스는 제외.
        if (x1 <= x0 || y1 <= y0) {
            return [];
        }

        return [{
            key: `${region.region_id ?? region.region_type ?? 'region'}-${index}`,
            label: regionLabel(region, index),
            leftPct: (x0 / pageWidth) * 100,
            topPct: (y0 / pageHeight) * 100,
            widthPct: ((x1 - x0) / pageWidth) * 100,
            heightPct: ((y1 - y0) / pageHeight) * 100,
            confidence: region.confidence,
        }];
    });
};

/**
 * buildPdfCitationRenderBoxes - %(상대) 박스를 실제 렌더 캔버스 크기 기준 px(절대) 좌표로 변환한다.
 *
 * @param renderedWidth - 렌더된 캔버스 폭(비정상이면 빈 배열 반환)
 * @param renderedHeight - 렌더된 캔버스 높이(비정상이면 빈 배열 반환)
 */
export const buildPdfCitationRenderBoxes = (
    regions: CitationRegion[],
    pageDimensions: PageDimensions | null | undefined,
    renderedWidth: number,
    renderedHeight: number,
    page?: number | null,
): PdfCitationRenderBox[] => {
    if (
        !isFiniteNumber(renderedWidth)
        || !isFiniteNumber(renderedHeight)
        || renderedWidth <= 0
        || renderedHeight <= 0
    ) {
        return [];
    }

    return buildPdfCitationBoxes(regions, pageDimensions, page).map((box) => ({
        ...box,
        leftPx: (box.leftPct / 100) * renderedWidth,
        topPx: (box.topPct / 100) * renderedHeight,
        widthPx: (box.widthPct / 100) * renderedWidth,
        heightPx: (box.heightPct / 100) * renderedHeight,
    }));
};
