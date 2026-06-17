/**
 * 문서 상세 정보 다이얼로그 컴포넌트
 *
 * 선택한 문서의 메타데이터(파일명, ID, 크기, MIME 타입, 업로드 일시,
 * 상태, 청크 수, 페이지 수, 단어 수)를 다이얼로그로 표시합니다.
 */
import React from 'react';
import { MoreHorizontal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { formatFileSize } from '../../utils/documentUtils';
import { useMenuMessages } from '../../i18n/useMenuLocale';
import { format } from '../../i18n/format';
import type { Document } from '../../types';

/** DocumentDetailDialog 컴포넌트의 Props */
export interface DocumentDetailDialogProps {
  /** 다이얼로그 열림 여부 */
  open: boolean;
  /** 상세 정보를 표시할 문서 (null이면 내용 미표시) */
  document: Document | null;
  /** 닫기 핸들러 */
  onClose: () => void;
}

/**
 * 양수 카운트 타입 가드.
 *
 * React는 false/null/undefined만 렌더링에서 건너뛰고 숫자 0은 그대로 "0" 텍스트로 표시한다.
 * 따라서 `{count && <Row/>}` 형태는 count가 0일 때 화면에 길잃은 '0'을 남긴다.
 * 이 가드로 0/undefined를 모두 걸러내고, 양수일 때만 행을 렌더링한다.
 */
const hasPositiveCount = (value: number | undefined): value is number => (
  typeof value === 'number' && value > 0
);

/** 상세 정보 행 컴포넌트 (라벨 + 값) */
const DetailRow = ({ label, value, copyable }: { label: string; value: string | number | undefined | null; copyable?: boolean }) => (
  <div className="group/row">
    <p className="text-[10px] uppercase font-black text-muted-foreground/60 mb-1 tracking-wider">{label}</p>
    <div className="flex items-center justify-between p-3 rounded-xl bg-muted/30 border border-transparent group-hover/row:border-border/60 transition-all">
      <p className="text-sm font-bold text-foreground break-all">{value || '-'}</p>
      {copyable && value && (
        <Button variant="ghost" size="icon" className="h-6 w-6 opacity-0 group-hover/row:opacity-100 transition-opacity" onClick={() => navigator.clipboard.writeText(String(value))}>
          <MoreHorizontal className="w-3 h-3" />
        </Button>
      )}
    </div>
  </div>
);

/**
 * 문서 상세 정보 다이얼로그 컴포넌트
 *
 * 문서의 메타데이터와 상태 정보를 스크롤 가능한 영역에 행(row) 형태로 표시합니다.
 */
export const DocumentDetailDialog: React.FC<DocumentDetailDialogProps> = ({
  open,
  document: doc,
  onClose,
}) => {
  // i18n: 현재 로케일에 해당하는 번역 사전을 가져온다.
  const { messages } = useMenuMessages();
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent className="max-w-md rounded-[28px] border-border/40 p-0 overflow-hidden">
        <DialogHeader className="p-6 pb-4 bg-muted/30">
          <DialogTitle className="text-xl font-black">{messages.docDetail.title}</DialogTitle>
          <DialogDescription className="text-sm font-medium">{messages.docDetail.description}</DialogDescription>
        </DialogHeader>
        <div className="p-6 pt-0 space-y-4">
          <ScrollArea className="max-h-[60vh] pr-4">
            {doc && (
              <div className="space-y-4">
                <DetailRow label={messages.docDetail.filename} value={doc.originalName} />
                <DetailRow label={messages.docDetail.documentId} value={doc.id} copyable />
                <DetailRow label={messages.docDetail.fileSize} value={formatFileSize(doc.size)} />
                <DetailRow label={messages.docDetail.mimeType} value={doc.mimeType} />
                <DetailRow label={messages.docDetail.uploadedAt} value={new Date(doc.uploadedAt).toLocaleString()} />
                <DetailRow label={messages.docDetail.status} value={doc.status} />
                {hasPositiveCount(doc.chunks) && <DetailRow label={messages.docDetail.chunkCount} value={format(messages.docDetail.chunkCountValue, { count: doc.chunks })} />}
                {hasPositiveCount(doc.metadata?.pageCount) && <DetailRow label={messages.docDetail.pageCount} value={format(messages.docDetail.pageCountValue, { count: doc.metadata?.pageCount ?? 0 })} />}
                {hasPositiveCount(doc.metadata?.wordCount) && <DetailRow label={messages.docDetail.wordCount} value={format(messages.docDetail.wordCountValue, { count: doc.metadata?.wordCount ?? 0 })} />}
              </div>
            )}
          </ScrollArea>
        </div>
        <DialogFooter className="p-6 bg-muted/10">
          <Button variant="secondary" className="rounded-xl font-bold w-full" onClick={onClose}>{messages.docDetail.close}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
