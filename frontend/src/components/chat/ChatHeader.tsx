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
    return (
        <header className="px-6 py-4 border-b bg-gradient-to-r from-background to-muted/10 relative overflow-hidden backdrop-blur-sm">
            <div className="flex justify-between items-center relative z-10">
                <div className="flex flex-col">
                    <h1 className="text-xl font-bold tracking-tight leading-tight">OneRAG Chat</h1>
                    <p className="text-sm text-muted-foreground">- 궁금한 것을 질문해주세요!</p>
                </div>

                <div className="flex items-center gap-2">
                    {!sessionId.startsWith('id-12345') && (
                        <Badge variant="secondary" className="hidden sm:flex gap-1.5 items-center px-3 py-1 font-medium border-border/50 shrink-0">
                            <Code className="w-4 h-4 text-primary/70" />
                            <span className="text-xs opacity-80">
                                세션: {sessionId.replace('fallback-', '').slice(0, 8)}...
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
                                        title="개발자 도구 보기"
                                    >
                                        <Eye className="w-5 h-5" />
                                    </Button>
                                </TooltipTrigger>
                                <TooltipContent className="glass-morphism border-border/40 text-foreground font-bold text-xs rounded-xl px-3 py-1.5">
                                    개발자 도구 보기
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
                                    title="새 대화 시작"
                                >
                                    <Trash2 className="w-5 h-5" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent className="glass-morphism border-border/40 text-foreground font-bold text-xs rounded-xl px-3 py-1.5">
                                새 대화 시작
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
            </div>
        </header>
    );
};

