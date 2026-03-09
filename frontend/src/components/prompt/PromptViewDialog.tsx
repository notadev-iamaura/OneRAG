/**
 * 프롬프트 상세 조회 다이얼로그 컴포넌트
 *
 * 프롬프트의 이름, 카테고리, 설명, 생성일/수정일, 본문을 표시합니다.
 * 복사 버튼으로 프롬프트 본문을 클립보드에 복사하거나,
 * 수정 버튼으로 편집 모드로 전환할 수 있습니다.
 *
 * Props:
 * - open: 다이얼로그 열림 상태
 * - onOpenChange: 다이얼로그 열림 상태 변경 핸들러
 * - selectedPrompt: 조회할 프롬프트 데이터
 * - onEdit: 수정 버튼 클릭 핸들러
 */

import React from 'react';
import { Copy, Edit2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Label } from '@/components/ui/label';

import type { Prompt } from '../../types/prompt';
import { PROMPT_CATEGORIES } from '../../types/prompt';

export interface PromptViewDialogProps {
  /** 다이얼로그 열림 상태 */
  open: boolean;
  /** 다이얼로그 열림 상태 변경 핸들러 */
  onOpenChange: (open: boolean) => void;
  /** 조회할 프롬프트 데이터 */
  selectedPrompt: Prompt | null;
  /** 수정 버튼 클릭 핸들러 */
  onEdit: (prompt: Prompt) => void;
}

export const PromptViewDialog: React.FC<PromptViewDialogProps> = ({
  open,
  onOpenChange,
  selectedPrompt,
  onEdit,
}) => {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl overflow-hidden p-0 rounded-3xl border-none">
        <DialogHeader className="p-6 pb-0">
          <DialogTitle className="text-xl font-bold">프롬프트 상세 정보</DialogTitle>
          <DialogDescription>
            프롬프트의 구성 요소와 설정 내역을 확인합니다.
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-[70vh] p-6">
          {selectedPrompt && (
            <div className="space-y-8">
              {/* 이름 및 카테고리 */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">프롬프트명</Label>
                  <p className="font-bold flex items-center gap-2">
                    {selectedPrompt.name}
                    <Badge variant={selectedPrompt.is_active ? 'default' : 'secondary'} className="h-5 text-[10px] rounded-sm font-black">
                      {selectedPrompt.is_active ? 'ACTIVE' : 'INACTIVE'}
                    </Badge>
                  </p>
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">카테고리</Label>
                  <div>
                    <Badge variant="outline" className="rounded-md border-primary/20 text-primary bg-primary/5 font-bold">
                      {PROMPT_CATEGORIES.find(c => c.value === selectedPrompt.category)?.label || selectedPrompt.category}
                    </Badge>
                  </div>
                </div>
              </div>

              {/* 설명 */}
              <div className="space-y-1">
                <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">설명</Label>
                <p className="text-sm text-foreground/80 leading-relaxed">{selectedPrompt.description || '설명이 없습니다.'}</p>
              </div>

              {/* 생성일/수정일 */}
              <div className="grid grid-cols-2 gap-4 pt-2">
                <div className="space-y-1">
                  <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">생성일</Label>
                  <p className="text-xs font-medium text-muted-foreground italic">{new Date(selectedPrompt.created_at).toLocaleString('ko-KR')}</p>
                </div>
                <div className="space-y-1">
                  <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">수정일</Label>
                  <p className="text-xs font-medium text-muted-foreground italic">{new Date(selectedPrompt.updated_at).toLocaleString('ko-KR')}</p>
                </div>
              </div>

              {/* 프롬프트 본문 */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">프롬프트 본문</Label>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-[10px] px-2 rounded-lg font-bold gap-1"
                    onClick={() => {
                      navigator.clipboard.writeText(selectedPrompt.content);
                    }}
                  >
                    <Copy className="w-3 h-3" /> 복사
                  </Button>
                </div>
                <div className="p-4 bg-muted/50 rounded-2xl border border-border/40 min-h-[100px] overflow-auto">
                  <pre className="text-xs font-mono leading-relaxed whitespace-pre-wrap break-all opacity-80 select-all">
                    {selectedPrompt.content}
                  </pre>
                </div>
              </div>
            </div>
          )}
        </ScrollArea>

        {/* 하단 버튼 */}
        <DialogFooter className="p-6 border-t border-border/40 bg-muted/10">
          <Button variant="ghost" onClick={() => onOpenChange(false)} className="rounded-xl font-bold">
            닫기
          </Button>
          {selectedPrompt && (
            <Button
              onClick={() => {
                onOpenChange(false);
                onEdit(selectedPrompt);
              }}
              className="rounded-xl font-bold gap-2 px-8"
            >
              <Edit2 className="w-4 h-4" />
              프롬프트 수정
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
