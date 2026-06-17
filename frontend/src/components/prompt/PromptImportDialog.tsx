/**
 * 프롬프트 가져오기 다이얼로그 컴포넌트
 *
 * JSON 형식의 프롬프트 데이터를 가져오는 다이얼로그입니다.
 * JSON 텍스트 입력 필드와 중복 시 덮어쓰기 옵션을 제공합니다.
 *
 * Props:
 * - open: 다이얼로그 열림 상태
 * - onOpenChange: 다이얼로그 열림 상태 변경 핸들러
 * - importData: JSON 데이터 문자열
 * - importOverwrite: 덮어쓰기 여부
 * - onImportDataChange: JSON 데이터 변경 핸들러
 * - onImportOverwriteChange: 덮어쓰기 상태 변경 핸들러
 * - onImport: 가져오기 실행 핸들러
 */

import React from 'react';
import { Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Switch } from '@/components/ui/switch';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useMenuMessages } from '../../i18n/useMenuLocale';

export interface PromptImportDialogProps {
  /** 다이얼로그 열림 상태 */
  open: boolean;
  /** 다이얼로그 열림 상태 변경 핸들러 */
  onOpenChange: (open: boolean) => void;
  /** JSON 데이터 문자열 */
  importData: string;
  /** 덮어쓰기 여부 */
  importOverwrite: boolean;
  /** JSON 데이터 변경 핸들러 */
  onImportDataChange: (data: string) => void;
  /** 덮어쓰기 상태 변경 핸들러 */
  onImportOverwriteChange: (overwrite: boolean) => void;
  /** 가져오기 실행 핸들러 */
  onImport: () => void;
}

export const PromptImportDialog: React.FC<PromptImportDialogProps> = ({
  open,
  onOpenChange,
  importData,
  importOverwrite,
  onImportDataChange,
  onImportOverwriteChange,
  onImport,
}) => {
  const { messages } = useMenuMessages();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl overflow-hidden p-0 rounded-3xl border-none">
        <DialogHeader className="p-6 pb-0">
          <DialogTitle className="text-xl font-bold">{messages.promptImport.title}</DialogTitle>
          <DialogDescription>
            {messages.promptImport.description}
          </DialogDescription>
        </DialogHeader>

        <div className="p-6 space-y-6">
          {/* 안내 메시지 */}
          <Alert className="bg-primary/5 border-none text-primary/80 rounded-2xl p-4">
            <Info className="h-4 w-4" />
            <AlertDescription className="text-xs font-medium">
              {messages.promptImport.infoNotice}
            </AlertDescription>
          </Alert>

          {/* JSON 입력 영역 */}
          <div className="space-y-2">
            <Label className="text-sm font-bold">{messages.promptImport.jsonLabel}</Label>
            <Textarea
              placeholder='{"prompts": [...], "exported_at": "...", "total": 0}'
              value={importData}
              onChange={(e) => onImportDataChange(e.target.value)}
              className="min-h-[250px] font-mono text-xs rounded-xl border-border/60"
            />
          </div>

          {/* 덮어쓰기 옵션 */}
          <div className="flex items-center justify-between p-4 bg-muted/30 rounded-2xl border border-border/40">
            <div className="space-y-0.5">
              <Label className="text-sm font-bold">{messages.promptImport.overwriteLabel}</Label>
              <p className="text-xs text-muted-foreground font-medium italic">{messages.promptImport.overwriteHelp}</p>
            </div>
            <Switch
              checked={importOverwrite}
              onCheckedChange={onImportOverwriteChange}
            />
          </div>
        </div>

        {/* 하단 버튼 */}
        <DialogFooter className="p-6 border-t border-border/40 bg-muted/10">
          <Button variant="ghost" onClick={() => onOpenChange(false)} className="rounded-xl font-bold">
            {messages.common.cancel}
          </Button>
          <Button
            onClick={onImport}
            disabled={!importData.trim()}
            className="rounded-xl font-bold px-10 shadow-lg shadow-primary/20"
          >
            {messages.promptImport.importButton}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
