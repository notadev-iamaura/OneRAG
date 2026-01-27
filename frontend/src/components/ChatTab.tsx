import React, { useMemo } from 'react';
import {
  ToastMessage,
  SourceAdditionalMetadata,
  ApiLog,
} from '../types';

// Custom Hooks
import { useChatSession } from '../hooks/chat/useChatSession';
import { useChatMessages } from '../hooks/chat/useChatMessages';
import { useChatInteraction } from '../hooks/chat/useChatInteraction';

// Components
import { ChatDevTools } from './chat/ChatDevTools';
import { ChatMessageList } from './chat/ChatMessageList';
import { ChatInput } from './chat/ChatInput';
import { ChatHeader } from './chat/ChatHeader';
import { ChunkDetailModal } from './chat/ChunkDetailModal';

interface DocumentInfoItem {
  label: string;
  value: string;
}

interface ChatTabProps {
  showToast: (message: Omit<ToastMessage, 'id'>) => void;
}

export const ChatTab: React.FC<ChatTabProps> = ({ showToast }) => {
  // API Logs State
  const [apiLogs, setApiLogs] = React.useState<ApiLog[]>([]);

  // 1. Session Logic Hook
  const {
    sessionId,
    sessionInfo,
    setSessionInfo,
    initialMessages,
    handleNewSession,
    synchronizeSessionId,
    refreshSessionInfo
  } = useChatSession({ showToast, setApiLogs });

  // 2. Message Logic Hook
  const {
    messages,
    input,
    setInput,
    loading,
    handleSend,
    handleStop,
    // 스트리밍 관련 상태
    isStreaming,
    streamingMessage,
  } = useChatMessages({
    sessionId,
    initialMessages,
    synchronizeSessionId,
    refreshSessionInfo,
    setSessionInfo,
    showToast,
    setApiLogs
  });

  // 3. Interaction Logic Hook
  const {
    messagesEndRef,
    modalOpen,
    selectedChunk,
    handleChunkClick,
    handleCloseModal,
    leftPanelTab,
    setLeftPanelTab,
    expandedLogs,
    toggleLogExpansion,
    isDebugExpanded,
    setIsDebugExpanded,
    messageAnimations,
    showDevTools,
    setShowDevTools,
    copyToClipboard,
    showScrollButton,
    handleScroll,
    scrollToBottom,
  } = useChatInteraction({ messages, showToast });

  const documentInfoItems = useMemo<DocumentInfoItem[]>(() => {
    if (!selectedChunk) return [];

    const meta = (selectedChunk.additional_metadata ?? {}) as SourceAdditionalMetadata;
    const formatPrimitive = (value: unknown): string => {
      if (value === undefined || value === null) return 'N/A';
      if (typeof value === 'boolean') return value ? '예' : '아니오';
      if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : String(value);
      if (value instanceof Date) return value.toISOString();
      if (Array.isArray(value)) return value.length === 0 ? 'N/A' : value.map(v => typeof v === 'object' ? JSON.stringify(v) : v).join(', ');
      const s = String(value);
      return s.trim().length > 0 ? s : 'N/A';
    };

    const similarity = typeof selectedChunk.relevance === 'number'
      ? `${(selectedChunk.relevance * 100).toFixed(2)}%`
      : undefined;

    return [
      { label: '문서 ID', value: formatPrimitive(selectedChunk.id) },
      { label: '문서 파일명', value: formatPrimitive(selectedChunk.document) },
      { label: '표시 제목', value: formatPrimitive(meta.display_title ?? meta.law_name) },
      { label: '우선순위', value: formatPrimitive(meta.priority_level) },
      { label: '청크 번호', value: formatPrimitive(selectedChunk.chunk !== null && selectedChunk.chunk !== undefined ? `#${selectedChunk.chunk}` : null) },
      { label: '페이지', value: formatPrimitive(selectedChunk.page) },
      { label: '유사도', value: formatPrimitive(similarity) },
      { label: '총 청크 수', value: formatPrimitive(selectedChunk.total_chunks) },
      { label: '원본 점수', value: formatPrimitive(selectedChunk.original_score) },
      { label: '재순위 방법', value: formatPrimitive(selectedChunk.rerank_method) },
      { label: '업로드 일시', value: formatPrimitive(meta.uploaded_at) },
    ];
  }, [selectedChunk]);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    setInput(suggestion);
  };

  return (
    <div className="flex h-[85vh] bg-muted/20 overflow-hidden font-sans antialiased">
      <ChatDevTools
        showDevTools={showDevTools}
        setShowDevTools={setShowDevTools}
        leftPanelTab={leftPanelTab}
        setLeftPanelTab={setLeftPanelTab}
        sessionId={sessionId}
        sessionInfo={sessionInfo}
        apiLogs={apiLogs}
        expandedLogs={expandedLogs}
        toggleLogExpansion={toggleLogExpansion}
        isDebugExpanded={isDebugExpanded}
        setIsDebugExpanded={setIsDebugExpanded}
        handleNewSession={handleNewSession}
        copyToClipboard={copyToClipboard}
      />

      <div className="flex-grow flex justify-center items-center px-4 md:px-6 py-4">
        <div className="w-full max-w-4xl h-[80vh] flex flex-col min-h-0 bg-background rounded-2xl shadow-xl overflow-hidden border border-border/60">
          <ChatHeader
            sessionId={sessionId}
            showDevTools={showDevTools}
            setShowDevTools={setShowDevTools}
            onNewSession={handleNewSession}
          />

          <ChatMessageList
            messages={messages}
            loading={loading}
            messageAnimations={messageAnimations}
            messagesEndRef={messagesEndRef}
            onChunkClick={handleChunkClick}
            onSuggestionClick={handleSuggestionClick}
            copyToClipboard={copyToClipboard}
            showScrollButton={showScrollButton}
            handleScroll={handleScroll}
            scrollToBottom={scrollToBottom}
            isStreaming={isStreaming}
            streamingMessage={streamingMessage}
          />

          <ChatInput
            input={input}
            setInput={setInput}
            loading={loading}
            handleSend={handleSend}
            handleStop={handleStop}
            handleKeyPress={handleKeyPress}
          />
        </div>
      </div>

      <ChunkDetailModal
        open={modalOpen}
        onClose={handleCloseModal}
        selectedChunk={selectedChunk}
        documentInfoItems={documentInfoItems}
      />
    </div>
  );
};

