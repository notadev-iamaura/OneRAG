import React, { useState, useEffect } from 'react';
import { Lock } from 'lucide-react';
import { setAdminAccess } from '../utils/accessControl';
import { logger } from '../utils/logger';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useMenuMessages } from '../i18n/useMenuLocale';

interface AccessControlProps {
  isOpen: boolean;
  onAccessGranted: () => void;
  onCancel: () => void;
  title?: string;
}

// 하위 호환용 기본 접근 코드 (런타임/환경변수 미설정 시 사용)
const FALLBACK_ACCESS_CODE = '1127';

/**
 * 접근 코드 결정 우선순위:
 *   1) window.RUNTIME_CONFIG.ACCESS_CODE — config.js(런타임 생성)에서 주입.
 *      재빌드 없이 배포 환경변수(ACCESS_CODE)만 바꾸면 즉시 변경 가능.
 *   2) VITE_ACCESS_CODE — 개발 모드 빌드 환경변수 (기존 동작 유지)
 *   3) FALLBACK_ACCESS_CODE — 기본값 (하위 호환)
 *
 * 모듈 로드 시점이 아니라 제출 시점에 호출해, config.js 로드 순서나
 * 테스트 환경과 무관하게 항상 최신 런타임 설정을 반영한다.
 * 앞뒤 공백을 제거(trim)해 환경변수에 섞인 공백으로 인한 인증 실패를 방지한다.
 */
const getAccessCode = (): string => {
  // 런타임 설정 확인 (빈 문자열/공백만 있는 경우는 무시하고 다음 단계로 폴백)
  const runtimeCode = typeof window !== 'undefined' ? window.RUNTIME_CONFIG?.ACCESS_CODE : undefined;
  if (typeof runtimeCode === 'string' && runtimeCode.trim().length > 0) {
    logger.log('런타임 접근코드 사용');
    return runtimeCode.trim();
  }

  // 개발 환경에서만 .env 파일 사용
  if (import.meta.env.MODE === 'development' && import.meta.env.VITE_ACCESS_CODE) {
    logger.log('개발 환경 접근코드 사용');
    return String(import.meta.env.VITE_ACCESS_CODE).trim();
  }

  // 기본값
  logger.log('⚠️ 환경변수 없음 - 기본값 사용');
  return FALLBACK_ACCESS_CODE;
};

export function AccessControl({ isOpen, onAccessGranted, onCancel, title }: AccessControlProps) {
  const { messages } = useMenuMessages();
  // 외부에서 title을 전달하면 그 값을, 미전달 시 현재 로케일 기본 라벨을 사용한다.
  const resolvedTitle = title ?? messages.accessControl.title;
  const [code, setCode] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (isOpen) {
      setCode('');
      setError('');
    }
  }, [isOpen]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // 제출 시점에 접근 코드를 평가해 최신 런타임 설정을 반영한다.
    if (code === getAccessCode()) {
      // 세션에 접근 권한 저장
      setAdminAccess();
      onAccessGranted();
    } else {
      setError(messages.accessControl.invalidCode);
      setCode('');
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="sm:max-w-md rounded-2xl p-0 overflow-hidden border-border/60 shadow-2xl animate-in zoom-in-95 duration-300">
        <DialogHeader className="p-8 pb-4 text-center items-center">
          <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center mb-4 transition-all hover:scale-110">
            <Lock className="h-7 w-7 text-primary" />
          </div>
          <DialogTitle className="text-2xl font-bold tracking-tight text-foreground">
            {resolvedTitle}
          </DialogTitle>
          <DialogDescription className="text-muted-foreground mt-2">
            {messages.accessControl.description}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="p-8 pt-4 space-y-6">
          {error && (
            <Alert variant="destructive" className="bg-destructive/10 text-destructive border-none rounded-xl animate-in slide-in-from-top-2 duration-300">
              <AlertDescription className="font-bold flex items-center gap-2">
                <span className="w-1 h-1 rounded-full bg-destructive" />
                {error}
              </AlertDescription>
            </Alert>
          )}

          <div className="space-y-4">
            <Input
              type="password"
              placeholder={messages.accessControl.placeholder}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="h-12 border-border/60 rounded-xl focus-visible:ring-primary/20 transition-all font-mono text-center tracking-widest text-lg"
              autoFocus
            />
          </div>

          <DialogFooter className="flex sm:flex-row gap-3 pt-4 sm:justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={onCancel}
              className="flex-1 sm:flex-none h-11 px-6 rounded-xl border-border/60 font-semibold hover:bg-muted"
            >
              {messages.accessControl.cancel}
            </Button>
            <Button
              type="submit"
              className="flex-1 sm:flex-none h-11 px-8 rounded-xl font-bold shadow-lg shadow-primary/20 hover:scale-[1.02] active:scale-[0.98] transition-all"
            >
              {messages.accessControl.confirm}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}


