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
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent className="max-w-md rounded-[28px] border-border/40 p-0 overflow-hidden">
        <DialogHeader className="p-6 pb-4 bg-muted/30">
          <DialogTitle className="text-xl font-black">문서 상세 정보</DialogTitle>
          <DialogDescription className="text-sm font-medium">문서의 메타데이터와 상태 정보를 확인합니다</DialogDescription>
        </DialogHeader>
        <div className="p-6 pt-0 space-y-4">
          <ScrollArea className="max-h-[60vh] pr-4">
            {doc && (
              <div className="space-y-4">
                <DetailRow label="파일명" value={doc.originalName} />
                <DetailRow label="문서 ID" value={doc.id} copyable />
                <DetailRow label="파일 크기" value={formatFileSize(doc.size)} />
                <DetailRow label="MIME 타입" value={doc.mimeType} />
                <DetailRow label="업로드 일시" value={new Date(doc.uploadedAt).toLocaleString()} />
                <DetailRow label="상태" value={doc.status} />
                {doc.chunks && <DetailRow label="청크 수" value={`${doc.chunks}개`} />}
                {doc.metadata?.pageCount && <DetailRow label="페이지 수" value={`${doc.metadata.pageCount}P`} />}
                {doc.metadata?.wordCount && <DetailRow label="단어 수" value={`${doc.metadata.wordCount}개`} />}
              </div>
            )}
          </ScrollArea>
        </div>
        <DialogFooter className="p-6 bg-muted/10">
          <Button variant="secondary" className="rounded-xl font-bold w-full" onClick={onClose}>닫기</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
