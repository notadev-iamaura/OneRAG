import React from 'react';
import {
    Settings,
    EyeOff,
    Info,
    History,
    Terminal,
    BarChart2,
    Bug,
    ChevronUp,
    ChevronDown,
    RefreshCw,
    Copy
} from 'lucide-react';
import { SessionInfo, ApiLog } from '../../types';
import { formatModelConfigValue } from '../../utils/chat/formatters';
import { ChatbotIcon } from '../icons';
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger
} from "@/components/ui/tabs";
import {
    Card,
    CardContent,
} from "@/components/ui/card";
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger
} from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from '@/lib/utils';
import { useMenuMessages } from '../../i18n/useMenuLocale';

interface ChatDevToolsProps {
    showDevTools: boolean;
    setShowDevTools: (show: boolean) => void;
    leftPanelTab: number;
    setLeftPanelTab: (tab: number) => void;
    sessionId: string;
    sessionInfo: SessionInfo | null;
    apiLogs: ApiLog[];
    expandedLogs: Set<string>;
    toggleLogExpansion: (id: string) => void;
    isDebugExpanded: boolean;
    setIsDebugExpanded: (expanded: boolean) => void;
    handleNewSession: () => void;
    copyToClipboard: (text: string, message?: string) => void;
}

export const ChatDevTools: React.FC<ChatDevToolsProps> = ({
    showDevTools,
    setShowDevTools,
    leftPanelTab,
    setLeftPanelTab,
    sessionId,
    sessionInfo,
    apiLogs,
    expandedLogs,
    toggleLogExpansion,
    isDebugExpanded,
    setIsDebugExpanded,
    handleNewSession,
    copyToClipboard
}) => {
    // i18n: 개발자 도구 패널의 사용자 노출 라벨
    const { messages } = useMenuMessages();
    if (!showDevTools) return null;

    const modelConfigEntries = sessionInfo?.modelInfo?.model_config
        ? Object.entries(sessionInfo.modelInfo.model_config).filter(([, value]) => value !== undefined && value !== null)
        : [];

    return (
        <div className="w-[280px] min-w-[280px] h-full bg-background border-r border-border flex flex-col overflow-hidden shadow-lg animate-in slide-in-from-left duration-300">
            {/* 헤더 */}
            <div className="p-4 border-b bg-muted/30 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Settings className="h-4 w-4 text-primary" />
                    <h2 className="text-sm font-bold tracking-tight">{messages.chatDevTools.title}</h2>
                </div>
                <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 rounded-lg hover:bg-muted"
                    onClick={() => setShowDevTools(false)}
                    title={messages.chatDevTools.close}
                >
                    <EyeOff className="h-4 w-4 text-muted-foreground" />
                </Button>
            </div>

            {/* 탭 네비게이션 */}
            <Tabs
                value={leftPanelTab.toString()}
                onValueChange={(v) => setLeftPanelTab(parseInt(v))}
                className="w-full"
            >
                <TabsList className="w-full flex rounded-none bg-muted/20 border-b h-10 p-1">
                    <TabsTrigger value="0" className="flex-1 text-[11px] font-bold gap-1.5 data-[state=active]:bg-background shadow-sm h-8 rounded-md transition-all">
                        <Info className="h-3 w-3" />
                        {messages.chatDevTools.sessionInfoTab}
                    </TabsTrigger>
                    <TabsTrigger value="1" className="flex-1 text-[11px] font-bold gap-1.5 data-[state=active]:bg-background shadow-sm h-8 rounded-md transition-all">
                        <History className="h-3 w-3" />
                        {messages.chatDevTools.apiLogTab}
                    </TabsTrigger>
                </TabsList>

                <ScrollArea className="flex-1">
                    <TabsContent value="0" className="p-4 m-0 space-y-4">
                        {/* 현재 세션 카드 */}
                        <Card className="shadow-sm border-border/60 hover:shadow-md transition-all">
                            <CardContent className="p-3.5 space-y-2.5">
                                <div className="flex items-center gap-2">
                                    <Terminal className="h-3.5 w-3.5 text-muted-foreground" />
                                    <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{messages.chatDevTools.currentSession}</span>
                                </div>
                                <div className="font-mono text-[10px] bg-muted p-2.5 rounded-lg break-all border border-border/50 text-foreground/80 leading-relaxed">
                                    {sessionId || 'N/A'}
                                </div>
                            </CardContent>
                        </Card>

                        {sessionInfo && (
                            <>
                                {/* 통계 정보 카드 */}
                                <Card className="shadow-sm border-border/60 hover:shadow-md transition-all">
                                    <CardContent className="p-3.5 space-y-3">
                                        <div className="flex items-center gap-2">
                                            <BarChart2 className="h-3.5 w-3.5 text-green-500" />
                                            <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{messages.chatDevTools.sessionStats}</span>
                                        </div>
                                        <div className="grid gap-2">
                                            <div className="flex items-center justify-between">
                                                <span className="text-[11px] font-medium text-muted-foreground">{messages.chatDevTools.messages}</span>
                                                <Badge variant="secondary" className="h-5 text-[10px] font-bold">{sessionInfo.messageCount}</Badge>
                                            </div>
                                            <div className="flex items-center justify-between">
                                                <span className="text-[11px] font-medium text-muted-foreground">{messages.chatDevTools.tokens}</span>
                                                <Badge className="h-5 text-[10px] font-bold bg-blue-500 hover:bg-blue-600">{sessionInfo.tokensUsed}</Badge>
                                            </div>
                                            <div className="flex items-center justify-between">
                                                <span className="text-[11px] font-medium text-muted-foreground">{messages.chatDevTools.processingTime}</span>
                                                <Badge className="h-5 text-[10px] font-bold bg-green-500 hover:bg-green-600">{sessionInfo.processingTime?.toFixed(2)}s</Badge>
                                            </div>
                                        </div>
                                    </CardContent>
                                </Card>

                                {sessionInfo?.modelInfo && (
                                    <Card className="shadow-sm border-border/60 hover:shadow-md transition-all">
                                        <CardContent className="p-3.5 space-y-3">
                                            <div className="flex items-center gap-2">
                                                <ChatbotIcon width={14} height={14} animated={true} />
                                                <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{messages.chatDevTools.llmModelInfo}</span>
                                            </div>
                                            <div className="space-y-1.5">
                                                <div className="flex justify-between text-[11px]">
                                                    <span className="text-muted-foreground">{messages.chatDevTools.provider}</span>
                                                    <span className="font-bold">{sessionInfo.modelInfo.provider || 'N/A'}</span>
                                                </div>
                                                <div className="flex justify-between text-[11px]">
                                                    <span className="text-muted-foreground">{messages.chatDevTools.model}</span>
                                                    <span className="font-bold truncate max-w-[120px]" title={sessionInfo.modelInfo.model}>
                                                        {sessionInfo.modelInfo.model || 'N/A'}
                                                    </span>
                                                </div>
                                                <div className="flex justify-between text-[11px]">
                                                    <span className="text-muted-foreground">{messages.chatDevTools.generationTime}</span>
                                                    <span className="font-bold">{sessionInfo.modelInfo.generation_time ? `${sessionInfo.modelInfo.generation_time.toFixed(3)}s` : 'N/A'}</span>
                                                </div>

                                                {modelConfigEntries.length > 0 && (
                                                    <div className="pt-2 space-y-2">
                                                        <Separator className="bg-border/40" />
                                                        <span className="text-[9px] font-extrabold uppercase tracking-widest text-muted-foreground/70 block px-0.5">{messages.chatDevTools.modelParameters}</span>
                                                        <div className="grid gap-1 px-0.5">
                                                            {modelConfigEntries.map(([key, value]) => (
                                                                <div key={key} className="flex justify-between text-[10px]">
                                                                    <span className="text-muted-foreground">{key}</span>
                                                                    <span className="font-bold text-foreground/80">{formatModelConfigValue(value)}</span>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        </CardContent>
                                    </Card>
                                )}

                                {/* 디버그 정보 */}
                                {import.meta.env.DEV && (
                                    <Card className="shadow-sm border-border/60 overflow-hidden">
                                        <div
                                            className="p-3 flex items-center justify-between cursor-pointer hover:bg-muted/30 transition-all select-none"
                                            onClick={() => setIsDebugExpanded(!isDebugExpanded)}
                                        >
                                            <div className="flex items-center gap-2">
                                                <Bug className="h-3.5 w-3.5 text-orange-500" />
                                                <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{messages.chatDevTools.debugInfo}</span>
                                            </div>
                                            {isDebugExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                                        </div>
                                        {isDebugExpanded && (
                                            <CardContent className="p-3 pt-0 border-t bg-muted/10">
                                                <pre className="mt-2 p-2 bg-muted rounded border border-border/40 text-[9px] font-mono leading-tight whitespace-pre-wrap max-h-[200px] overflow-auto">
                                                    {JSON.stringify({
                                                        sessionId: sessionInfo.session_id,
                                                        messageCount: sessionInfo.messageCount,
                                                        tokensUsed: sessionInfo.tokensUsed,
                                                        processingTime: sessionInfo.processingTime,
                                                        timestamp: sessionInfo.timestamp,
                                                        modelInfo: sessionInfo.modelInfo ? {
                                                            provider: sessionInfo.modelInfo.provider,
                                                            model: sessionInfo.modelInfo.model,
                                                            generationTime: sessionInfo.modelInfo.generation_time,
                                                            parameters: sessionInfo.modelInfo.model_config,
                                                        } : null,
                                                    }, null, 2)}
                                                </pre>
                                            </CardContent>
                                        )}
                                    </Card>
                                )}
                            </>
                        )}

                        {/* 새 세션 버튼 */}
                        <Button
                            className="w-full font-bold text-[11px] h-9 gap-2 shadow-sm rounded-lg hover:scale-[1.02] active:scale-95 transition-all"
                            onClick={handleNewSession}
                        >
                            <RefreshCw className="h-3.5 w-3.5" />
                            {messages.chatDevTools.startNewSession}
                        </Button>
                    </TabsContent>

                    <TabsContent value="1" className="p-4 m-0 space-y-3">
                        {apiLogs.length === 0 ? (
                            <div className="flex flex-col items-center justify-center py-12 text-center space-y-3">
                                <History className="h-10 w-10 text-muted-foreground/30" />
                                <p className="text-xs text-muted-foreground italic">{messages.chatDevTools.noApiCalls}</p>
                            </div>
                        ) : (
                            <div className="space-y-2">
                                {apiLogs.slice().reverse().map((log) => (
                                    <div key={log.id} className="group border rounded-xl overflow-hidden shadow-sm transition-all hover:border-primary/30">
                                        <div
                                            className={cn(
                                                "p-3 cursor-pointer transition-all flex flex-col gap-1.5",
                                                log.type === 'request' ? "bg-blue-500/5 hover:bg-blue-500/10" :
                                                    log.status === 200 ? "bg-green-500/5 hover:bg-green-500/10" : "bg-red-500/5 hover:bg-red-500/10"
                                            )}
                                            onClick={() => toggleLogExpansion(log.id)}
                                        >
                                            <div className="flex items-center justify-between">
                                                <span className="text-[10px] font-bold font-mono tracking-tight text-foreground truncate max-w-[140px]">
                                                    {log.method} {log.endpoint}
                                                </span>
                                                <div className="flex items-center gap-1.5">
                                                    <TooltipProvider>
                                                        <Tooltip>
                                                            <TooltipTrigger asChild>
                                                                <Button
                                                                    variant="ghost"
                                                                    size="icon"
                                                                    className="h-6 w-6 rounded-md opacity-0 group-hover:opacity-100 transition-opacity"
                                                                    aria-label={messages.chatDevTools.copyLog}
                                                                    onClick={(e) => {
                                                                        e.stopPropagation();
                                                                        const logText = JSON.stringify(log.data, null, 2);
                                                                        copyToClipboard(logText, messages.chatDevTools.logCopiedNotice);
                                                                    }}
                                                                >
                                                                    <Copy className="h-3 w-3" />
                                                                </Button>
                                                            </TooltipTrigger>
                                                            <TooltipContent className="text-[10px]">{messages.chatDevTools.copy}</TooltipContent>
                                                        </Tooltip>
                                                    </TooltipProvider>
                                                    <Badge
                                                        variant="outline"
                                                        className={cn(
                                                            "h-4 text-[9px] px-1 font-extrabold border-none",
                                                            log.type === 'request' ? "bg-blue-500 text-white" :
                                                                log.status === 200 ? "bg-green-500 text-white" : "bg-red-500 text-white"
                                                        )}
                                                    >
                                                        {log.type === 'request' ? 'REQ' : `RES ${log.status}`}
                                                    </Badge>
                                                </div>
                                            </div>
                                            <div className="text-[9px] text-muted-foreground flex items-center gap-2 px-0.5">
                                                <span>{new Date(log.timestamp).toLocaleTimeString('ko-KR')}</span>
                                                {log.duration && <span className="text-primary/60 font-bold">{log.duration}ms</span>}
                                            </div>
                                        </div>
                                        {expandedLogs.has(log.id) && (
                                            <div className="p-3 border-t bg-muted/10">
                                                <pre className="p-2 bg-muted rounded border border-border/40 text-[9px] font-mono leading-tight whitespace-pre-wrap max-h-[300px] overflow-auto">
                                                    {JSON.stringify(log.data, null, 2)}
                                                </pre>
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </TabsContent>
                </ScrollArea>
            </Tabs>
        </div>
    );
};

