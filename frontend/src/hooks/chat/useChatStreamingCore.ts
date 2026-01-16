/**
 * useChatStreamingCore - 스트리밍 관리 핵심 로직
 *
 * IChatWebSocketService를 직접 주입받아 스트리밍을 관리하는 순수 훅입니다.
 * Context 없이 서비스를 직접 전달받아 동작합니다.
 *
 * @example
 * // Core 훅 직접 사용 (테스트 또는 특수 케이스)
 * const streaming = useChatStreamingCore(mockService, {
 *   sessionId: 'session-123',
 *   onMessageComplete: (msg) => console.log('완료:', msg),
 *   onError: (err) => console.error('오류:', err),
 * });
 *
 * // 일반적인 사용은 useChatStreaming() 또는 useChatStreamingWithDI() 권장
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { IChatWebSocketService } from '../../services/createChatWebSocketService';
import type {
  StreamingMessage,
  StreamingState,
  StreamTokenMessage,
  StreamSourcesMessage,
  StreamEndMessage,
  StreamErrorMessage,
  ConnectionEventData,
} from '../../types/chatStreaming';
import type { ChatMessage } from '../../types';
import { logger } from '../../utils/logger';

/**
 * WebSocket 이벤트 핸들러 타입
 * (IChatWebSocketService.on/off와 호환)
 */
export type WebSocketEventHandler = (data: unknown) => void;

/**
 * useChatStreamingCore 훅 Props
 */
export interface UseChatStreamingCoreProps {
  /** 채팅 세션 ID */
  sessionId: string;
  /** 메시지 스트리밍 완료 시 호출되는 콜백 */
  onMessageComplete: (message: ChatMessage) => void;
  /** 에러 발생 시 호출되는 콜백 */
  onError: (error: string) => void;
}

/**
 * useChatStreamingCore 훅 반환 타입
 */
export interface UseChatStreamingCoreReturn {
  /** WebSocket 연결 상태 */
  isConnected: boolean;
  /** 현재 스트리밍 상태 */
  streamingState: StreamingState;
  /** 현재 스트리밍 중인 메시지 */
  streamingMessage: StreamingMessage | null;
  /** WebSocket 연결 시작 */
  connect: () => Promise<void>;
  /** WebSocket 연결 해제 */
  disconnect: () => void;
  /** 스트리밍 메시지 전송 (메시지 ID 반환, 실패 시 null) */
  sendStreamingMessage: (content: string) => string | null;
}

/**
 * 스트리밍 관리 핵심 훅
 *
 * @param service - 주입받은 Chat WebSocket 서비스
 * @param props - 훅 옵션 (sessionId, onMessageComplete, onError)
 * @returns 스트리밍 관련 상태 및 함수
 */
export function useChatStreamingCore(
  service: IChatWebSocketService,
  { sessionId, onMessageComplete, onError }: UseChatStreamingCoreProps
): UseChatStreamingCoreReturn {
  // 상태 관리
  const [isConnected, setIsConnected] = useState(false);
  const [streamingState, setStreamingState] = useState<StreamingState>('idle');
  const [streamingMessage, setStreamingMessage] =
    useState<StreamingMessage | null>(null);

  // 콜백 ref (useEffect 내에서 최신 콜백 참조)
  const onMessageCompleteRef = useRef(onMessageComplete);
  const onErrorRef = useRef(onError);

  // 콜백 ref 업데이트
  useEffect(() => {
    onMessageCompleteRef.current = onMessageComplete;
    onErrorRef.current = onError;
  }, [onMessageComplete, onError]);

  /**
   * WebSocket 연결 시작
   */
  const connect = useCallback(async () => {
    if (!sessionId) {
      logger.warn('세션 ID 없이 WebSocket 연결 시도');
      return;
    }

    // Fallback 세션은 WebSocket 연결 불가
    if (sessionId.startsWith('fallback-')) {
      logger.warn('Fallback 세션은 WebSocket 연결을 지원하지 않습니다.');
      return;
    }

    try {
      await service.connect(sessionId);
      setIsConnected(true);
    } catch (error) {
      logger.error('WebSocket 연결 실패:', error);
      setIsConnected(false);
    }
  }, [sessionId, service]);

  /**
   * WebSocket 연결 해제
   */
  const disconnect = useCallback(() => {
    service.disconnect();
    setIsConnected(false);
    setStreamingState('idle');
    setStreamingMessage(null);
  }, [service]);

  /**
   * 스트리밍 메시지 전송
   *
   * @param content - 전송할 메시지 내용
   * @returns 메시지 ID (성공 시) 또는 null (실패 시)
   */
  const sendStreamingMessage = useCallback(
    (content: string): string | null => {
      if (!isConnected) {
        logger.error('WebSocket이 연결되지 않은 상태에서 메시지 전송 시도');
        return null;
      }

      try {
        const messageId = service.sendMessage(content);
        setStreamingMessage({
          id: messageId,
          content: '',
          state: 'streaming',
        });
        setStreamingState('streaming');
        return messageId;
      } catch (error) {
        logger.error('메시지 전송 실패:', error);
        onErrorRef.current('메시지 전송에 실패했습니다.');
        return null;
      }
    },
    [isConnected, service]
  );

  /**
   * 서비스 이벤트 리스너 등록
   */
  useEffect(() => {
    /**
     * 연결 상태 변경 처리
     */
    const handleConnection = (data: unknown) => {
      const { connected } = data as ConnectionEventData;
      setIsConnected(connected);
      if (!connected) {
        setStreamingState('idle');
      }
    };

    /**
     * 스트리밍 시작 처리
     */
    const handleStreamStart = () => {
      setStreamingState('streaming');
    };

    /**
     * 스트리밍 토큰 처리 (응답 텍스트 누적)
     */
    const handleStreamToken = (data: unknown) => {
      const { message_id, token } = data as StreamTokenMessage;
      setStreamingMessage((prev) => {
        // 새 메시지이거나 ID가 다른 경우 새로 시작
        if (!prev || prev.id !== message_id) {
          return { id: message_id, content: token, state: 'streaming' };
        }
        // 기존 메시지에 토큰 누적
        return { ...prev, content: prev.content + token };
      });
    };

    /**
     * 스트리밍 소스 처리 (RAG 참조 문서)
     */
    const handleStreamSources = (data: unknown) => {
      const { message_id, sources } = data as StreamSourcesMessage;
      setStreamingMessage((prev) => {
        if (!prev || prev.id !== message_id) return prev;
        return { ...prev, sources };
      });
    };

    /**
     * 스트리밍 완료 처리
     */
    const handleStreamEnd = (data: unknown) => {
      const { message_id } = data as StreamEndMessage;
      setStreamingMessage((prev) => {
        if (!prev || prev.id !== message_id) return prev;

        // 완료된 메시지 객체 생성
        const completedMessage: ChatMessage = {
          id: prev.id,
          role: 'assistant',
          content: prev.content,
          timestamp: new Date().toISOString(),
          sources: prev.sources,
        };

        // 다음 틱에 콜백 호출 (상태 업데이트 후)
        setTimeout(() => {
          onMessageCompleteRef.current(completedMessage);
        }, 0);

        return null;
      });
      setStreamingState('idle');
    };

    /**
     * 스트리밍 에러 처리
     */
    const handleStreamError = (data: unknown) => {
      const { message_id, message, solutions } = data as StreamErrorMessage;
      const errorMessage = solutions?.length
        ? `${message}\n해결 방법: ${solutions.join(', ')}`
        : message;

      setStreamingMessage((prev) => {
        if (!prev || prev.id !== message_id) return prev;
        return { ...prev, state: 'error', error: errorMessage };
      });

      setStreamingState('error');
      onErrorRef.current(errorMessage);
    };

    /**
     * 재연결 실패 처리
     */
    const handleReconnectFailed = () => {
      onErrorRef.current(
        '서버 연결이 끊어졌습니다. 페이지를 새로고침해주세요.'
      );
    };

    // 이벤트 리스너 등록
    service.on('connection', handleConnection);
    service.on('stream_start', handleStreamStart);
    service.on('stream_token', handleStreamToken);
    service.on('stream_sources', handleStreamSources);
    service.on('stream_end', handleStreamEnd);
    service.on('stream_error', handleStreamError);
    service.on('reconnect_failed', handleReconnectFailed);

    // 클린업: 이벤트 리스너 제거
    return () => {
      service.off('connection', handleConnection);
      service.off('stream_start', handleStreamStart);
      service.off('stream_token', handleStreamToken);
      service.off('stream_sources', handleStreamSources);
      service.off('stream_end', handleStreamEnd);
      service.off('stream_error', handleStreamError);
      service.off('reconnect_failed', handleReconnectFailed);
    };
  }, [service]);

  return {
    isConnected,
    streamingState,
    streamingMessage,
    connect,
    disconnect,
    sendStreamingMessage,
  };
}
