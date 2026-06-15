import React from 'react';
import { Code, Eye, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import { useMenuMessages } from '../../i18n/useMenuLocale';

interface ChatHeaderProps {
    sessionId: string;
    showDevTools: boolean;
    setShowDevTools: (show: boolean) => void;
    onNewSession: () => void;
}

export const ChatHeader: React.FC<ChatHeaderProps> = ({
    sessionId,
    showDevTools,
    setShowDevTools,
    onNewSession,
}) => {
    // i18n: 현재 로케일 메시지 + 로케일 전환 함수
    const { messages, locale, setLocale } = useMenuMessages();

    return (
        <header className="px-6 py-4 border-b bg-gradient-to-r from-background to-muted/10 relative overflow-hidden backdrop-blur-sm">
            <div className="flex justify-between items-center relative z-10">
                <div className="flex flex-col">
                    <h1 className="text-xl font-bold tracking-tight leading-tight">{messages.chat.header.title}</h1>
                    <p className="text-sm text-muted-foreground">{messages.chat.header.subtitle}</p>
                </div>

                <div className="flex items-center gap-2">
                    {/* 언어 셀렉터: localStorage + CustomEvent 기반 i18n 레이어와 연결 */}
                    <select
                        aria-label={messages.language.select}
                        title={messages.language.select}
                        value={locale}
                        onChange={(e) => setLocale(e.target.value === 'en' ? 'en' : 'ko')}
                        className="h-8 rounded-lg border border-border/50 bg-muted/30 px-2 text-xs font-medium text-foreground hover:bg-muted/50 transition-colors cursor-pointer shrink-0"
                    >
                        <option value="ko">{messages.language.ko}</option>
                        <option value="en">{messages.language.en}</option>
                    </select>

                    {!sessionId.startsWith('id-12345') && (
                        <Badge variant="secondary" className="hidden sm:flex gap-1.5 items-center px-3 py-1 font-medium border-border/50 shrink-0">
                            <Code className="w-4 h-4 text-primary/70" />
                            <span className="text-xs opacity-80">
                                {messages.chat.header.sessionPrefix}: {sessionId.replace('fallback-', '').slice(0, 8)}...
                            </span>
                        </Badge>
                    )}

                    {!showDevTools && (
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        onClick={() => setShowDevTools(true)}
                                        className="rounded-xl hover:bg-muted transition-all duration-200 shrink-0"
                                        title={messages.chat.header.showDevTools}
                                    >
                                        <Eye className="w-5 h-5" />
                                    </Button>
                                </TooltipTrigger>
                                <TooltipContent className="glass-morphism border-border/40 text-foreground font-bold text-xs rounded-xl px-3 py-1.5">
                                    {messages.chat.header.showDevTools}
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    )}

                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={onNewSession}
                                    className="rounded-xl hover:bg-destructive/10 hover:text-destructive transition-all duration-300 shrink-0"
                                    title={messages.chat.header.newSession}
                                >
                                    <Trash2 className="w-5 h-5" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent className="glass-morphism border-border/40 text-foreground font-bold text-xs rounded-xl px-3 py-1.5">
                                {messages.chat.header.newSession}
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
            </div>
        </header>
    );
};

