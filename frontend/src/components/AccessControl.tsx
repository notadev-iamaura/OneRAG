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

interface AccessControlProps {
  isOpen: boolean;
  onAccessGranted: () => void;
  onCancel: () => void;
  title?: string;
}

// Railway 환경변수에서 접근코드를 가져오기
const getAccessCode = () => {
  // Railway 런타임 설정 확인
  if (typeof window !== 'undefined' && window.RUNTIME_CONFIG?.ACCESS_CODE) {
    logger.log('Railway 런타임 접근코드 사용');
    return window.RUNTIME_CONFIG.ACCESS_CODE;
  }

  // 개발 환경에서만 .env 파일 사용
  if (import.meta.env.MODE === 'development' && import.meta.env.VITE_ACCESS_CODE) {
    logger.log('개발 환경 접근코드 사용');
    return import.meta.env.VITE_ACCESS_CODE;
  }

  // 기본값
  logger.log('⚠️ 환경변수 없음 - 기본값 사용');
  return '1127';
};

const ACCESS_CODE = getAccessCode();

export function AccessControl({ isOpen, onAccessGranted, onCancel, title = "관리자 접근" }: AccessControlProps) {
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

    if (code === ACCESS_CODE) {
      // 세션에 접근 권한 저장
      setAdminAccess();
      onAccessGranted();
    } else {
      setError('잘못된 접근코드입니다.');
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
            {title}
          </DialogTitle>
          <DialogDescription className="text-muted-foreground mt-2">
            이 페이지에 접근하려면 접근코드를 입력하세요.
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
              placeholder="접근코드를 입력하세요"
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
              취소
            </Button>
            <Button
              type="submit"
              className="flex-1 sm:flex-none h-11 px-8 rounded-xl font-bold shadow-lg shadow-primary/20 hover:scale-[1.02] active:scale-[0.98] transition-all"
            >
              확인
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}


