import React from 'react';
import {
  Sun,
  Moon,
  UploadCloud,
  MessageSquare,
  BrainCircuit,
  BarChart3,
  LogOut,
  CheckCircle,
  HelpCircle,
  AlertTriangle,
} from 'lucide-react';
import { useIsDarkMode } from '../hooks/useIsDarkMode';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { BRAND_CONFIG } from '../config/brand';
import { BrandLogo } from './icons/BrandLogo';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface PageHeaderProps {
  pageName?: string;
  darkMode?: boolean;
  serverStatus: 'healthy' | 'unhealthy' | 'checking';
  onToggleDarkMode: () => void;
  onLogout: () => void;
  onMenuClick: (path: string) => void;
  showNavigation?: boolean;
  navigationItems?: Array<{
    label: string;
    path: string;
    icon: React.ElementType;
  }>;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  serverStatus,
  onToggleDarkMode,
  onLogout,
  onMenuClick,
  showNavigation = true,
  navigationItems,
}) => {
  const isDark = useIsDarkMode();

  const defaultNavigationItems = [
    { label: '챗봇', path: '/bot', icon: MessageSquare },
    { label: '업로드', path: '/upload', icon: UploadCloud },
    { label: '프롬프트', path: '/prompts', icon: BrainCircuit },
    { label: '통계', path: '/analysis', icon: BarChart3 },
  ];

  const items = navigationItems || defaultNavigationItems;

  const StatusBadge = () => {
    switch (serverStatus) {
      case 'healthy':
        return (
          <Badge variant="outline" className="bg-emerald-500/10 text-emerald-500 border-emerald-500/30 gap-1.5 font-bold py-1 px-3 rounded-full transition-all hover:bg-emerald-500/20">
            <CheckCircle className="w-3.5 h-3.5" />
            정상
          </Badge>
        );
      case 'checking':
        return (
          <Badge variant="outline" className="bg-amber-500/10 text-amber-500 border-amber-500/30 gap-1.5 font-bold py-1 px-3 rounded-full transition-all hover:bg-amber-500/20">
            <HelpCircle className="w-3.5 h-3.5 animate-pulse" />
            확인중
          </Badge>
        );
      case 'unhealthy':
        return (
          <Badge variant="outline" className="bg-destructive/10 text-destructive border-destructive/30 gap-1.5 font-bold py-1 px-3 rounded-full transition-all hover:bg-destructive/20">
            <AlertTriangle className="w-3.5 h-3.5" />
            오류
          </Badge>
        );
      default:
        return null;
    }
  };

  return (
    <TooltipProvider>
      <header className="sticky top-0 z-[100] w-full border-b border-border/40 bg-background/60 backdrop-blur-2xl supports-[backdrop-filter]:bg-background/40 shadow-sm transition-all duration-300">
        <div className="flex h-16 items-center px-6 gap-4 max-w-[1440px] mx-auto">
          {/* 브랜드 타이틀 */}
          <div className="flex-1 flex items-center min-w-0 group cursor-default">
            <div className="relative mr-3 shrink-0">
              <BrandLogo width={30} height={30} className="relative z-10 transition-transform duration-500 group-hover:rotate-12 group-hover:scale-110" />
              <div className="absolute inset-x-0 inset-y-0 bg-primary/20 blur-lg rounded-full -z-10 opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
            </div>
            <h1 className="text-xl font-black tracking-tighter text-gradient truncate leading-none pt-0.5">
              {BRAND_CONFIG.appName}
            </h1>
          </div>

          {/* 네비게이션 */}
          {showNavigation && (
            <nav className="hidden lg:flex items-center gap-1 mx-4 p-1 px-1.5 bg-muted/30 rounded-2xl border border-border/40">
              {items.map((item) => {
                const Icon = item.icon;
                return (
                  <Button
                    key={item.path}
                    variant="ghost"
                    size="sm"
                    onClick={() => onMenuClick(item.path)}
                    className="gap-2 font-bold hover:bg-background hover:shadow-sm rounded-xl transition-all h-8 px-4"
                  >
                    <Icon className="w-4 h-4 opacity-60" />
                    <span className="text-xs">{item.label}</span>
                  </Button>
                );
              })}
            </nav>
          )}

          {/* 우측 액션 섹션 */}
          <div className="flex items-center gap-2 ml-auto">
            <div className="mr-2">
              <StatusBadge />
            </div>

            <div className="h-4 w-px bg-border/40 mx-2 hidden sm:block" />

            {/* 로그아웃 */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onLogout}
                  className="h-9 w-9 rounded-xl hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-all duration-300 active:scale-90"
                >
                  <LogOut className="w-[18px] h-[18px]" />
                </Button>
              </TooltipTrigger>
              <TooltipContent className="glass-morphism border-border/40 text-foreground font-bold text-xs rounded-xl px-3 py-1.5">
                로그아웃
              </TooltipContent>
            </Tooltip>

            {/* 다크모드 토글 */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onToggleDarkMode}
                  className="h-9 w-9 rounded-xl hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-all duration-300 active:scale-90"
                >
                  <div className="relative w-full h-full flex items-center justify-center overflow-hidden">
                    {isDark ? (
                      <Sun className="w-[18px] h-[18px] animate-in slide-in-from-top-full duration-500" />
                    ) : (
                      <Moon className="w-[18px] h-[18px] animate-in slide-in-from-bottom-full duration-500" />
                    )}
                  </div>
                </Button>
              </TooltipTrigger>
              <TooltipContent className="glass-morphism border-border/40 text-foreground font-bold text-xs rounded-xl px-3 py-1.5">
                {isDark ? "라이트 모드" : "다크 모드"}
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </header>
    </TooltipProvider>
  );
};

export default PageHeader;
