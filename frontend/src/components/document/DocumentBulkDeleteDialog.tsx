/**
 * 일괄 삭제 확인 다이얼로그 컴포넌트
 *
 * 선택된 여러 문서를 한번에 삭제할 때 확인을 요청하는 다이얼로그입니다.
 * 선택된 문서 수를 제목에 표시하고, 로딩 중 버튼 비활성화를 지원합니다.
 */
import React from 'react';
import { ShieldAlert, RotateCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

/** DocumentBulkDeleteDialog 컴포넌트의 Props */
export interface DocumentBulkDeleteDialogProps {
  /** 다이얼로그 열림 여부 */
  open: boolean;
  /** 삭제 진행 중 로딩 상태 */
  loading: boolean;
  /** 선택된 문서 수 */
  selectedCount: number;
  /** 삭제 확인 핸들러 */
  onConfirm: () => void;
  /** 취소 핸들러 */
  onCancel: () => void;
}

/**
 * 일괄 삭제 확인 다이얼로그 컴포넌트
 *
 * "{N}개 문서 삭제" 제목과 경고 메시지를 표시하고, 삭제 승인/취소 버튼을 제공합니다.
 */
export const DocumentBulkDeleteDialog: React.FC<DocumentBulkDeleteDialogProps> = ({
  open,
  loading,
  selectedCount,
  onConfirm,
  onCancel,
}) => {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onCancel(); }}>
      <DialogContent className="rounded-[28px] max-w-sm">
        <DialogHeader>
          <div className="w-12 h-12 rounded-2xl bg-destructive/10 text-destructive flex items-center justify-center mb-4">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <DialogTitle className="text-xl font-black">{selectedCount}개 문서 삭제</DialogTitle>
          <DialogDescription className="font-medium text-sm">
            선택한 모든 문서를 영구적으로 삭제합니다.<br />정말 진행하시겠습니까?
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 mt-4">
          <Button variant="ghost" onClick={onCancel} disabled={loading} className="rounded-xl font-bold">취소</Button>
          <Button variant="destructive" onClick={onConfirm} disabled={loading} className="rounded-xl font-bold shadow-lg shadow-destructive/20">
            {loading ? <RotateCw className="w-4 h-4 mr-2 animate-spin" /> : null}
            삭제 승인
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
