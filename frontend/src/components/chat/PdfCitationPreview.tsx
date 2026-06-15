// PDF 인용 bbox 하이라이트 뷰어(#55).
//
// 동작:
//   - 원본 PDF를 다운로드(documentAPI.downloadDocument)하여 pdfjs-dist로 캔버스에 렌더한다.
//   - CitationRegion(bbox)을 페이지 위에 하이라이트 오버레이로 표시한다.
//   - 확대/축소(zoom)와 HiDPI(devicePixelRatio) 스케일을 지원한다.
//
// graceful degradation(백엔드 계약 의존):
//   - 백엔드가 bbox(citation_regions/page_dimensions)를 제공하지 않으면 boxes가 비어
//     컴포넌트는 null을 반환한다(하이라이트만 생략, 기존 동작 보존).
//   - PDF가 아니거나 documentId가 없으면 미리보기를 시도하지 않는다.
//   - PDF 로드/렌더 실패 시 좌표 가이드(좌표 비율 박스)로 폴백한다.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FileText, MapPin, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from 'pdfjs-dist';
import { documentAPI } from '../../services/api';
import { CitationRegion, PageDimensions } from '../../types/chat';
import { Button } from '@/components/ui/button';
import { buildPdfCitationBoxes, buildPdfCitationRenderBoxes } from './pdfCitationGeometry';
import { useMenuMessages } from '../../i18n/useMenuLocale';

interface PdfCitationPreviewProps {
    documentId?: string | null;
    documentName?: string | null;
    fileType?: string | null;
    citationRegions: CitationRegion[];
    pageDimensions?: PageDimensions | null;
    page?: number | null;
}

interface RenderedPdfPage {
    width: number;
    height: number;
}

const MIN_ZOOM = 0.75;
const MAX_ZOOM = 2;
const ZOOM_STEP = 0.25;

// 문서명/타입으로 PDF 여부를 판단한다.
const isPdfLike = (documentName?: string | null, fileType?: string | null): boolean => {
    const normalizedType = fileType?.toLowerCase().replace(/^\./, '');
    if (normalizedType === 'pdf' || normalizedType === 'application/pdf') {
        return true;
    }
    return documentName?.toLowerCase().endsWith('.pdf') ?? false;
};

// zoom 값을 허용 범위로 클램핑.
const clampZoom = (value: number): number => (
    Math.min(Math.max(value, MIN_ZOOM), MAX_ZOOM)
);

// 요청 페이지 번호를 [1, pageCount] 범위로 정규화.
const normalizePageNumber = (
    requestedPage: number | null | undefined,
    pageCount: number | null,
): number => {
    const pageNumber = Number.isFinite(requestedPage)
        ? Math.trunc(Number(requestedPage))
        : 1;
    const lowerBounded = Math.max(pageNumber, 1);
    return pageCount && pageCount > 0
        ? Math.min(lowerBounded, pageCount)
        : lowerBounded;
};

// 렌더 취소(컴포넌트 언마운트/재렌더)로 인한 예외인지 판별(정상 흐름이라 에러 처리 제외).
const isRenderingCancelled = (error: unknown): boolean => (
    error instanceof Error && error.name === 'RenderingCancelledException'
);

// pdfjs 모듈과 worker를 지연 로드(번들 분할 + 최초 사용 시 1회만 로드).
let pdfjsModulePromise: Promise<typeof import('pdfjs-dist')> | null = null;

const loadPdfjs = async (): Promise<typeof import('pdfjs-dist')> => {
    pdfjsModulePromise ??= Promise.all([
        import('pdfjs-dist'),
        import('pdfjs-dist/build/pdf.worker.mjs?url'),
    ]).then(([pdfjs, worker]) => {
        if (!pdfjs.GlobalWorkerOptions.workerSrc) {
            pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
        }
        return pdfjs;
    });
    return pdfjsModulePromise;
};

/**
 * PdfCitationPreview - PDF 인용 영역을 하이라이트하는 뷰어 컴포넌트.
 * bbox 데이터가 없으면 null을 반환하여 기존 동작을 보존한다(graceful).
 */
export const PdfCitationPreview: React.FC<PdfCitationPreviewProps> = ({
    documentId,
    documentName,
    fileType,
    citationRegions,
    pageDimensions,
    page,
}) => {
    const { messages } = useMenuMessages();
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const [pdfBlob, setPdfBlob] = useState<Blob | null>(null);
    const [pdfDocument, setPdfDocument] = useState<PDFDocumentProxy | null>(null);
    const [pageCount, setPageCount] = useState<number | null>(null);
    const [renderedPage, setRenderedPage] = useState<RenderedPdfPage | null>(null);
    const [loading, setLoading] = useState(false);
    const [rendering, setRendering] = useState(false);
    const [failed, setFailed] = useState(false);
    const [zoom, setZoom] = useState(1);
    const shouldPreview = Boolean(documentId) && isPdfLike(documentName, fileType);
    const requestedPage = page ?? citationRegions.find((region) => region.page != null)?.page ?? 1;
    const activePage = normalizePageNumber(requestedPage, pageCount);
    // %(상대) 좌표 박스(폴백 좌표 가이드용)
    const boxes = useMemo(
        () => buildPdfCitationBoxes(citationRegions, pageDimensions, activePage),
        [activePage, citationRegions, pageDimensions],
    );
    // 렌더 캔버스 크기 기준 px(절대) 좌표 박스(실제 오버레이용)
    const renderBoxes = useMemo(
        () => renderedPage
            ? buildPdfCitationRenderBoxes(
                citationRegions,
                pageDimensions,
                renderedPage.width,
                renderedPage.height,
                activePage,
            )
            : [],
        [activePage, citationRegions, pageDimensions, renderedPage],
    );

    // 1단계: 원본 PDF 바이너리를 다운로드한다.
    useEffect(() => {
        let active = true;

        setPdfBlob(null);
        setPdfDocument(null);
        setPageCount(null);
        setRenderedPage(null);
        setFailed(false);
        if (!shouldPreview || !documentId) {
            return () => undefined;
        }

        setLoading(true);
        documentAPI.downloadDocument(documentId)
            .then((response) => {
                if (!active) return;
                setPdfBlob(response.data);
            })
            .catch(() => {
                // 다운로드 실패 시 좌표 가이드(폴백)로 graceful degradation
                if (active) setFailed(true);
            })
            .finally(() => {
                if (active) setLoading(false);
            });

        return () => {
            active = false;
        };
    }, [documentId, shouldPreview]);

    // 2단계: 다운로드한 Blob을 pdfjs로 파싱한다.
    useEffect(() => {
        let active = true;
        let loadedDocument: PDFDocumentProxy | null = null;
        let loadingTask: PDFDocumentLoadingTask | null = null;

        setPdfDocument(null);
        setPageCount(null);
        setRenderedPage(null);
        setFailed(false);

        if (!pdfBlob) {
            return () => undefined;
        }

        setLoading(true);
        void pdfBlob.arrayBuffer()
            .then(async (buffer) => {
                if (!active) {
                    return null;
                }
                const pdfjs = await loadPdfjs();
                if (!active) {
                    return null;
                }
                loadingTask = pdfjs.getDocument({ data: new Uint8Array(buffer) });
                return loadingTask.promise;
            })
            .then((document) => {
                if (!document) {
                    return;
                }
                loadedDocument = document;
                if (!active) {
                    void document.destroy();
                    return;
                }
                setPdfDocument(document);
                setPageCount(document.numPages);
            })
            .catch(() => {
                if (active) setFailed(true);
            })
            .finally(() => {
                if (active) setLoading(false);
            });

        return () => {
            // 언마운트/재실행 시 진행 중인 로드 작업과 문서를 정리(메모리 누수 방지).
            active = false;
            void loadingTask?.destroy();
            if (loadedDocument) {
                void loadedDocument.destroy();
            }
        };
    }, [pdfBlob]);

    // 3단계: 활성 페이지를 캔버스에 렌더하고, 렌더된 크기를 저장한다.
    useEffect(() => {
        let active = true;
        let renderTask: RenderTask | null = null;

        const renderPage = async () => {
            if (!pdfDocument || !canvasRef.current) {
                return;
            }

            setRendering(true);
            setFailed(false);
            try {
                const pdfPage = await pdfDocument.getPage(activePage);
                if (!active || !canvasRef.current) {
                    return;
                }

                const viewport = pdfPage.getViewport({ scale: zoom });
                const canvas = canvasRef.current;
                const context = canvas.getContext('2d');
                if (!context) {
                    throw new Error('PDF canvas context unavailable');
                }
                // HiDPI(레티나) 대응: devicePixelRatio만큼 캔버스 해상도를 높인다.
                const outputScale = window.devicePixelRatio || 1;
                const canvasWidth = Math.floor(viewport.width * outputScale);
                const canvasHeight = Math.floor(viewport.height * outputScale);

                canvas.width = canvasWidth;
                canvas.height = canvasHeight;
                canvas.style.width = `${viewport.width}px`;
                canvas.style.height = `${viewport.height}px`;
                context.clearRect(0, 0, canvasWidth, canvasHeight);
                setRenderedPage({ width: viewport.width, height: viewport.height });

                renderTask = pdfPage.render({
                    canvas,
                    canvasContext: context,
                    viewport,
                    transform: outputScale !== 1
                        ? [outputScale, 0, 0, outputScale, 0, 0]
                        : undefined,
                });
                await renderTask.promise;
            } catch (error) {
                // 렌더 취소(정상 흐름)는 무시하고, 실제 실패만 폴백 처리.
                if (active && !isRenderingCancelled(error)) {
                    setFailed(true);
                }
            } finally {
                if (active) {
                    setRendering(false);
                }
            }
        };

        void renderPage();

        return () => {
            active = false;
            renderTask?.cancel();
        };
    }, [activePage, pdfDocument, zoom]);

    // bbox가 없거나 PDF가 아니면 아무것도 렌더하지 않는다(graceful).
    if (!shouldPreview || boxes.length === 0) {
        return null;
    }

    // 폴백 좌표 가이드의 종횡비(페이지 크기 기반, 없으면 A4 비율).
    const aspectRatio = pageDimensions?.width && pageDimensions.height
        ? `${pageDimensions.width} / ${pageDimensions.height}`
        : '1 / 1.414';

    return (
        <div className="space-y-4">
            <h3 className="text-lg font-bold flex items-center gap-2">
                <FileText className="h-4 w-4 text-primary" />
                {messages.pdfViewer.heading}
            </h3>
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.45fr)_minmax(220px,0.55fr)] gap-4">
                <div className="rounded-xl border border-border/50 bg-muted/20 p-3 min-h-[360px] space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="text-sm font-bold text-foreground">
                            p.{activePage}{pageCount ? ` / ${pageCount}` : ''} {messages.pdfViewer.highlightSuffix}
                        </div>
                        <div className="flex items-center gap-1">
                            <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={messages.pdfViewer.zoomOut}
                                title={messages.pdfViewer.zoomOut}
                                disabled={zoom <= MIN_ZOOM}
                                onClick={() => setZoom((value) => clampZoom(value - ZOOM_STEP))}
                            >
                                <ZoomOut className="h-4 w-4" />
                            </Button>
                            <span className="w-12 text-center text-xs font-bold text-muted-foreground">
                                {Math.round(zoom * 100)}%
                            </span>
                            <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={messages.pdfViewer.zoomIn}
                                title={messages.pdfViewer.zoomIn}
                                disabled={zoom >= MAX_ZOOM}
                                onClick={() => setZoom((value) => clampZoom(value + ZOOM_STEP))}
                            >
                                <ZoomIn className="h-4 w-4" />
                            </Button>
                            <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={messages.pdfViewer.resetZoom}
                                title={messages.pdfViewer.resetZoom}
                                disabled={zoom === 1}
                                onClick={() => setZoom(1)}
                            >
                                <RotateCcw className="h-4 w-4" />
                            </Button>
                        </div>
                    </div>

                    {(loading || rendering) && (
                        <div className="flex h-[320px] items-center justify-center text-sm font-semibold text-muted-foreground">
                            {messages.pdfViewer.loading}
                        </div>
                    )}
                    {failed && !loading && !rendering && (
                        <div className="flex h-[320px] items-center justify-center text-sm font-semibold text-muted-foreground">
                            {messages.pdfViewer.loadFailed}
                        </div>
                    )}
                    {!failed && (
                        <div className="overflow-auto rounded-lg border bg-background">
                            <div
                                className="relative mx-auto"
                                style={renderedPage ? {
                                    width: `${renderedPage.width}px`,
                                    height: `${renderedPage.height}px`,
                                } : undefined}
                                aria-label={messages.pdfViewer.highlightOverlay}
                            >
                                <canvas
                                    ref={canvasRef}
                                    className="block bg-background"
                                    data-testid="pdf-citation-canvas"
                                />
                                {renderedPage && (
                                    <div className="pointer-events-none absolute inset-0">
                                        {renderBoxes.map((box) => (
                                            <div
                                                key={box.key}
                                                className="absolute rounded border-2 border-amber-500 bg-amber-300/30 shadow-sm"
                                                style={{
                                                    left: `${box.leftPx}px`,
                                                    top: `${box.topPx}px`,
                                                    width: `${box.widthPx}px`,
                                                    height: `${box.heightPx}px`,
                                                }}
                                                title={box.label}
                                            />
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                <div className="rounded-xl border border-border/50 bg-muted/20 p-4 space-y-3">
                    <div className="flex items-center gap-2 text-sm font-bold">
                        <MapPin className="h-4 w-4 text-primary" />
                        {messages.pdfViewer.citationBox}
                    </div>
                    {/* PDF 렌더 실패 시 좌표 비율 기반 가이드로 폴백 */}
                    {failed && (
                        <div
                            className="relative w-full overflow-hidden rounded-lg border bg-background shadow-inner"
                            style={{ aspectRatio }}
                            aria-label={messages.pdfViewer.coordGuide}
                        >
                            {boxes.map((box) => (
                                <div
                                    key={box.key}
                                    className="absolute rounded border-2 border-amber-500 bg-amber-300/30 shadow-sm"
                                    style={{
                                        left: `${box.leftPct}%`,
                                        top: `${box.topPct}%`,
                                        width: `${box.widthPct}%`,
                                        height: `${box.heightPct}%`,
                                    }}
                                    title={box.label}
                                />
                            ))}
                        </div>
                    )}
                    <div className="flex flex-wrap gap-2">
                        {boxes.slice(0, 6).map((box) => (
                            <span
                                key={`${box.key}-label`}
                                className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-bold text-primary"
                            >
                                {box.label}
                            </span>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
};
