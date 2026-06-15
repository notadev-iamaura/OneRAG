// PDF 인용 좌표 변환 유틸 단위 테스트(#55).
// bbox→%/px 변환, 페이지 필터, 비정상 입력 거부(graceful), 좌표 클램핑을 검증한다.
import { describe, expect, it } from 'vitest';
import { buildPdfCitationBoxes, buildPdfCitationRenderBoxes } from '../pdfCitationGeometry';

describe('buildPdfCitationBoxes', () => {
    it('선택한 페이지의 유한 bbox를 퍼센트(%) 좌표로 변환한다', () => {
        const boxes = buildPdfCitationBoxes(
            [
                {
                    region_id: 'paragraph-0',
                    region_type: 'paragraph',
                    page: 2,
                    bbox: [60, 80, 540, 400],
                },
                {
                    region_id: 'other-page',
                    region_type: 'paragraph',
                    page: 1,
                    bbox: [0, 0, 100, 100],
                },
            ],
            { width: 600, height: 800 },
            2,
        );

        // 페이지 2의 영역만 남고, %로 변환되어야 한다.
        expect(boxes).toEqual([
            {
                key: 'paragraph-0-0',
                label: 'paragraph-0',
                leftPct: 10,
                topPct: 10,
                widthPct: 80,
                heightPct: 40,
                confidence: undefined,
            },
        ]);
    });

    it('비정상 bbox/페이지 크기는 빈 배열로 거부한다(graceful)', () => {
        // bbox에 NaN 포함 → 거부
        expect(buildPdfCitationBoxes(
            [{ region_id: 'bad', bbox: [0, Number.NaN, 1, 1] }],
            { width: 600, height: 800 },
            null,
        )).toEqual([]);

        // 페이지 폭 0 → 거부(변환 불가)
        expect(buildPdfCitationBoxes(
            [{ region_id: 'bad', bbox: [0, 0, 1, 1] }],
            { width: 0, height: 800 },
            null,
        )).toEqual([]);

        // page_dimensions 미제공(백엔드 bbox 미지원) → 거부 → 뷰어가 graceful하게 생략
        expect(buildPdfCitationBoxes(
            [{ region_id: 'ok', bbox: [0, 0, 1, 1] }],
            null,
            null,
        )).toEqual([]);
    });

    it('table_index로 라벨을 생성하고 면적 0 박스는 제외한다', () => {
        const boxes = buildPdfCitationBoxes(
            [
                { table_index: 3, bbox: [10, 10, 110, 60] },
                // x1 <= x0 → 면적 0 → 제외
                { region_id: 'zero-area', bbox: [50, 50, 50, 90] },
            ],
            { width: 200, height: 400 },
            null,
        );

        expect(boxes).toHaveLength(1);
        expect(boxes[0]?.label).toBe('table-3');
    });
});

describe('buildPdfCitationRenderBoxes', () => {
    it('인용 박스를 렌더된 PDF 페이지 픽셀(px) 좌표로 투영한다', () => {
        const boxes = buildPdfCitationRenderBoxes(
            [{
                region_id: 'paragraph-0',
                region_type: 'paragraph',
                page: 1,
                bbox: [60, 80, 540, 400],
                confidence: 0.9,
            }],
            { width: 600, height: 800 },
            300,
            400,
            1,
        );

        expect(boxes).toEqual([
            {
                key: 'paragraph-0-0',
                label: 'paragraph-0',
                leftPct: 10,
                topPct: 10,
                widthPct: 80,
                heightPct: 40,
                leftPx: 30,
                topPx: 40,
                widthPx: 240,
                heightPx: 160,
                confidence: 0.9,
            },
        ]);
    });

    it('모든 박스를 렌더 영역 경계 안으로 클램핑한다', () => {
        const boxes = buildPdfCitationRenderBoxes(
            [
                { region_id: 'page', region_type: 'page', page: 2, bbox: [0, 0, 595, 842] },
                { region_id: 'title', region_type: 'paragraph', page: 2, bbox: [72, 90, 520, 122] },
                { region_type: 'table', page: 2, table_index: 0, bbox: [72, 150, 520, 265] },
                // 다른 페이지 → 제외
                { region_id: 'wrong-page', region_type: 'paragraph', page: 3, bbox: [0, 0, 595, 842] },
            ],
            { width: 595, height: 842 },
            297.5,
            421,
            2,
        );

        expect(boxes).toHaveLength(3);
        for (const box of boxes) {
            expect(box.leftPx).toBeGreaterThanOrEqual(0);
            expect(box.topPx).toBeGreaterThanOrEqual(0);
            expect(box.leftPx + box.widthPx).toBeLessThanOrEqual(297.5 + 1e-6);
            expect(box.topPx + box.heightPx).toBeLessThanOrEqual(421 + 1e-6);
            expect(box.widthPx).toBeGreaterThan(0);
            expect(box.heightPx).toBeGreaterThan(0);
        }
    });

    it('가로(landscape) 페이지도 세로 가정 없이 처리한다', () => {
        const boxes = buildPdfCitationRenderBoxes(
            [{
                region_id: 'paragraph-route',
                region_type: 'paragraph',
                page: 3,
                bbox: [260, 130, 690, 225],
            }],
            { width: 842, height: 595 },
            421,
            297.5,
            3,
        );

        expect(boxes).toHaveLength(1);
        const box = boxes[0];
        expect(box).toBeDefined();
        if (!box) throw new Error('expected one citation box');
        expect(box.label).toBe('paragraph-route');
        expect(box.leftPx).toBeCloseTo(130);
        expect(box.topPx).toBeCloseTo(65);
        expect(box.widthPx).toBeCloseTo(215);
        expect(box.heightPx).toBeCloseTo(47.5);
    });

    it('비유한 렌더 크기는 빈 배열로 거부한다', () => {
        expect(buildPdfCitationRenderBoxes(
            [{ region_id: 'bad', bbox: [0, 0, 1, 1] }],
            { width: 600, height: 800 },
            Number.NaN,
            400,
            null,
        )).toEqual([]);
    });
});
