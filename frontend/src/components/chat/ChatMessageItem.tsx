import React from 'react';
import { User, Copy, BookOpen } from 'lucide-react';
import { ChatMessage, Source as SourceType } from '../../types';
import { MarkdownRenderer } from '../MarkdownRenderer';
import { ChatbotIcon } from '../icons';
import {
    Avatar,
    AvatarFallback,
} from "@/components/ui/avatar";
import { Button } from '@/components/ui/button';
import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from '@/components/ui/badge';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from '@/lib/utils';
import {
    formatSourcePreview,
    formatTimestamp,
} from '../../utils/chat/formatters';
import { useMenuMessages } from '../../i18n/useMenuLocale';
import { format } from '../../i18n/format';

interface ChatMessageItemProps {
    message: ChatMessage;
    isAnimated: boolean;
    copyToClipboard: (text: string, successMessage?: string) => void;
    onChunkClick: (source: SourceType) => void;
}

export const ChatMessageItem: React.FC<ChatMessageItemProps> = ({
    message,
    isAnimated,
    copyToClipboard,
    onChunkClick,
}) => {
    // i18n: 복사 버튼 등 메시지 액션 라벨
    const { messages } = useMenuMessages();
    const isUser = message.role === 'user';

    return (
        <div
            className={cn(
                "flex w-full gap-3 mb-6 transition-all duration-500 ease-out px-1",
                isUser ? "flex-row-reverse" : "flex-row",
                isAnimated ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4"
            )}
        >
            <Avatar className={cn(
                "h-8 w-8 border shadow-sm shrink-0",
                isUser ? "bg-primary text-primary-foreground border-primary" : "bg-background border-border"
            )}>
                {isUser ? (
                    <AvatarFallback className="bg-primary text-primary-foreground">
                        <User className="h-4 w-4" />
                    </AvatarFallback>
                ) : (
                    <div className="flex items-center justify-center w-full h-full bg-background mt-0.5">
                        <ChatbotIcon width={18} height={18} />
                    </div>
                )}
            </Avatar>

            <div className={cn(
                "flex flex-col gap-1 max-w-[85%]",
                isUser ? "items-end" : "items-start"
            )}>
                <div className={cn(
                    "relative group transition-all",
                    isUser
                        ? "bg-primary text-primary-foreground px-4 py-2 rounded-[18px] rounded-tr-sm shadow-sm"
                        : "bg-transparent border-none px-0 py-0"
                )}>
                    {!isUser && (
                        <div className="absolute -top-1 -right-8 opacity-0 group-hover:opacity-100 transition-opacity z-10">
                            <TooltipProvider>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-7 w-7 rounded-md hover:bg-muted"
                                            aria-label={messages.chat.message.copyAnswer}
                                            onClick={() => copyToClipboard(message.content, messages.chat.message.copiedNotice)}
                                        >
                                            <Copy className="h-3.5 w-3.5" />
                                        </Button>
                                    </TooltipTrigger>
                                    <TooltipContent>{messages.chat.message.copyAnswer}</TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                        </div>
                    )}

                    {isUser ? (
                        <div className="text-sm leading-relaxed whitespace-pre-wrap">
                            {message.content}
                        </div>
                    ) : (
                        <MarkdownRenderer
                            content={message.content}
                            onCitationClick={(index) => {
                                if (message.sources && message.sources[index - 1]) {
                                    onChunkClick(message.sources[index - 1]);
                                }
                            }}
                            className="w-full"
                        />
                    )}

                    <span className={cn(
                        "text-[10px] mt-1.5 block font-medium",
                        isUser ? "text-primary-foreground/70 text-right" : "text-muted-foreground/50"
                    )}>
                        {formatTimestamp(message.timestamp)}
                    </span>
                </div>

                {!isUser && message.sources && message.sources.length > 0 && (
                    <div className="w-full mt-3">
                        <Accordion type="single" collapsible className="w-full border-none">
                            <AccordionItem value="sources" className="border-none">
                                <AccordionTrigger className="flex justify-start gap-2 py-2 px-0 hover:no-underline hover:opacity-80 transition-all border-none">
                                    <div className="flex items-center gap-2 text-[11px] font-bold text-primary/60">
                                        <BookOpen className="h-3.5 w-3.5 text-blue-500" />
                                        {format(messages.chat.message.sourcesCount, { count: message.sources.length })}
                                    </div>
                                </AccordionTrigger>
                                <AccordionContent className="pt-2 pb-0">
                                    <div className="grid grid-cols-1 gap-2">
                                        {message.sources.map((source, idx) => (
                                            <button
                                                key={idx}
                                                onClick={() => onChunkClick(source)}
                                                className="text-left p-3 rounded-xl border border-border/40 bg-muted/10 hover:bg-muted/30 hover:border-primary/20 transition-all group relative overflow-hidden"
                                            >
                                                <div className="flex justify-between items-start mb-1.5 relative z-10">
                                                    <div className="text-xs font-bold text-primary/80 truncate pr-2">
                                                        {source.document}
                                                        {source.page && <span className="ml-1 text-[10px] opacity-60 font-normal">(p.{source.page})</span>}
                                                    </div>
                                                    <Badge variant="outline" className={cn(
                                                        "h-4 text-[8px] px-1 font-extrabold shrink-0 shadow-none border-none",
                                                        source.relevance > 0.8 ? "bg-green-500/10 text-green-600" : "bg-slate-500/10 text-slate-600"
                                                    )}>
                                                        {(source.relevance * 100).toFixed(0)}%
                                                    </Badge>
                                                </div>
                                                <p className="text-[11px] text-muted-foreground line-clamp-2 leading-relaxed relative z-10">
                                                    {formatSourcePreview(source.content_preview)}
                                                </p>
                                            </button>
                                        ))}
                                    </div>
                                </AccordionContent>
                            </AccordionItem>
                        </Accordion>
                    </div>
                )}
            </div>
        </div>
    );
};
