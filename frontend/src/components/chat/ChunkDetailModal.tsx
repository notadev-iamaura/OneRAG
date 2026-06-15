import React from 'react';
import { FileText, Loader2 } from 'lucide-react';
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
} from '../../types/chat';
import type { SourceDetail } from '../../types';
import { formatFullContent } from '../../utils/chat/formatters';
import { cn } from '@/lib/utils';
import { ScrollArea } from "@/components/ui/scroll-area";
import { useMenuMessages } from '../../i18n/useMenuLocale';
import { PdfCitationPreview } from './PdfCitationPreview';

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
