/**
 * 전체 삭제 확인 다이얼로그 컴포넌트 (2단계)
 *
 * 모든 문서를 삭제하는 위험한 작업이므로 2단계 확인 프로세스를 거칩니다:
 * 1단계 (confirm): "네, 정말 모두 삭제합니다" 버튼 클릭
 * 2단계 (typing): "문서 삭제에 동의합니다." 문구 입력 후 "전체 삭제 실행"
 */
import React from 'react';
import { AlertTriangle, RotateCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { useMenuMessages } from '../../i18n/useMenuLocale';

/** DocumentDeleteAllDialog 컴포넌트의 Props */
export interface DocumentDeleteAllDialogProps {
  /** 다이얼로그 열림 여부 */
  open: boolean;
  /** 삭제 진행 중 로딩 상태 */
  loading: boolean;
  /** 현재 단계 (confirm: 1단계, typing: 2단계) */
  step: 'confirm' | 'typing';
  /** 확인 문구 입력값 */
  typingValue: string;
  /** 확인 버튼 핸들러 (1단계→2단계 전환 또는 삭제 실행) */
  onConfirm: () => void;
  /** 취소 핸들러 */
  onCancel: () => void;
  /** 확인 문구 입력 변경 핸들러 */
  onTypingChange: (value: string) => void;
}

/**
 * 전체 삭제 2단계 확인 다이얼로그 컴포넌트
 *
 * 위험 아이콘, 경고 메시지, 그리고 단계별 버튼/입력 필드를 포함합니다.
 */
export const DocumentDeleteAllDialog: React.FC<DocumentDeleteAllDialogProps> = ({
  open,
  loading,
  step,
  typingValue,
  onConfirm,
  onCancel,
  onTypingChange,
}) => {
  // i18n: 현재 로케일에 해당하는 번역 사전을 가져온다.
  const { messages } = useMenuMessages();
  // 확인 문구: 사용자에게 표시되는 문구와 입력 검증 대상이 동일해야 하므로 로케일 사전에서 가져온다.
  const confirmPhrase = messages.docDelete.allConfirmPhrase;
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onCancel(); }}>
      <DialogContent className="rounded-[32px] max-w-md border-destructive/20">
        <DialogHeader>
          <div className="w-16 h-16 rounded-3xl bg-destructive text-white flex items-center justify-center mb-6 mx-auto shadow-2xl shadow-destructive/40 rotate-12">
            <AlertTriangle className="w-8 h-8" />
          </div>
          <DialogTitle className="text-2xl font-black text-center">{messages.docDelete.allTitle}</DialogTitle>
          <DialogDescription className="text-center font-bold text-destructive px-4">
            {messages.docDelete.allWarning}
          </DialogDescription>
        </DialogHeader>

        {step === 'typing' && (
          <div className="mt-6 space-y-4 animate-in fade-in slide-in-from-top-4">
            <p className="text-sm font-black text-center">
              {messages.docDelete.allTypingGuide}
              <br />
              <span className="text-primary mt-2 block backdrop-blur-sm bg-primary/5 p-2 rounded-lg italic">&quot;{confirmPhrase}&quot;</span>
            </p>
            <Input
              value={typingValue}
              onChange={(e) => onTypingChange(e.target.value)}
              placeholder={messages.docDelete.allTypingPlaceholder}
              className="text-center font-bold border-destructive/40 focus-visible:ring-destructive/20 rounded-xl h-12"
            />
          </div>
        )}

        <DialogFooter className="mt-8 flex-col sm:flex-col gap-3">
          <Button
            variant={step === 'confirm' ? 'destructive' : 'default'}
            className={cn("w-full h-12 rounded-xl font-black text-base shadow-xl", step === 'confirm' ? "shadow-destructive/30" : "bg-black hover:bg-zinc-800 shadow-zinc-200")}
            onClick={onConfirm}
            disabled={loading || (step === 'typing' && typingValue !== confirmPhrase)}
          >
            {loading ? <RotateCw className="w-5 h-5 mr-2 animate-spin" /> : null}
            {step === 'confirm' ? messages.docDelete.allConfirmStep : messages.docDelete.allExecuteStep}
          </Button>
          <Button variant="ghost" className="w-full font-bold h-12 rounded-xl" onClick={onCancel} disabled={loading}>
            {messages.docDelete.allCancel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
