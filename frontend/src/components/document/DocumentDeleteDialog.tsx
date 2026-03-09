/**
 * 단일 문서 삭제 확인 다이얼로그 컴포넌트
 *
 * 사용자가 문서 1개를 삭제할 때 확인을 요청하는 다이얼로그입니다.
 * 로딩 상태에서는 취소/삭제 버튼이 비활성화됩니다.
 */
import React from 'react';
import { Trash2, RotateCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

/** DocumentDeleteDialog 컴포넌트의 Props */
export interface DocumentDeleteDialogProps {
  /** 다이얼로그 열림 여부 */
  open: boolean;
  /** 삭제 진행 중 로딩 상태 */
  loading: boolean;
  /** 삭제 확인 핸들러 */
  onConfirm: () => void;
  /** 취소 핸들러 */
  onCancel: () => void;
}

/**
 * 단일 문서 삭제 확인 다이얼로그 컴포넌트
 *
 * "이 문서를 삭제하시겠습니까?" 메시지와 함께 삭제/취소 버튼을 제공합니다.
 */
export const DocumentDeleteDialog: React.FC<DocumentDeleteDialogProps> = ({
  open,
  loading,
  onConfirm,
  onCancel,
}) => {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onCancel(); }}>
      <DialogContent className="rounded-[28px] max-w-sm">
        <DialogHeader>
          <div className="w-12 h-12 rounded-2xl bg-destructive/10 text-destructive flex items-center justify-center mb-4">
            <Trash2 className="w-6 h-6" />
          </div>
          <DialogTitle className="text-xl font-black">문서 삭제</DialogTitle>
          <DialogDescription className="font-medium text-sm">
            이 문서를 삭제하시겠습니까? <br />이 작업은 되돌릴 수 없습니다.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 mt-4">
          <Button variant="ghost" onClick={onCancel} disabled={loading} className="rounded-xl font-bold">취소</Button>
          <Button variant="destructive" onClick={onConfirm} disabled={loading} className="rounded-xl font-bold shadow-lg shadow-destructive/20">
            {loading ? <RotateCw className="w-4 h-4 mr-2 animate-spin" /> : null}
            {loading ? '삭제 중...' : '삭제하기'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
