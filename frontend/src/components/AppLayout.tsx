import React, { useState, useEffect } from 'react';
import { Sidebar } from './Sidebar';
import { PageHeader } from './PageHeader';
import { useLocation, useNavigate } from 'react-router-dom';
import { healthAPI } from '../services/api';
import { removeAdminAccess } from '../utils/accessControl';
import { useConfig } from '../core/useConfig';
import { Toaster } from '@/components/ui/toaster';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { cn } from '@/lib/utils';

interface AppLayoutProps {
  children: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({ children }) => {
  const { config } = useConfig();
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    const saved = localStorage.getItem('sidebarOpen');
    return saved ? JSON.parse(saved) : true;
  });
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('darkMode');
    return saved ? JSON.parse(saved) : false;
  });
  const [serverStatus, setServerStatus] = useState<'healthy' | 'unhealthy' | 'checking'>('checking');
  const location = useLocation();
  const navigate = useNavigate();

  // 반응형: 화면이 좁아지면 메인 사이드바 자동 닫기
  const isSmallScreen = useMediaQuery('(max-width: 768px)');

  // 서버 상태 확인
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await healthAPI.check();
        setServerStatus(response.data.status === 'OK' ? 'healthy' : 'unhealthy');
      } catch {
        setServerStatus('unhealthy');
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 30000);

    return () => clearInterval(interval);
  }, []);

  // 사이드바 상태 저장
  useEffect(() => {
    localStorage.setItem('sidebarOpen', JSON.stringify(sidebarOpen));
  }, [sidebarOpen]);

  // 반응형: 화면이 좁아지면 메인 사이드바 자동 닫기
  useEffect(() => {
    if (isSmallScreen && sidebarOpen) {
      setSidebarOpen(false);
    }
  }, [isSmallScreen, sidebarOpen]);

  // 다크모드 토글
  const toggleDarkMode = () => {
    const newMode = !darkMode;
    setDarkMode(newMode);
    localStorage.setItem('darkMode', JSON.stringify(newMode));
    if (newMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  };

  // 초기 다크모드 적용
  useEffect(() => {
    const savedMode = localStorage.getItem('darkMode');
    const isDark = savedMode ? JSON.parse(savedMode) : false;
    setDarkMode(isDark);
    if (isDark) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, []);

  const handleLogout = () => {
    removeAdminAccess();
    window.location.href = '/bot';
  };

  const handleMenuClick = (path: string) => {
    navigate(path);
  };

  // 현재 페이지 이름 추출
  const getCurrentPageName = () => {
    const path = location.pathname;
    if (path === '/bot') return '챗봇';
    if (path === '/upload') return '문서 관리';
    if (path === '/prompts') return '프롬프트';
    if (path === '/admin') return '관리자 대시보드';
    return '';
  };

  const pageName = getCurrentPageName();

  // 사이드바 너비 계산 (Tailwind 클래스로 처리 권장되지만 미세조정용)
  const sidebarWidth = isSmallScreen ? 0 : (sidebarOpen ? config.layout.sidebar.width : config.layout.sidebar.collapsedWidth);

  return (
    <div className="flex min-h-screen bg-background text-foreground transition-colors duration-300">
      <Sidebar
        open={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
      />

      <main
        className={cn(
          "flex-grow flex flex-col min-w-0 transition-all duration-300 ease-in-out",
          !isSmallScreen && sidebarOpen ? `ml-[${config.layout.sidebar.width}px]` : !isSmallScreen ? `ml-[${config.layout.sidebar.collapsedWidth}px]` : "ml-0"
        )}
        style={{
          marginLeft: !isSmallScreen ? `${sidebarWidth}px` : undefined
        }}
      >
        {pageName && (
          <PageHeader
            pageName={pageName}
            darkMode={darkMode}
            serverStatus={serverStatus}
            onToggleDarkMode={toggleDarkMode}
            onLogout={handleLogout}
            onMenuClick={handleMenuClick}
            showNavigation={false}
          />
        )}

        <div className="flex-grow flex flex-col p-4 md:p-6 bg-muted/20">
          {children}
        </div>
      </main>

      <Toaster />
    </div>
  );
};

export default AppLayout;

