/**
 * 프롬프트 삭제 확인 다이얼로그 컴포넌트
 *
 * 프롬프트 삭제 전 확인을 요청하는 다이얼로그입니다.
 * 시스템 프롬프트인 경우 추가 경고 메시지를 표시합니다.
 *
 * Props:
 * - open: 다이얼로그 열림 상태
 * - onOpenChange: 다이얼로그 열림 상태 변경 핸들러
 * - selectedPrompt: 삭제할 프롬프트 데이터
 * - onConfirm: 삭제 확인 핸들러
 */

import React from 'react';
import { Trash2, Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
} from '@/components/ui/dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';

import type { Prompt } from '../../types/prompt';

export interface PromptDeleteDialogProps {
  /** 다이얼로그 열림 상태 */
  open: boolean;
  /** 다이얼로그 열림 상태 변경 핸들러 */
  onOpenChange: (open: boolean) => void;
  /** 삭제할 프롬프트 데이터 */
  selectedPrompt: Prompt | null;
  /** 삭제 확인 핸들러 */
  onConfirm: () => void;
}

export const PromptDeleteDialog: React.FC<PromptDeleteDialogProps> = ({
  open,
  onOpenChange,
  selectedPrompt,
  onConfirm,
}) => {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md p-0 overflow-hidden rounded-3xl border-none shadow-2xl">
        <div className="p-8 pb-4 text-center space-y-4">
          {/* 삭제 아이콘 */}
          <div className="mx-auto w-16 h-16 bg-destructive/10 rounded-full flex items-center justify-center text-destructive">
            <Trash2 className="w-8 h-8" />
          </div>

          {/* 삭제 확인 메시지 */}
          <div className="space-y-1">
            <h3 className="text-xl font-bold text-foreground">프롬프트 삭제</h3>
            <p className="text-sm text-muted-foreground">
              &apos;<span className="font-bold text-foreground">{selectedPrompt?.name}</span>&apos; 프롬프트를 정말 삭제하시겠습니까?<br />이 작업은 되돌릴 수 없습니다.
            </p>
          </div>

          {/* 시스템 프롬프트 경고 */}
          {selectedPrompt?.category === 'system' && (
            <Alert variant="destructive" className="bg-destructive/10 text-destructive border-none rounded-2xl text-left mt-4 p-3">
              <Info className="h-4 w-4" />
              <AlertDescription className="text-xs font-bold leading-tight uppercase tracking-tight">
                시스템 핵심 프롬프트입니다. 삭제 시 시스템 동작이 불안정해질 수 있습니다.
              </AlertDescription>
            </Alert>
          )}
        </div>

        {/* 하단 버튼 */}
        <DialogFooter className="p-6 pt-2 grid grid-cols-2 gap-3">
          <Button variant="outline" onClick={() => onOpenChange(false)} className="rounded-xl font-bold h-12">
            취소
          </Button>
          <Button variant="destructive" onClick={onConfirm} className="rounded-xl font-bold h-12 shadow-lg shadow-destructive/20">
            확인 및 삭제
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
