import React from 'react';
import {
  MessageSquare,
  UploadCloud,
  BrainCircuit,
  BarChart3,
  Settings,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useConfig } from '../core/useConfig';
import { useIsModuleEnabled } from '../core/useFeature';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { cn } from '@/lib/utils';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Button } from '@/components/ui/button';
import { BrandLogo } from './icons/BrandLogo';
import { BRAND_CONFIG } from '../config/brand';

interface SidebarProps {
  open: boolean;
  onToggle: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ open, onToggle }) => {
  const { config } = useConfig();
  const navigate = useNavigate();
  const location = useLocation();

  // 반응형: 작은 화면 감지
  const isSmallScreen = useMediaQuery('(max-width: 640px)'); // sm 사이즈 이하

  const isChatbotEnabled = useIsModuleEnabled('chatbot');
  const isDocumentsEnabled = useIsModuleEnabled('documentManagement');
  const isPromptsEnabled = useIsModuleEnabled('prompts');
  const isAnalysisEnabled = useIsModuleEnabled('analysis');
  const isAdminEnabled = useIsModuleEnabled('admin');

  const menuItems = [
    {
      label: '챗봇',
      path: '/bot',
      icon: MessageSquare,
      enabled: isChatbotEnabled
    },
    {
      label: '문서 관리',
      path: '/upload',
      icon: UploadCloud,
      enabled: isDocumentsEnabled
    },
    {
      label: '프롬프트',
      path: '/prompts',
      icon: BrainCircuit,
      enabled: isPromptsEnabled
    },
    {
      label: '통계',
      path: '/analysis',
      icon: BarChart3,
      enabled: isAnalysisEnabled
    },
    {
      label: '관리자',
      path: '/admin',
      icon: Settings,
      enabled: isAdminEnabled
    },
  ].filter(item => item.enabled);

  const handleMenuClick = (path: string) => {
    navigate(path);
    if (isSmallScreen && open) {
      onToggle();
    }
  };

  // 사이드바 너비
  const drawerWidth = config.layout.sidebar.width;
  const collapsedWidth = config.layout.sidebar.collapsedWidth;

  return (
    <TooltipProvider delayDuration={0}>
      {/* 모바일 오버레이 */}
      {isSmallScreen && open && (
        <div
          className="fixed inset-0 bg-black/40 backdrop-blur-[2px] z-[100] animate-in fade-in duration-300"
          onClick={onToggle}
        />
      )}

      {/* 사이드바 컨테이너 */}
      <aside
        style={{ width: open ? drawerWidth : collapsedWidth }}
        className={cn(
          "h-screen flex flex-col bg-background border-r border-border transition-all duration-300 ease-in-out z-[110]",
          isSmallScreen ? "fixed top-0 left-0" : "relative shrink-0",
          isSmallScreen && !open && "translate-x-[-100%]"
        )}
      >
        {/* 헤더 섹션 */}
        <div className={cn(
          "flex items-center h-14 px-3 border-b border-border/60 transition-all",
          open ? "justify-between" : "justify-center"
        )}>
          <div className={cn(
            "flex items-center gap-2 overflow-hidden transition-all",
            open ? "flex-1" : "justify-center"
          )}>
            <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-primary/5 flex items-center justify-center">
              <BrandLogo width={22} height={22} className="shrink-0" />
            </div>
            {open && (
              <span className="font-bold text-sm text-foreground truncate animate-in fade-in slide-in-from-left-2 duration-300">
                {BRAND_CONFIG.appName}
              </span>
            )}
          </div>

          {open && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 rounded-md hover:bg-muted shrink-0 text-muted-foreground transition-all"
              onClick={onToggle}
              aria-label="사이드바 축소"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
          )}
        </div>

        {/* 메뉴 리스트 */}
        <nav className="flex-1 overflow-y-auto overflow-x-hidden p-2 space-y-1 scrollbar-none">
          {menuItems.map((item) => {
            const isActive = location.pathname === item.path;
            const Icon = item.icon;

            return (
              <div key={item.path}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      onClick={() => handleMenuClick(item.path)}
                      className={cn(
                        "w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 group relative",
                        isActive
                          ? "bg-primary text-primary-foreground shadow-md shadow-primary/20"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground",
                        !open && "justify-center px-0"
                      )}
                    >
                      <Icon className={cn(
                        "h-[20px] w-[20px] shrink-0 transition-transform duration-300 group-hover:scale-110",
                        isActive ? "text-primary-foreground" : "text-muted-foreground group-hover:text-foreground"
                      )} />

                      {open && (
                        <span className="text-[14px] font-semibold truncate animate-in fade-in slide-in-from-left-2 duration-300">
                          {item.label}
                        </span>
                      )}

                      {isActive && !open && (
                        <div className="absolute left-0 w-1 h-5 bg-primary-foreground rounded-r-full" />
                      )}
                    </button>
                  </TooltipTrigger>
                  {!open && (
                    <TooltipContent side="right" className="font-bold">
                      {item.label}
                    </TooltipContent>
                  )}
                </Tooltip>
              </div>
            );
          })}
        </nav>

        {/* 푸터 / 접혔을 때 열기 버튼 */}
        <div className={cn(
          "p-2 border-t border-border/40 min-h-[50px] flex items-center justify-center transition-all",
          !open ? "opacity-100" : "opacity-0 pointer-events-none"
        )}>
          {!open && (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 rounded-full border border-border/60 bg-background/50 hover:bg-primary/10 hover:text-primary hover:border-primary/30 transition-all shadow-sm"
              onClick={onToggle}
              aria-label="사이드바 확장"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          )}
        </div>
      </aside>

      {/* 닫혀있을 때의 부유형 플로팅 토글 (사이드바가 Relative일 때 보완) */}
      {!open && !isSmallScreen && (
        <div className="fixed top-12 left-2 z-[105] opacity-0 group/toggle hover:opacity-100 transition-opacity">
          <Button
            variant="secondary"
            size="icon"
            className="h-8 w-8 rounded-full shadow-lg border border-border"
            onClick={onToggle}
            aria-label="사이드바 플로팅 확장"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </TooltipProvider>
  );
};

export default Sidebar;

