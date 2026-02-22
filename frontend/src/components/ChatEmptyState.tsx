import React, { useState, useEffect } from 'react';
import { chatSettingsService } from '../services/chatSettingsService';
import { ChatEmptyStateSettings } from '../types';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { Sparkles } from 'lucide-react';

/**
 * 챗봇 빈 상태 컴포넌트
 * 
 * 대화가 없을 때 표시되는 미니멀하고 세련된 Empty State
 * 참고: Perplexity 스타일의 깔끔한 디자인
 */

interface SuggestionCardProps {
  text: string;
  onClick: (text: string) => void;
}

export const SuggestionCard: React.FC<SuggestionCardProps> = ({ text, onClick }) => {
  return (
    <Card
      onClick={() => onClick(text)}
      className="group relative px-4 py-3 rounded-xl border border-border/50 bg-background/50 backdrop-blur-sm cursor-pointer transition-all duration-300 hover:bg-muted/50 hover:border-primary/30 hover:shadow-md hover:-translate-y-0.5 active:scale-[0.98]"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-foreground/80 group-hover:text-foreground transition-colors leading-relaxed">
          {text}
        </span>
        <div className="h-5 w-5 rounded-full bg-primary/5 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
          <Sparkles className="h-3 w-3 text-primary/60" />
        </div>
      </div>
    </Card>
  );
};

interface ChatEmptyStateProps {
  onSuggestionClick: (text: string) => void;
}

export const ChatEmptyState: React.FC<ChatEmptyStateProps> = ({ onSuggestionClick }) => {
  // 설정 상태 관리
  const [settings, setSettings] = useState<ChatEmptyStateSettings>(
    chatSettingsService.getSettings()
  );

  // 설정 변경 감지 (localStorage 변경 이벤트 리스너)
  useEffect(() => {
    const handleStorageChange = () => {
      setSettings(chatSettingsService.getSettings());
    };

    window.addEventListener('storage', handleStorageChange);
    return () => {
      window.removeEventListener('storage', handleStorageChange);
    };
  }, []);

  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh] py-12 px-6 w-full max-w-2xl mx-auto animate-in fade-in zoom-in-95 duration-1000 ease-out">
      {/* Premium Icon Assembly */}
      <div className="mb-10 relative flex items-center justify-center transform transition-transform hover:scale-105 duration-700">
        <div className="relative w-32 h-32 flex items-center justify-center">
          <svg
            width="120"
            height="120"
            viewBox="0 0 100 100"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className="drop-shadow-2xl"
          >
            {/* 큰 4각 별 (왼쪽) */}
            <g transform="translate(35, 42)">
              <path
                d="M 0 -15 C 0 -7, -7 0, -15 0 C -7 0, 0 7, 0 15 C 0 7, 7 0, 15 0 C 7 0, 0 -7, 0 -15 Z"
                className="fill-primary"
              >
                <animateTransform
                  attributeName="transform"
                  attributeType="XML"
                  type="scale"
                  values="1;1.3;0.8;1"
                  dur="3.4s"
                  repeatCount="indefinite"
                  additive="sum"
                />
              </path>
            </g>

            {/* 중간 4각 별 (오른쪽 상단) */}
            <g transform="translate(68, 35)">
              <path
                d="M 0 -11 C 0 -5, -5 0, -11 0 C -5 0, 0 5, 0 11 C 0 5, 5 0, 11 0 C 5 0, 0 -5, 0 -11 Z"
                className="fill-primary/60"
              >
                <animateTransform
                  attributeName="transform"
                  attributeType="XML"
                  type="scale"
                  values="1;0.8;1.3;1"
                  dur="3s"
                  begin="0.4s"
                  repeatCount="indefinite"
                  additive="sum"
                />
              </path>
            </g>

            {/* 작은 4각 별 (아래) */}
            <g transform="translate(52, 65)">
              <path
                d="M 0 -7 C 0 -3, -3 0, -7 0 C -3 0, 0 3, 0 7 C 0 3, 3 0, 7 0 C 3 0, 0 -3, 0 -7 Z"
                className="fill-primary/40"
              >
                <animateTransform
                  attributeName="transform"
                  attributeType="XML"
                  type="scale"
                  values="1;0.8;1.3;0.8;1"
                  dur="3.8s"
                  begin="0.8s"
                  repeatCount="indefinite"
                  additive="sum"
                />
              </path>
            </g>
          </svg>

          {/* 블러 광채 효과 및 회전 링 */}
          <div className="absolute inset-x-0 inset-y-0 bg-primary/20 blur-[60px] rounded-full -z-10 animate-pulse" />
          <div className="absolute inset-[-20%] border-[0.5px] border-primary/10 rounded-full -z-5 animate-slow-spin" />
          <div className="absolute inset-[-40%] border-[0.5px] border-primary/5 rounded-full -z-5 animate-slow-spin direction-reverse duration-[12s]" />
        </div>
      </div>

      {/* 메인 타이틀 - Premium Outfit Typography & Gradient */}
      <h2 className="text-4xl md:text-5xl font-black text-gradient mb-4 text-center tracking-tighter leading-none">
        {settings.mainMessage}
      </h2>

      {/* 서브 타이틀 */}
      <p className="text-lg text-muted-foreground mb-12 text-center max-w-md leading-relaxed font-medium tracking-tight">
        {settings.subMessage}
      </p>

      {/* 추천 질문 섹션 - Glassmorphism UI */}
      <div className="w-full max-w-xl mt-4 animate-in slide-in-from-bottom-8 duration-1000 delay-500 fill-mode-both ease-out">
        <div className="flex items-center gap-2 md:gap-4 mb-6 px-2">
          <div className="h-px flex-1 bg-gradient-to-r from-transparent via-border/50 to-transparent" />
          <span className="text-[10px] md:text-[10px] font-black text-muted-foreground/40 uppercase tracking-[0.2em] md:tracking-[0.3em] whitespace-normal md:whitespace-nowrap text-center">
            맞춤형 추천 질문 (Personalized Suggestions)
          </span>
          <div className="h-px flex-1 bg-gradient-to-r from-transparent via-border/50 to-transparent" />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {settings.suggestions.map((suggestion, index) => (
            <Card
              key={index}
              onClick={() => onSuggestionClick(suggestion)}
              className={cn(
                "group relative px-5 py-4 cursor-pointer transition-all duration-500",
                "glass-morphism hover:bg-primary/5 hover:border-primary/30 hover:shadow-xl hover:-translate-y-1 active:scale-[0.98]",
                "min-h-[90px] flex items-center justify-center"
              )}
            >
              <div className="flex items-center justify-between gap-3 w-full">
                <span className="text-sm font-semibold text-foreground/70 group-hover:text-primary transition-colors leading-snug">
                  {suggestion}
                </span>
                <div className="h-6 w-6 rounded-xl bg-primary/5 flex items-center justify-center translate-x-1 opacity-0 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-500">
                  <Sparkles className="h-3.5 w-3.5 text-primary" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
};

export default ChatEmptyState;
