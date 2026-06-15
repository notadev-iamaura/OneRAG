import React from 'react';
import { Send, Square, WifiOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import { useMenuMessages } from '../../i18n/useMenuLocale';

interface ChatInputProps {
    input: string;
    setInput: (value: string) => void;
    loading: boolean;
    handleSend: () => void;
    handleStop: () => void;
    handleKeyPress: (e: React.KeyboardEvent) => void;
    isOnline?: boolean;
}

export const ChatInput: React.FC<ChatInputProps> = ({
    input,
    setInput,
    loading,
    handleSend,
    handleStop,
    handleKeyPress,
    isOnline = true,
}) => {
    // i18n: 입력창 관련 메시지
    const { messages } = useMenuMessages();

    return (
        <div className="px-4 py-4 bg-background/50 backdrop-blur-md border-t border-border/50 relative">
            {!isOnline && (
                <div className="absolute -top-10 left-0 right-0 flex justify-center mt-2 pointer-events-none z-10">
                    <div className="bg-destructive/10 border border-destructive/20 text-destructive text-xs font-bold px-4 py-1.5 rounded-full flex items-center gap-2 shadow-sm backdrop-blur-md">
                        <WifiOff className="w-3.5 h-3.5" />
                        {messages.chat.input.offlineNotice}
                    </div>
                </div>
            )}
            <div className={cn("flex gap-2 items-end max-w-4xl mx-auto transition-opacity", !isOnline && "opacity-50 pointer-events-none")}>
                <div className="relative flex-1 group">
                    <Textarea
                        placeholder={isOnline ? messages.chat.input.placeholder : messages.chat.input.offlinePlaceholder}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyPress}
                        disabled={loading || !isOnline}
                        className={cn(
                            "flex-1 min-h-[48px] max-h-48 rounded-[24px] bg-muted/30 border-border/50 focus-visible:ring-primary/10 transition-all resize-none py-3 px-6 pr-12 text-sm leading-relaxed",
                            "group-hover:bg-muted/50 group-focus-within:bg-background group-focus-within:shadow-sm",
                            !isOnline && "cursor-not-allowed"
                        )}
                    />
                </div>

                <TooltipProvider>
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                onClick={loading ? handleStop : handleSend}
                                disabled={(!loading && !input.trim()) || !isOnline}
                                aria-label={loading ? messages.chat.input.stopResponse : messages.chat.input.sendMessage}
                                size="icon"
                                className={cn(
                                    "h-[48px] w-[48px] rounded-full transition-all duration-300 shadow-md",
                                    loading
                                        ? "bg-destructive hover:bg-destructive/90 text-destructive-foreground animate-pulse"
                                        : "bg-primary hover:bg-primary/90 text-primary-foreground",
                                    !isOnline && "bg-muted text-muted-foreground hover:bg-muted"
                                )}
                            >
                                {loading ? (
                                    <Square className="w-5 h-5 fill-current" />
                                ) : (
                                    <Send className="w-5 h-5 ml-0.5" />
                                )}
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent side="top">
                            {!isOnline ? messages.chat.input.disconnected : loading ? messages.chat.input.stop : messages.chat.input.send}
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            </div>
        </div>
    );
};

