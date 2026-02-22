import React, { useEffect, useRef } from 'react';
import { ArrowDown, Loader2 } from 'lucide-react';
import { ChatMessage, Source as SourceType } from '../../types';
import { StreamingMessage } from '../../types/chatStreaming';
import { ChatMessageItem } from './ChatMessageItem';
import { ChatEmptyState } from '../ChatEmptyState';
import { ChatbotIcon } from '../icons';
import { MarkdownRenderer } from '../MarkdownRenderer';
import {
    ScrollArea
} from "@/components/ui/scroll-area";
import { Button } from '@/components/ui/button';
import {
    Avatar,
} from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";

interface ChatMessageListProps {
    messages: ChatMessage[];
    loading: boolean;
    messageAnimations: Set<string>;
    copyToClipboard: (text: string, successMessage?: string) => void;
    onChunkClick: (source: SourceType) => void;
    onSuggestionClick: (suggestion: string) => void;
    messagesEndRef: React.RefObject<HTMLDivElement>;
    showScrollButton?: boolean;
    handleScroll?: (e: React.UIEvent<HTMLDivElement>) => void;
    scrollToBottom?: (behavior: ScrollBehavior) => void;
    streamingMessage?: StreamingMessage | null;
    isStreaming?: boolean;
}

const StreamingMessageItem: React.FC<{
    streamingMessage: StreamingMessage;
}> = ({ streamingMessage }) => {
    return (
        <div className="flex gap-3 mb-6 items-start px-1 animate-in fade-in slide-in-from-bottom-2 duration-500">
            <Avatar className="h-8 w-8 border shadow-sm shrink-0 bg-background border-border">
                <div className="flex items-center justify-center w-full h-full bg-background mt-0.5">
                    <ChatbotIcon width={18} height={18} animated={true} />
                </div>
            </Avatar>
            <div className="flex flex-col gap-1 max-w-[85%] items-start">
                <div className="relative group transition-all bg-transparent border-none px-0 py-0 min-w-[100px] min-h-[40px]">
                    {streamingMessage.content ? (
                        <div className="relative">
                            <MarkdownRenderer content={streamingMessage.content} className="w-full" />
                            <span className="inline-block w-0.5 h-4 bg-primary ml-1 animate-pulse align-middle" />
                        </div>
                    ) : (
                        <div className="flex items-center gap-2 py-1">
                            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground opacity-60" />
                            <span className="text-[11px] text-muted-foreground opacity-80 font-medium">응답을 준비하고 있습니다...</span>
                        </div>
                    )}
                </div>
                <div className="flex items-center gap-1.5 px-0.5 mt-1">
                    <Loader2 className="h-2.5 w-2.5 animate-spin text-primary opacity-80" />
                    <span className="text-[10px] text-muted-foreground opacity-60 font-bold tracking-tight">스트리밍 중...</span>
                </div>
            </div>
        </div>
    );
};

export const ChatMessageList: React.FC<ChatMessageListProps> = ({
    messages,
    loading,
    messageAnimations,
    copyToClipboard,
    onChunkClick,
    onSuggestionClick,
    messagesEndRef,
    showScrollButton,
    handleScroll,
    scrollToBottom,
    streamingMessage,
    isStreaming,
}) => {
    const lastContentLengthRef = useRef(0);

    useEffect(() => {
        if (isStreaming && streamingMessage?.content) {
            const currentLength = streamingMessage.content.length;
            if (currentLength > lastContentLengthRef.current + 50 || lastContentLengthRef.current === 0) {
                lastContentLengthRef.current = currentLength;
                if (!showScrollButton) {
                    scrollToBottom?.('smooth');
                }
            }
        } else {
            lastContentLengthRef.current = 0;
        }
    }, [isStreaming, streamingMessage?.content, showScrollButton, scrollToBottom]);

    return (
        <div className="flex-1 min-h-0 relative overflow-hidden bg-gradient-to-b from-background via-muted/5 to-muted/10">
            <ScrollArea
                className="h-full w-full px-4 pt-6"
                onScrollCapture={handleScroll}
            >
                {messages.length === 0 && !loading && !isStreaming ? (
                    <ChatEmptyState onSuggestionClick={onSuggestionClick} />
                ) : (
                    <div className="max-w-4xl mx-auto pb-6">
                        {messages.map((message) => (
                            <ChatMessageItem
                                key={message.id}
                                message={message}
                                isAnimated={messageAnimations.has(message.id)}
                                copyToClipboard={copyToClipboard}
                                onChunkClick={onChunkClick}
                            />
                        ))}

                        {isStreaming && streamingMessage && (
                            <StreamingMessageItem streamingMessage={streamingMessage} />
                        )}

                        {loading && !isStreaming && (
                            <div className="flex gap-3 mb-8 items-start px-1 animate-in fade-in duration-500">
                                <Avatar className="h-8 w-8 border shadow-sm shrink-0 bg-background border-border">
                                    <div className="flex items-center justify-center w-full h-full bg-background mt-0.5">
                                        <ChatbotIcon width={18} height={18} animated={true} />
                                    </div>
                                </Avatar>
                                <div className="flex flex-col gap-3 w-full max-w-[80%]">
                                    <div className="space-y-2.5 p-4 rounded-[18px] rounded-tl-sm bg-muted/20 border border-border/40 shadow-sm">
                                        <Skeleton className="h-3.5 w-[90%] bg-muted-foreground/10" />
                                        <Skeleton className="h-3.5 w-[70%] bg-muted-foreground/10" />
                                        <Skeleton className="h-3.5 w-[80%] bg-muted-foreground/10" />
                                        <div className="flex items-center gap-2 mt-2 pt-2 border-t border-border/20">
                                            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground opacity-60" />
                                            <span className="text-[11px] text-muted-foreground opacity-80 font-medium">답변을 생성하고 있습니다...</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}
                        <div ref={messagesEndRef} className="h-4" />
                    </div>
                )}
            </ScrollArea>

            {showScrollButton && (
                <Button
                    variant="secondary"
                    size="icon"
                    className="absolute bottom-6 right-6 rounded-full shadow-lg border border-border bg-background/80 backdrop-blur-sm z-50 hover:scale-110 active:scale-95 transition-all animate-in fade-in zoom-in duration-300"
                    onClick={() => scrollToBottom?.('smooth')}
                    aria-label="맨 아래로 이동"
                >
                    <ArrowDown className="h-4 w-4" />
                </Button>
            )}
        </div>
    );
};

