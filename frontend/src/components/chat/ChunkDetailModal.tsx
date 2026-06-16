import React from 'react';
import { FileText, Loader2, MapPin } from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogFooter,
} from "@/components/ui/dialog";
import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from '@/components/ui/button';
import {
    Source as SourceType,
    DocumentInfoItem,
    CitationRegion,
    PageDimensions,
} from '../../types/chat';
import type { SourceDetail } from '../../types';
import { formatFullContent } from '../../utils/chat/formatters';
import { documentAPI } from '../../services/api';
import { logger } from '../../utils/logger';
import { cn } from '@/lib/utils';
import { ScrollArea } from "@/components/ui/scroll-area";
import { useMenuMessages } from '../../i18n/useMenuLocale';
import { PdfCitationPreview } from './PdfCitationPreview';

// 좌표 값을 사람이 읽기 쉬운 형태로 포맷한다(정수는 그대로, 소수는 불필요한 0 제거).
const formatCoordinate = (value: number): string => {
    if (!Number.isFinite(value)) {
        return String(value);
    }
    const rounded = Math.round(value * 100) / 100;
    return Number.isInteger(rounded)
        ? String(rounded)
        : rounded.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
};

// bbox([x0, y0, x1, y1])를 콤마 구분 문자열로 변환한다. 4개가 아니면 null(미표시).
const formatBBox = (bbox?: number[] | null): string | null => {
    if (!bbox || bbox.length !== 4) {
        return null;
    }
    return bbox.map(formatCoordinate).join(', ');
};

// page_dimensions(폭 x 높이)를 표시 문자열로 변환한다. 값이 없으면 null(미표시).
const formatPageDimensions = (dimensions?: PageDimensions | null): string | null => {
    if (!dimensions) {
        return null;
    }
    const width = Number.isFinite(dimensions.width) ? formatCoordinate(dimensions.width) : '?';
    const height = Number.isFinite(dimensions.height) ? formatCoordinate(dimensions.height) : '?';
    return `${width} x ${height}`;
};

// citation region의 표시용 제목(region_id → region_type → 순번 순으로 폴백).
const regionTitle = (region: CitationRegion, index: number): string => {
    return region.region_id || region.region_type || `region-${index + 1}`;
};

// 문서가 PDF인지 판정한다(file_type 또는 파일명 확장자 기준).
const isPdfSource = (fileType?: string | null, documentName?: string | null): boolean => {
    if (fileType && fileType.toLowerCase().includes('pdf')) {
        return true;
    }
    return Boolean(documentName && documentName.toLowerCase().endsWith('.pdf'));
};

interface ChunkDetailModalProps {
    open: boolean;
    onClose: () => void;
    selectedChunk: SourceType | null;
    documentInfoItems: DocumentInfoItem[];
    /** lazy 조회된 청크 전체 상세(없으면 content_preview로 fallback) */
    sourceDetail?: SourceDetail | null;
    /** 상세 조회 로딩 상태 */
    sourceDetailLoading?: boolean;
    /** 상세 조회 실패 메시지(있어도 미리보기로 graceful degradation) */
    sourceDetailError?: string | null;
}

export const ChunkDetailModal: React.FC<ChunkDetailModalProps> = ({
    open,
    onClose,
    selectedChunk,
    documentInfoItems,
    sourceDetail,
    sourceDetailLoading = false,
    sourceDetailError = null,
}) => {
    // i18n: 모달 라벨
    const { messages } = useMenuMessages();
    // 표시할 청크 본문 결정: 전체 원문(full_content/content) 우선, 없으면 미리보기로 fallback.
    const fullContent = sourceDetail?.full_content ?? sourceDetail?.content ?? null;
    const displayContent = fullContent ?? selectedChunk?.content_preview ?? '';

    // 인용 영역(citation regions)과 페이지 치수는 selectedChunk(Source)에서 가져온다.
    const citationRegions = selectedChunk?.citation_regions ?? [];
    const pageDimensions = selectedChunk?.page_dimensions ?? null;
    const pageDimensionsLabel = formatPageDimensions(pageDimensions);

    // PDF 인라인 미리보기용 식별자. document_id가 있고 PDF일 때만 미리보기를 시도한다.
    const previewDocumentId = selectedChunk?.document_id ?? null;
    const previewDocumentName = selectedChunk?.document_name ?? selectedChunk?.document ?? null;
    const previewPage = selectedChunk?.page ?? citationRegions[0]?.page ?? null;
    const canPreviewPdf = Boolean(
        previewDocumentId && isPdfSource(selectedChunk?.file_type, previewDocumentName)
    );

    // PDF blob을 받아 만든 object URL과 로딩/실패 상태.
    // OneRAG documentAPI에는 직접 다운로드 URL이 없고 /download가 인증을 요구하므로,
    // iframe src에 원격 URL을 직접 넣지 않고 axios(인증 인터셉터 적용)로 blob을 받아
    // URL.createObjectURL로 만든 로컬 URL을 사용한다(#page=N 프래그먼트로 페이지 점프).
    const [pdfObjectUrl, setPdfObjectUrl] = React.useState<string | null>(null);
    const [pdfPreviewLoading, setPdfPreviewLoading] = React.useState<boolean>(false);
    const [pdfPreviewFailed, setPdfPreviewFailed] = React.useState<boolean>(false);

    React.useEffect(() => {
        // 모달이 닫혀 있거나 PDF가 아니면 미리보기를 시도하지 않는다.
        if (!open || !canPreviewPdf || !previewDocumentId) {
            setPdfObjectUrl(null);
            setPdfPreviewLoading(false);
            setPdfPreviewFailed(false);
            return;
        }

        let active = true;
        let createdUrl: string | null = null;

        setPdfPreviewLoading(true);
        setPdfPreviewFailed(false);

        documentAPI.downloadDocument(previewDocumentId)
            .then((response) => {
                if (!active) {
                    return;
                }
                // 응답 blob의 Content-Type을 PDF로 강제해 브라우저 내장 뷰어가 열리도록 한다.
                const blob = new Blob([response.data], { type: 'application/pdf' });
                createdUrl = URL.createObjectURL(blob);
                setPdfObjectUrl(createdUrl);
            })
            .catch((error) => {
                // 다운로드 실패 시 좌표 텍스트 목록(폴백)만 표시(graceful degradation).
                if (active) {
                    logger.warn('PDF 미리보기 다운로드 실패:', error);
                    setPdfPreviewFailed(true);
                }
            })
            .finally(() => {
                if (active) {
                    setPdfPreviewLoading(false);
                }
            });

        return () => {
            active = false;
            if (createdUrl) {
                // object URL 누수를 방지한다.
                URL.revokeObjectURL(createdUrl);
            }
        };
    }, [open, canPreviewPdf, previewDocumentId]);

    // iframe src: blob URL + #page=N(1-base). 페이지 정보가 없으면 1페이지.
    const pdfPreviewSrc = pdfObjectUrl
        ? `${pdfObjectUrl}#page=${previewPage ?? 1}`
        : null;

    return (
        <Dialog open={open} onOpenChange={onClose}>
            <DialogContent className="max-w-3xl max-h-[90vh] flex flex-col p-0 overflow-hidden border-none shadow-2xl">
                <DialogHeader className="bg-primary text-primary-foreground p-5 space-y-0 flex-row items-center justify-between shrink-0">
                    <div className="flex items-center gap-2.5">
                        <div className="bg-primary-foreground/10 p-2 rounded-lg">
                            <FileText className="h-5 w-5" />
                        </div>
                        <DialogTitle className="text-xl font-bold tracking-tight">
                            {messages.chunkDetail.modalTitle}
                        </DialogTitle>
                    </div>
                    <DialogDescription className="sr-only">
                        {messages.chunkDetail.modalDesc}
                    </DialogDescription>
                </DialogHeader>

                <ScrollArea className="flex-1 overflow-y-auto">
                    <div className="p-6 space-y-8">
                        {selectedChunk && (
                            <div className="space-y-8">
                                {/* 문서 정보 */}
                                <div className="space-y-4">
                                    {documentInfoItems.length > 0 ? (
                                        <Accordion type="single" collapsible defaultValue="doc-info" className="border rounded-xl shadow-sm overflow-hidden bg-background">
                                            <AccordionItem value="doc-info" className="border-none">
                                                <AccordionTrigger className="px-5 py-4 hover:no-underline bg-muted/50 hover:bg-muted transition-all">
                                                    <span className="flex items-center gap-2 font-bold text-sm">
                                                        📄 {messages.chunkDetail.documentInfo}
                                                    </span>
                                                </AccordionTrigger>
                                                <AccordionContent className="px-5 py-5 border-t">
                                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                        {documentInfoItems.map((item, index) => (
                                                            <div
                                                                key={`document-info-${index}`}
                                                                className="p-3.5 rounded-xl bg-muted/30 border border-border/50 transition-all hover:border-primary/20"
                                                            >
                                                                <div className="text-[10px] font-extrabold text-muted-foreground uppercase tracking-widest mb-1">
                                                                    {item.label}
                                                                </div>
                                                                <div className="text-sm font-semibold text-foreground leading-relaxed break-words whitespace-pre-wrap">
                                                                    {item.value}
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </AccordionContent>
                                            </AccordionItem>
                                        </Accordion>
                                    ) : (
                                        <div className="text-sm text-muted-foreground italic py-2">
                                            {messages.chunkDetail.documentInfoUnavailable}
                                        </div>
                                    )}
                                </div>

                                <hr className="border-border/50" />

                                {/*
                                  PDF 인용 하이라이트 뷰어(#55).
                                  selectedChunk에 citation_regions/page_dimensions(백엔드 제공)가 있으면 표시되고,
                                  없으면 PdfCitationPreview가 null을 반환하여 자동으로 생략된다(graceful).
                                */}
                                <PdfCitationPreview
                                    documentId={selectedChunk.document_id ?? null}
                                    documentName={selectedChunk.document_name ?? selectedChunk.document}
                                    fileType={selectedChunk.file_type ?? null}
                                    citationRegions={selectedChunk.citation_regions ?? []}
                                    pageDimensions={selectedChunk.page_dimensions ?? null}
                                    page={selectedChunk.page ?? null}
                                />

                                {/*
                                  PDF 인라인 미리보기(#56).
                                  PDF 문서면 blob URL + #page=N으로 브라우저 내장 뷰어를 inline iframe으로 띄운다.
                                  다운로드 실패/비PDF면 graceful하게 생략된다.
                                */}
                                {canPreviewPdf && (
                                    <>
                                        <hr className="border-border/50" />
                                        <div className="space-y-4">
                                            <div className="flex items-center justify-between gap-3">
                                                <h3 className="text-lg font-bold flex items-center gap-2">
                                                    <div className="h-4 w-1 bg-primary rounded-full" />
                                                    {messages.chunkDetail.pdfPreview}
                                                </h3>
                                                {pdfPreviewSrc && (
                                                    <a
                                                        data-testid="source-pdf-open-link"
                                                        href={pdfPreviewSrc}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        className="text-xs font-bold text-primary hover:underline"
                                                    >
                                                        {messages.chunkDetail.openInNewTab}
                                                    </a>
                                                )}
                                            </div>
                                            {pdfPreviewLoading && (
                                                <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
                                                    <Loader2 className="h-4 w-4 animate-spin" />
                                                    {messages.chunkDetail.pdfPreviewLoading}
                                                </div>
                                            )}
                                            {pdfPreviewFailed && !pdfPreviewLoading && (
                                                <p className="text-xs font-medium text-muted-foreground">
                                                    {messages.chunkDetail.pdfPreviewFailed}
                                                </p>
                                            )}
                                            {pdfPreviewSrc && !pdfPreviewLoading && (
                                                <iframe
                                                    data-testid="source-pdf-preview"
                                                    title={messages.chunkDetail.pdfPreview}
                                                    src={pdfPreviewSrc}
                                                    className="h-80 w-full rounded-xl border border-border/60 bg-muted/20"
                                                />
                                            )}
                                        </div>
                                    </>
                                )}

                                {/*
                                  인용 영역 좌표 텍스트 목록(#56).
                                  citation_regions가 있으면 region_id/type·page·bbox·confidence·table을
                                  검사 가능한 텍스트로 노출한다. 데이터가 없으면 graceful하게 생략된다.
                                */}
                                {citationRegions.length > 0 && (
                                    <>
                                        <hr className="border-border/50" />
                                        <div className="space-y-4">
                                            <h3 className="text-lg font-bold flex items-center gap-2">
                                                <MapPin className="h-4 w-4 text-primary" />
                                                {messages.chunkDetail.citationLocation}
                                            </h3>
                                            {pageDimensionsLabel && (
                                                <div className="text-xs font-semibold text-muted-foreground">
                                                    {messages.chunkDetail.pageSizePrefix} {pageDimensionsLabel}
                                                </div>
                                            )}
                                            <div
                                                data-testid="citation-region-list"
                                                className="grid grid-cols-1 md:grid-cols-2 gap-3"
                                            >
                                                {citationRegions.map((region, index) => {
                                                    const bbox = formatBBox(region.bbox);
                                                    return (
                                                        <div
                                                            key={`${region.region_id ?? region.region_type ?? 'region'}-${index}`}
                                                            className="rounded-xl border border-border/50 bg-muted/20 p-4 space-y-2"
                                                        >
                                                            <div className="flex flex-wrap items-center gap-2">
                                                                <span className="text-sm font-bold text-foreground">
                                                                    {regionTitle(region, index)}
                                                                </span>
                                                                {region.page != null && (
                                                                    <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-bold text-primary">
                                                                        {messages.chunkDetail.pagePrefix}{region.page}
                                                                    </span>
                                                                )}
                                                                {region.confidence != null && (
                                                                    <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
                                                                        {messages.chunkDetail.confidencePrefix} {formatCoordinate(region.confidence)}
                                                                    </span>
                                                                )}
                                                            </div>
                                                            {bbox && (
                                                                <div className="text-xs font-mono text-muted-foreground break-words">
                                                                    BBox {bbox}
                                                                </div>
                                                            )}
                                                            {region.table_index != null && (
                                                                <div className="text-xs text-muted-foreground">
                                                                    {messages.chunkDetail.tablePrefix} {region.table_index}
                                                                </div>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    </>
                                )}

                                {/* 청크 내용 */}
                                <div className="space-y-4">
                                    <h3 className="text-lg font-bold flex items-center gap-2">
                                        <div className="h-4 w-1 bg-primary rounded-full" />
                                        {messages.chunkDetail.chunkContent}
                                    </h3>
                                    {/* 상세 조회 실패 시 미리보기로 대체한다는 안내(graceful degradation) */}
                                    {sourceDetailError && (
                                        <p className="text-xs font-medium text-muted-foreground">
                                            {sourceDetailError}
                                        </p>
                                    )}
                                    <div className="rounded-xl border bg-muted/20 border-border/40 p-6 relative group transition-all hover:bg-muted/30">
                                        {sourceDetailLoading ? (
                                            <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
                                                <Loader2 className="h-4 w-4 animate-spin" />
                                                {messages.chunkDetail.loadingFullContent}
                                            </div>
                                        ) : (
                                            /* HTML 테이블인 경우 및 일반 텍스트 렌더링 */
                                            <div className={cn(
                                                "text-sm leading-relaxed prose prose-sm max-w-none prose-slate dark:prose-invert",
                                                "font-sans antialiased"
                                            )}>
                                                <div className="whitespace-pre-wrap leading-[1.8] font-medium text-foreground/90">
                                                    {formatFullContent(displayContent)}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </ScrollArea>

                <DialogFooter className="p-4 border-t bg-muted/10 shrink-0">
                    <Button
                        onClick={onClose}
                        className="font-bold px-8 h-10 shadow-md hover:scale-105 transition-transform"
                    >
                        {messages.chunkDetail.close}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
