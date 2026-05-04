import React from 'react';
import { FileText } from 'lucide-react';
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
import { formatFullContent } from '../../utils/chat/formatters';
import { cn } from '@/lib/utils';
import { ScrollArea } from "@/components/ui/scroll-area";

interface ChunkDetailModalProps {
    open: boolean;
    onClose: () => void;
    selectedChunk: SourceType | null;
    documentInfoItems: DocumentInfoItem[];
}

export const ChunkDetailModal: React.FC<ChunkDetailModalProps> = ({
    open,
    onClose,
    selectedChunk,
    documentInfoItems,
}) => {
    return (
        <Dialog open={open} onOpenChange={onClose}>
            <DialogContent className="max-w-3xl max-h-[90vh] flex flex-col p-0 overflow-hidden border-none shadow-2xl">
                <DialogHeader className="bg-primary text-primary-foreground p-5 space-y-0 flex-row items-center justify-between shrink-0">
                    <div className="flex items-center gap-2.5">
                        <div className="bg-primary-foreground/10 p-2 rounded-lg">
                            <FileText className="h-5 w-5" />
                        </div>
                        <DialogTitle className="text-xl font-bold tracking-tight">
                            RAG 참고 자료 상세
                        </DialogTitle>
                    </div>
                    <DialogDescription className="sr-only">
                        선택한 RAG 참고 자료의 문서 정보와 청크 내용을 확인합니다.
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
                                                        📄 문서 정보
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
                                            문서 정보를 불러올 수 없습니다.
                                        </div>
                                    )}
                                </div>

                                <hr className="border-border/50" />

                                {/* 청크 내용 */}
                                <div className="space-y-4">
                                    <h3 className="text-lg font-bold flex items-center gap-2">
                                        <div className="h-4 w-1 bg-primary rounded-full" />
                                        청크 내용
                                    </h3>
                                    <div className="rounded-xl border bg-muted/20 border-border/40 p-6 relative group transition-all hover:bg-muted/30">
                                        {/* HTML 테이블인 경우 및 일반 텍스트 렌더링 */}
                                        <div className={cn(
                                            "text-sm leading-relaxed prose prose-sm max-w-none prose-slate dark:prose-invert",
                                            "font-sans antialiased"
                                        )}>
                                            <div className="whitespace-pre-wrap leading-[1.8] font-medium text-foreground/90">
                                                {formatFullContent(selectedChunk.content_preview)}
                                            </div>
                                        </div>
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
                        닫기
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
