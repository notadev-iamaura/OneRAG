/**
 * 프롬프트 편집/생성 다이얼로그 컴포넌트
 *
 * 프롬프트의 생성(Create) 및 편집(Edit) 모드를 지원하는 다이얼로그입니다.
 * 이름, 설명, 카테고리, 내용, 활성화 상태를 입력/수정할 수 있습니다.
 *
 * Props:
 * - open: 다이얼로그 열림 상태
 * - onOpenChange: 다이얼로그 열림 상태 변경 핸들러
 * - editingPrompt: 편집 중인 프롬프트 데이터
 * - isEditMode: 편집 모드 여부 (false면 생성 모드)
 * - selectedPrompt: 편집 시 원본 프롬프트 (시스템 프롬프트 이름 변경 방지용)
 * - modalError: 모달 내 에러 메시지
 * - onSave: 저장 버튼 핸들러
 * - onEditingPromptChange: 편집 데이터 변경 핸들러
 */

import React from 'react';
import { Save, Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Switch } from '@/components/ui/switch';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

import type { Prompt, CreatePromptRequest, UpdatePromptRequest } from '../../types/prompt';
import { PROMPT_CATEGORIES } from '../../types/prompt';

export interface PromptEditDialogProps {
  /** 다이얼로그 열림 상태 */
  open: boolean;
  /** 다이얼로그 열림 상태 변경 핸들러 */
  onOpenChange: (open: boolean) => void;
  /** 편집 중인 프롬프트 데이터 */
  editingPrompt: CreatePromptRequest | UpdatePromptRequest | null;
  /** 편집 모드 여부 (false면 생성 모드) */
  isEditMode: boolean;
  /** 편집 시 원본 프롬프트 (시스템 프롬프트 이름 변경 방지용) */
  selectedPrompt: Prompt | null;
  /** 모달 내 에러 메시지 */
  modalError: string | null;
  /** 저장 버튼 핸들러 */
  onSave: () => void;
  /** 편집 데이터 변경 핸들러 */
  onEditingPromptChange: (prompt: CreatePromptRequest | UpdatePromptRequest) => void;
}

export const PromptEditDialog: React.FC<PromptEditDialogProps> = ({
  open,
  onOpenChange,
  editingPrompt,
  isEditMode,
  selectedPrompt,
  modalError,
  onSave,
  onEditingPromptChange,
}) => {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl overflow-hidden p-0 rounded-3xl border-none">
        <DialogHeader className="p-6 pb-0">
          <DialogTitle className="text-xl font-bold">
            {isEditMode ? '프롬프트 편집' : '새 프롬프트 생성'}
          </DialogTitle>
          <DialogDescription>
            {isEditMode ? '기존 프롬프트를 수정합니다.' : '새로운 시스템 프롬프트를 생성합니다.'}
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-[60vh] p-6 pt-2">
          {/* 모달 에러 표시 */}
          {modalError && (
            <Alert variant="destructive" className="mb-4 bg-destructive/10 text-destructive border-none rounded-2xl animate-in slide-in-from-top-2 duration-300">
              <Info className="h-4 w-4" />
              <AlertTitle className="font-bold">입력 오류</AlertTitle>
              <AlertDescription className="text-sm">{modalError}</AlertDescription>
            </Alert>
          )}

          {/* 편집 폼 */}
          {editingPrompt && (
            <div className="space-y-6 pt-0">
              {/* 프롬프트 이름 */}
              <div className="space-y-2">
                <Label htmlFor="prompt-name" className="text-sm font-bold">프롬프트 이름</Label>
                <Input
                  id="prompt-name"
                  value={editingPrompt.name || ''}
                  onChange={(e) => onEditingPromptChange({ ...editingPrompt, name: e.target.value })}
                  disabled={isEditMode && selectedPrompt?.category === 'system'}
                  className="rounded-xl border-border/60"
                  placeholder="프롬프트 명칭을 입력하세요"
                />
                {isEditMode && selectedPrompt?.category === 'system' && (
                  <p className="text-[10px] text-muted-foreground font-medium flex items-center gap-1">
                    <Info className="w-3 h-3" /> 시스템 프롬프트는 이름을 변경할 수 없습니다
                  </p>
                )}
              </div>

              {/* 설명 */}
              <div className="space-y-2">
                <Label htmlFor="prompt-desc" className="text-sm font-bold">설명</Label>
                <Input
                  id="prompt-desc"
                  value={editingPrompt.description || ''}
                  onChange={(e) => onEditingPromptChange({ ...editingPrompt, description: e.target.value })}
                  className="rounded-xl border-border/60"
                  placeholder="어떤 역할이나 페르소나인지 간단히 설명하세요"
                />
              </div>

              {/* 카테고리 */}
              <div className="space-y-2">
                <Label className="text-sm font-bold">카테고리</Label>
                <Select
                  value={editingPrompt.category || 'custom'}
                  onValueChange={(val) => onEditingPromptChange({ ...editingPrompt, category: val as 'system' | 'assistant' | 'user' | 'custom' })}
                  disabled={isEditMode && selectedPrompt?.category === 'system'}
                >
                  <SelectTrigger className="rounded-xl border-border/60">
                    <SelectValue placeholder="카테고리 선택" />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl">
                    {PROMPT_CATEGORIES.map((category) => (
                      <SelectItem key={category.value} value={category.value}>
                        {category.label} - {category.description}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* 프롬프트 내용 */}
              <div className="space-y-2">
                <Label htmlFor="prompt-content" className="text-sm font-bold">프롬프트 내용</Label>
                <Textarea
                  id="prompt-content"
                  value={editingPrompt.content || ''}
                  onChange={(e) => onEditingPromptChange({ ...editingPrompt, content: e.target.value })}
                  className="min-h-[200px] rounded-xl border-border/60 font-mono text-sm leading-relaxed"
                  placeholder="AI에게 전달할 시스템 지침을 입력하세요..."
                />
              </div>

              {/* 활성화 상태 토글 */}
              <div className="flex items-center justify-between p-4 bg-muted/30 rounded-2xl border border-border/40">
                <div className="space-y-0.5">
                  <Label className="text-sm font-bold">활성화 상태</Label>
                  <p className="text-xs text-muted-foreground font-medium">저장 시 이 프롬프트를 즉시 적용합니다.</p>
                </div>
                <Switch
                  checked={editingPrompt.is_active !== false}
                  onCheckedChange={(checked) => onEditingPromptChange({ ...editingPrompt, is_active: checked })}
                />
              </div>
            </div>
          )}
        </ScrollArea>

        {/* 하단 버튼 */}
        <DialogFooter className="p-6 border-t border-border/40 bg-muted/10">
          <Button variant="ghost" onClick={() => onOpenChange(false)} className="rounded-xl font-bold">
            취소
          </Button>
          <Button onClick={onSave} className="rounded-xl font-bold gap-2 px-8">
            <Save className="w-4 h-4" />
            저장하기
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
