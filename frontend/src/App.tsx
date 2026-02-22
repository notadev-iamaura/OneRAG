import React, { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route, useNavigate, Navigate, useLocation } from 'react-router-dom';
import { Loader2, AlertCircle, MessageSquare, UploadCloud, BrainCircuit, BarChart3, Settings } from 'lucide-react';
import ErrorBoundary from './components/ErrorBoundary';
import { AppLayout } from './components/AppLayout';
import { BRAND_CONFIG } from './config/brand';
import { FeatureProvider } from './core/FeatureProvider';
import { useIsModuleEnabled } from './core/useFeature';
import { ConfigProvider } from './core/ConfigProvider';
import { WebSocketProvider } from './core/WebSocketProvider';
import { ChatAPIProvider } from './core/ChatAPIProvider';
import { createChatAPIService } from './services/chatAPIService';
import { defaultChatAPIConfig } from './types/chatAPI';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';

// Code Splitting: 라우트별 지연 로딩
const ChatPage = lazy(() => import('./pages/ChatPage'));
const UploadPage = lazy(() => import('./pages/UploadPage'));
const PromptsPage = lazy(() => import('./pages/PromptsPage'));
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'));
const AdminDashboard = lazy(() => import('./pages/Admin/AdminDashboard'));

// 로딩 폴백 컴포넌트
function LoadingFallback() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-background animate-in fade-in duration-500">
      <div className="relative flex items-center justify-center">
        <div className="h-12 w-12 rounded-full border-4 border-primary/20 border-t-primary animate-spin" />
        <Loader2 className="absolute h-5 w-5 text-primary animate-pulse" />
      </div>
      <p className="mt-4 text-sm font-medium text-muted-foreground animate-pulse">로딩 중...</p>
    </div>
  );
}

// 랜딩 페이지 컴포넌트
function LandingPageContent() {
  const navigate = useNavigate();
  const isChatbotEnabled = useIsModuleEnabled('chatbot');
  const isDocumentsEnabled = useIsModuleEnabled('documentManagement');
  const isPromptsEnabled = useIsModuleEnabled('prompts');
  const isAnalysisEnabled = useIsModuleEnabled('analysis');
  const isAdminEnabled = useIsModuleEnabled('admin');

  // 활성화된 첫 번째 모듈로 자동 리다이렉션 (챗봇 우선)
  React.useEffect(() => {
    if (isChatbotEnabled) {
      navigate('/bot');
    } else if (isDocumentsEnabled) {
      navigate('/upload');
    } else if (isPromptsEnabled) {
      navigate('/prompts');
    } else if (isAnalysisEnabled) {
      navigate('/analysis');
    } else if (isAdminEnabled) {
      navigate('/admin');
    }
  }, [isChatbotEnabled, isDocumentsEnabled, isPromptsEnabled, isAnalysisEnabled, isAdminEnabled, navigate]);

  const enabledModules = [
    { id: 'bot', enabled: isChatbotEnabled, label: '챗봇 사용하기', icon: MessageSquare, description: 'AI 어시스턴트와 대화하세요', path: '/bot', color: 'bg-blue-500/10 text-blue-500' },
    { id: 'upload', enabled: isDocumentsEnabled, label: '문서 관리', icon: UploadCloud, description: '지식 베이스 문서를 관리합니다', path: '/upload', color: 'bg-emerald-500/10 text-emerald-500' },
    { id: 'prompts', enabled: isPromptsEnabled, label: '프롬프트 관리', icon: BrainCircuit, description: 'AI 모델의 페르소나를 설정합니다', path: '/prompts', color: 'bg-amber-500/10 text-amber-500' },
    { id: 'analysis', enabled: isAnalysisEnabled, label: '통계 분석', icon: BarChart3, description: '데이터 분석 결과를 확인합니다', path: '/analysis', color: 'bg-purple-500/10 text-purple-500' },
    { id: 'admin', enabled: isAdminEnabled, label: '관리자', icon: Settings, description: '시스템 설정을 관리합니다', path: '/admin', color: 'bg-slate-500/10 text-slate-500' },
  ].filter(m => m.enabled);

  if (enabledModules.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen p-6 bg-background space-y-4">
        <div className="p-4 rounded-full bg-destructive/10 animate-pulse">
          <AlertCircle className="h-10 w-10 text-destructive" />
        </div>
        <h2 className="text-2xl font-bold tracking-tight text-foreground">활성화된 기능이 없습니다</h2>
        <p className="text-muted-foreground font-medium">시스템 관리자에게 문의하세요</p>
      </div>
    );
  }

  return (
    <div className="relative flex flex-col items-center justify-center min-h-screen p-6 overflow-hidden bg-background">
      {/* Premium Background Grid */}
      <div className="absolute inset-0 z-0 bg-grid-black dark:bg-grid-white opacity-20 pointer-events-none" />
      <div className="absolute inset-0 z-0 bg-gradient-to-b from-background via-transparent to-background pointer-events-none" />

      {/* Entrance Animation Blobs */}
      <div className="absolute top-[-10%] right-[-10%] w-[40%] h-[40%] bg-primary/5 rounded-full blur-[120px] animate-pulse" />
      <div className="absolute bottom-[-10%] left-[-10%] w-[40%] h-[40%] bg-primary/5 rounded-full blur-[120px] animate-pulse delay-700" />

      <div className="relative z-10 text-center space-y-4 max-w-2xl mb-12 animate-in fade-in slide-in-from-top-8 duration-1000 ease-out">
        <h1 className="text-5xl md:text-7xl font-black tracking-tighter text-gradient leading-tight">
          {BRAND_CONFIG.appName}
        </h1>
        <p className="text-xl text-muted-foreground font-medium tracking-tight">
          어떤 서비스를 이용하시겠습니까?
        </p>
      </div>

      <div className="relative z-10 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 w-full max-w-5xl animate-in fade-in slide-in-from-bottom-8 duration-1000 delay-300 fill-mode-both ease-out">
        {enabledModules.map((module, index) => {
          const Icon = module.icon;
          return (
            <Card
              key={module.id}
              className={cn(
                "group transition-all duration-500 cursor-pointer overflow-hidden",
                "bg-card/40 backdrop-blur-md border border-border/40 hover:border-primary/40",
                "hover:shadow-xl hover:shadow-black/10 hover:-translate-y-2"
              )}
              style={{ animationDelay: `${500 + (index * 100)}ms` }}
              onClick={() => navigate(module.path)}
            >
              <CardHeader className="flex flex-row items-center gap-4 pb-2">
                <div className={cn(
                  "p-4 rounded-[20px] transition-all duration-500 group-hover:scale-110 group-hover:rotate-6",
                  module.color
                )}>
                  <Icon className="h-6 w-6" />
                </div>
                <div className="space-y-0.5">
                  <CardTitle className="text-lg font-bold group-hover:text-primary transition-colors">
                    {module.label}
                  </CardTitle>
                  <CardDescription className="text-sm font-medium opacity-80">
                    {module.description}
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <div className="h-1.5 w-full bg-muted/20 rounded-full overflow-hidden mt-2">
                  <div className="h-full w-0 group-hover:w-full bg-primary/40 transition-all duration-700 ease-out rounded-full" />
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

/**
 * ProtectedRoute - Feature Flag 기반 라우트 보호 컴포넌트
 * 모듈이 비활성화되어 있으면 404 페이지로 리다이렉션
 */
interface ProtectedRouteProps {
  module: 'chatbot' | 'documentManagement' | 'prompts' | 'analysis' | 'admin';
  children: React.ReactNode;
}

function ProtectedRoute({ module, children }: ProtectedRouteProps) {
  const isEnabled = useIsModuleEnabled(module);

  if (!isEnabled) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

/**
 * AppRoutes - 동적 라우팅 설정 컴포넌트
 * Feature Flag에 따라 라우트를 조건부로 활성화
 */
function AppRoutes() {
  const isChatbotEnabled = useIsModuleEnabled('chatbot');
  const isDocumentsEnabled = useIsModuleEnabled('documentManagement');
  const isPromptsEnabled = useIsModuleEnabled('prompts');
  const isAnalysisEnabled = useIsModuleEnabled('analysis');
  const isAdminEnabled = useIsModuleEnabled('admin');
  const location = useLocation();

  return (
    <Routes>
      {/* 기본 경로 - 랜딩 페이지 */}
      <Route path="/" element={<LandingPageContent />} />

      {/* 챗봇 라우트 (조건부) */}
      {isChatbotEnabled && (
        <Route
          path="/bot"
          element={
            <AppLayout>
              <ErrorBoundary key={location.pathname}>
                <ProtectedRoute module="chatbot">
                  <Suspense fallback={<LoadingFallback />}>
                    <ChatPage />
                  </Suspense>
                </ProtectedRoute>
              </ErrorBoundary>
            </AppLayout>
          }
        />
      )}

      {/* 문서 관리 라우트 (조건부) */}
      {isDocumentsEnabled && (
        <Route
          path="/upload"
          element={
            <AppLayout>
              <ErrorBoundary key={location.pathname}>
                <ProtectedRoute module="documentManagement">
                  <Suspense fallback={<LoadingFallback />}>
                    <UploadPage />
                  </Suspense>
                </ProtectedRoute>
              </ErrorBoundary>
            </AppLayout>
          }
        />
      )}

      {/* 프롬프트 관리 라우트 (조건부) */}
      {isPromptsEnabled && (
        <Route
          path="/prompts"
          element={
            <AppLayout>
              <ErrorBoundary key={location.pathname}>
                <ProtectedRoute module="prompts">
                  <Suspense fallback={<LoadingFallback />}>
                    <PromptsPage />
                  </Suspense>
                </ProtectedRoute>
              </ErrorBoundary>
            </AppLayout>
          }
        />
      )}

      {/* 분석 라우트 (조건부) */}
      {isAnalysisEnabled && (
        <Route
          path="/analysis"
          element={
            <AppLayout>
              <ErrorBoundary key={location.pathname}>
                <ProtectedRoute module="analysis">
                  <Suspense fallback={<LoadingFallback />}>
                    <AnalysisPage />
                  </Suspense>
                </ProtectedRoute>
              </ErrorBoundary>
            </AppLayout>
          }
        />
      )}

      {/* 관리자 대시보드 (조건부) */}
      {isAdminEnabled && (
        <Route
          path="/admin"
          element={
            <AppLayout>
              <ErrorBoundary key={location.pathname}>
                <ProtectedRoute module="admin">
                  <Suspense fallback={<LoadingFallback />}>
                    <AdminDashboard />
                  </Suspense>
                </ProtectedRoute>
              </ErrorBoundary>
            </AppLayout>
          }
        />
      )}

      {/* 404 페이지 */}
      <Route path="*" element={<LandingPageContent />} />
    </Routes>
  );
}

/**
 * App - 메인 애플리케이션 컴포넌트
 *
 * Provider 계층 구조:
 * - ConfigProvider: 런타임 설정 제공 (API URL, 환경 변수 등)
 * - FeatureProvider: Feature Flag 제공 (모듈별 활성화 상태)
 * - WebSocketProvider: WebSocket DI 제공 (팩토리 및 설정)
 * - ChatAPIProvider: Chat API DI 제공 (서비스 팩토리 및 설정)
 * - Router: 라우팅 관리
 */
function App() {
  return (
    <ConfigProvider>
      <FeatureProvider>
        <WebSocketProvider>
          <ChatAPIProvider
            createService={createChatAPIService}
            config={defaultChatAPIConfig}
          >
            <Router>
              <AppRoutes />
            </Router>
          </ChatAPIProvider>
        </WebSocketProvider>
      </FeatureProvider>
    </ConfigProvider>
  );
}

export default App;

