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
import { useOfflineDetection } from '../hooks/useOfflineDetection';
import { useEmbedBridge } from '../embed/useEmbedBridge';
import { useMenuMessages } from '../i18n/useMenuLocale';

// Components
import { ChatDevTools } from './chat/ChatDevTools';
import { ChatMessageList } from './chat/ChatMessageList';
import { ChatInput } from './chat/ChatInput';
import { ChatHeader } from './chat/ChatHeader';
import { ChatSessionSidebar } from './chat/ChatSessionSidebar';
import { RagTracePanel } from './chat/RagTracePanel';
import { ChunkDetailModal } from './chat/ChunkDetailModal';

interface DocumentInfoItem {
  label: string;
  value: string;
}

interface ChatTabProps {
  showToast: (message: Omit<ToastMessage, 'id'>) => void;
  /** 임베드(embed) 모드 여부. true면 사이드바/디버그 UI를 숨기고 임베드 브리지를 활성화한다. */
  embedMode?: boolean;
}

export const ChatTab: React.FC<ChatTabProps> = ({ showToast, embedMode = false }) => {
  const { messages: t } = useMenuMessages();
  // API Logs State
  const [apiLogs, setApiLogs] = React.useState<ApiLog[]>([]);
  const { isOnline } = useOfflineDetection();

  // 1. Session Logic Hook
  const {
    sessionId,
    sessionInfo,
    setSessionInfo,
    initialMessages,
    handleNewSession,
    switchSession,
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
    isSseStreaming,
    ragProgress,
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
    sourceDetail,
    sourceDetailLoading,
    sourceDetailError,
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

  // 임베드 모드일 때만 부모 윈도우와의 postMessage 브리지를 활성화한다.
  // host가 보낸 메시지는 handleSend(directMessage)로 정확히 전달된다.
  useEmbedBridge({
    enabled: embedMode,
    loading,
    isStreaming,
    messageCount: messages.length,
    onSend: handleSend,
    onStop: handleStop,
  });

  const documentInfoItems = useMemo<DocumentInfoItem[]>(() => {
    if (!selectedChunk) return [];

    const meta = (selectedChunk.additional_metadata ?? {}) as SourceAdditionalMetadata;
    const formatPrimitive = (value: unknown): string => {
      if (value === undefined || value === null) return t.common.notAvailable;
      if (typeof value === 'boolean') return value ? t.ragTrace.booleanTrue : t.ragTrace.booleanFalse;
      if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : String(value);
      if (value instanceof Date) return value.toISOString();
      if (Array.isArray(value)) return value.length === 0 ? t.common.notAvailable : value.map(v => typeof v === 'object' ? JSON.stringify(v) : v).join(', ');
      const s = String(value);
      return s.trim().length > 0 ? s : t.common.notAvailable;
    };

    const similarity = typeof selectedChunk.relevance === 'number'
      ? `${(selectedChunk.relevance * 100).toFixed(2)}%`
      : undefined;

    return [
      { label: t.chatTab.documentId, value: formatPrimitive(selectedChunk.id) },
      { label: t.chatTab.documentFilename, value: formatPrimitive(selectedChunk.document) },
      { label: t.chatTab.displayTitle, value: formatPrimitive(meta.display_title ?? meta.law_name) },
      { label: t.chatTab.priority, value: formatPrimitive(meta.priority_level) },
      { label: t.chatTab.chunkNumber, value: formatPrimitive(selectedChunk.chunk !== null && selectedChunk.chunk !== undefined ? `#${selectedChunk.chunk}` : null) },
      { label: t.chatTab.page, value: formatPrimitive(selectedChunk.page) },
      { label: t.chatTab.similarity, value: formatPrimitive(similarity) },
      { label: t.chatTab.totalChunks, value: formatPrimitive(selectedChunk.total_chunks) },
      { label: t.chatTab.originalScore, value: formatPrimitive(selectedChunk.original_score) },
      { label: t.chatTab.rerankMethod, value: formatPrimitive(selectedChunk.rerank_method) },
      { label: t.chatTab.uploadedAt, value: formatPrimitive(meta.uploaded_at) },
    ];
  }, [selectedChunk, t]);

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
    <div
      className={
        embedMode
          // 임베드 모드: 뷰포트 전체를 채우고 부가 패널을 숨긴다.
          ? 'flex h-screen bg-muted/20 overflow-hidden font-sans antialiased'
          : 'flex h-[85vh] bg-muted/20 overflow-hidden font-sans antialiased'
      }
    >
      {/* 임베드 모드에서는 세션 사이드바를 숨긴다(외부 사이트 위젯은 단일 대화). */}
      {!embedMode && (
        <ChatSessionSidebar
          sessionId={sessionId}
          messages={messages}
          onNewSession={handleNewSession}
          onSelectSession={switchSession}
        />
      )}

      {/* 임베드 모드에서는 개발자 도구 패널을 숨긴다. */}
      {!embedMode && (
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
      )}

      <div
        className={
          embedMode
            ? 'flex-grow flex flex-col px-0 py-0'
            : 'flex-grow flex justify-center items-center px-4 md:px-6 py-4'
        }
      >
        <div
          className={
            embedMode
              ? 'w-full h-full flex flex-col min-h-0 bg-background overflow-hidden'
              : 'w-full max-w-4xl h-[80vh] flex flex-col min-h-0 bg-background rounded-2xl shadow-xl overflow-hidden border border-border/60'
          }
        >
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
            isSseStreaming={isSseStreaming}
            ragProgress={ragProgress}
          />

          <ChatInput
            input={input}
            setInput={setInput}
            loading={loading}
            handleSend={handleSend}
            handleStop={handleStop}
            handleKeyPress={handleKeyPress}
            isOnline={isOnline}
          />
        </div>
      </div>

      {/* 임베드 모드에서는 RAG 추적(디버그) 패널을 숨긴다. */}
      {!embedMode && (
        <RagTracePanel
          messages={messages}
          apiLogs={apiLogs}
          selectedChunk={selectedChunk}
          isStreaming={isStreaming}
        />
      )}

      <ChunkDetailModal
        open={modalOpen}
        onClose={handleCloseModal}
        selectedChunk={selectedChunk}
        documentInfoItems={documentInfoItems}
        sourceDetail={sourceDetail}
        sourceDetailLoading={sourceDetailLoading}
        sourceDetailError={sourceDetailError}
      />
    </div>
  );
};
