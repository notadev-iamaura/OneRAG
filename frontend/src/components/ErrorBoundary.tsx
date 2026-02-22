import React, { Component, ErrorInfo, ReactNode } from 'react';
import { logger } from '../utils/logger';
import { RotateCcw, Bug, ArrowLeft, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
  errorInfo?: ErrorInfo;
}

class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    logger.error('ErrorBoundary caught an error:', error, errorInfo);
    this.setState({ error, errorInfo });

    // Chunk load 실패 감지 (Code Splitting 오류)
    const isChunkLoadError =
      error.name === 'ChunkLoadError' ||
      error.message.includes('Loading chunk') ||
      error.message.includes('Failed to fetch dynamically imported module');

    // Chunk load 실패 시 자동 새로고침 (최대 1회)
    if (isChunkLoadError && !sessionStorage.getItem('chunk-load-retry')) {
      sessionStorage.setItem('chunk-load-retry', 'true');
      logger.warn('⚠️ Chunk load 실패 감지 - 페이지 새로고침 시도');
      window.location.reload();
      return;
    }

    // 오류 로깅 (운영환경에서는 외부 서비스로 전송)
    if (import.meta.env.PROD) {
      // 오류 리포팅 서비스에 전송
      logger.error('Production error:', {
        error: error.toString(),
        stack: error.stack,
        componentStack: errorInfo.componentStack,
        timestamp: new Date().toISOString(),
        userAgent: navigator.userAgent,
        url: window.location.href,
        isChunkLoadError,
      });
    }

    // 새로고침 후 오류 재발 시 retry 플래그 제거
    sessionStorage.removeItem('chunk-load-retry');
  }

  handleReset = () => {
    // 단순 상태 리셋보다는 전체 페이지 새로고침이 런타임 오류(상수 미정의 등) 복구에 더 효과적입니다.
    window.location.reload();
  };

  handleGoBack = () => {
    // 브라우저 히스토리가 있으면 이전 페이지로, 없으면 홈페이지로
    if (window.history.length > 1) {
      window.history.back();
    } else {
      window.location.href = '/';
    }
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="flex items-center justify-center min-h-[60vh] p-6 bg-background animate-in fade-in duration-500">
          <Card className="max-w-xl w-full border-border/60 shadow-xl overflow-hidden">
            <CardHeader className="text-center pb-2">
              <div className="flex justify-center mb-4">
                <div className="p-4 rounded-full bg-destructive/10">
                  <Bug className="h-10 w-10 text-destructive" />
                </div>
              </div>
              <CardTitle className="text-2xl font-bold text-foreground">
                오류가 발생했습니다
              </CardTitle>
              <CardDescription className="text-muted-foreground mt-2">
                예상치 못한 오류가 발생했습니다. 아래 버튼을 클릭하여 다시 시도해주세요.
              </CardDescription>
            </CardHeader>

            <CardContent className="pt-4">
              {import.meta.env.DEV && this.state.error && (
                <Alert variant="destructive" className="bg-destructive/5 border-destructive/20 text-destructive text-left overflow-auto max-h-[200px]">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle className="text-sm font-bold">Error Detail</AlertTitle>
                  <AlertDescription>
                    <pre className="text-[11px] font-mono whitespace-pre-wrap mt-2">
                      {this.state.error.toString()}
                      {this.state.error.stack && (
                        <>
                          {'\n\n'}
                          {this.state.error.stack}
                        </>
                      )}
                    </pre>
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>

            <CardFooter className="flex flex-col sm:flex-row gap-3 justify-center pb-8">
              <Button
                onClick={this.handleReset}
                className="gap-2 font-bold min-w-[140px] rounded-xl shadow-md shadow-primary/20"
                title="현재 화면을 초기화하고 다시 로드합니다"
              >
                <RotateCcw className="h-4 w-4" />
                화면 새로고침 (초기화)
              </Button>
              <Button
                variant="outline"
                onClick={this.handleGoBack}
                className="gap-2 font-bold min-w-[140px] rounded-xl border-border/60"
              >
                <ArrowLeft className="h-4 w-4" />
                이전으로 돌아가기
              </Button>
            </CardFooter>

            <div className="text-center pb-6">
              <p className="text-[11px] text-muted-foreground/60 font-medium tracking-tight">
                문제가 지속되면 관리자에게 문의해주세요.
              </p>
            </div>
          </Card>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
