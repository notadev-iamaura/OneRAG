/**
 * useChatSessionCore - 세션 관리 핵심 로직
 *
 * IChatAPIService를 직접 주입받아 세션을 관리하는 순수 훅입니다.
 * DI Context 없이 서비스를 직접 전달받아 동작합니다.
 *
 * @example
 * // Core 훅 직접 사용 (테스트 또는 특수 케이스)
 * const session = useChatSessionCore(mockService, options);
 *
 * // 일반적인 사용은 useChatSession() 권장
 */

import { useState, useCallback, useEffect } from 'react';
import { AxiosError } from 'axios';
import { logger } from '../../utils/logger';
import {
  ChatMessage,
  ApiLog,
  SessionInfo,
  ChatTabProps,
} from '../../types/chat';
import type { IChatAPIService } from '../../types/chatAPI';
import { mapHistoryEntryToChatMessage } from '../../utils/chat/mappers';

// Axios 에러 응답 타입 정의
interface ApiErrorResponse {
  message?: string;
  error?: string;
}

/**
 * useChatSessionCore 훅 옵션
 */
export interface UseChatSessionCoreOptions {
  /** 토스트 메시지 표시 함수 */
  showToast: ChatTabProps['showToast'];
  /** 메시지 상태 설정 함수 */
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  /** API 로그 상태 설정 함수 */
  setApiLogs: React.Dispatch<React.SetStateAction<ApiLog[]>>;
  /** 세션 정보 상태 설정 함수 */
  setSessionInfo: React.Dispatch<React.SetStateAction<SessionInfo | null>>;
}

/**
 * useChatSessionCore 반환 타입
 */
export interface UseChatSessionCoreReturn {
  /** 현재 세션 ID */
  sessionId: string;
  /** 세션 초기화 완료 여부 */
  isSessionInitialized: boolean;
  /** 세션 ID 동기화 함수 */
  synchronizeSessionId: (newSessionId: string, context?: string) => boolean;
  /** 새 세션 시작 함수 */
  handleNewSession: () => Promise<void>;
}

/**
 * Fallback 세션 ID 생성
 */
function generateFallbackSessionId(): string {
  return `fallback-${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
}

/**
 * 세션 관리 핵심 훅
 *
 * @param chatAPI - 주입받은 Chat API 서비스
 * @param options - 훅 옵션
 * @returns 세션 관련 상태 및 함수
 */
export function useChatSessionCore(
  chatAPI: IChatAPIService,
  {
    showToast,
    setMessages,
    setApiLogs,
    setSessionInfo,
  }: UseChatSessionCoreOptions
): UseChatSessionCoreReturn {
  const [sessionId, setSessionId] = useState<string>('');
  const [isSessionInitialized, setIsSessionInitialized] = useState<boolean>(false);

  /**
   * 세션 ID 동기화
   * 새 세션 ID가 현재와 다르면 업데이트하고 localStorage에 저장
   */
  const synchronizeSessionId = useCallback((newSessionId: string, context: string = '') => {
    if (newSessionId && newSessionId !== sessionId) {
      logger.log(`세션 동기화 (${context}):`, {
        from: sessionId,
        to: newSessionId,
        context
      });

      setSessionId(newSessionId);
      localStorage.setItem('chatSessionId', newSessionId);

      if (context.includes('불일치') || context.includes('복구')) {
        showToast({
          type: 'info',
          message: `세션이 동기화되었습니다. (${context})`,
        });
      }
      return true;
    }
    return false;
  }, [sessionId, showToast]);

  /**
   * 세션 초기화
   * localStorage에 저장된 세션이 있으면 히스토리 로드, 없으면 새 세션 생성
   */
  const initializeSession = useCallback(async () => {
    if (isSessionInitialized) {
      logger.log('세션 초기화 이미 완료됨, 스킵');
      return;
    }

    let storedSessionId = localStorage.getItem('chatSessionId');

    // fallback 세션이면 새로 생성
    if (storedSessionId && storedSessionId.startsWith('fallback-')) {
      logger.log('fallback 세션 감지, 백엔드 세션 생성을 재시도합니다:', storedSessionId);
      localStorage.removeItem('chatSessionId');
      storedSessionId = null;
    }

    try {
      if (storedSessionId) {
        // 기존 세션 복구 시도
        logger.log('저장된 세션 ID로 초기화:', storedSessionId);
        setSessionId(storedSessionId);

        try {
          const response = await chatAPI.getChatHistory(storedSessionId);
          if (response.data.messages.length > 0) {
            const lastMessage = response.data.messages[response.data.messages.length - 1];
            const historySessionId = lastMessage?.session_id;

            if (historySessionId) {
              synchronizeSessionId(historySessionId, '기록 로드 시 불일치');
            }
          }

          const historyMessages = Array.isArray(response.data.messages)
            ? response.data.messages.map((msg, index) => mapHistoryEntryToChatMessage(msg, index))
            : [];

          setMessages(historyMessages);
          setIsSessionInitialized(true);
        } catch (historyError) {
          // 히스토리 로드 실패 시 새 세션 생성
          logger.warn('채팅 기록을 불러올 수 없습니다:', historyError);
          logger.log('세션 유효성 검증을 위해 새 세션 생성');

          const startTime = Date.now();
          const requestLogId = `session-validate-${Date.now()}`;
          const requestLog: ApiLog = {
            id: requestLogId,
            timestamp: new Date().toISOString(),
            type: 'request',
            method: 'POST',
            endpoint: '/api/chat/session',
            data: {},
          };
          setApiLogs((prev) => [...prev, requestLog]);

          try {
            const newSessionResponse = await chatAPI.startNewSession();
            const duration = Date.now() - startTime;
            const validSessionId = newSessionResponse.data.session_id;

            const responseLog: ApiLog = {
              id: `session-validate-res-${Date.now()}`,
              timestamp: new Date().toISOString(),
              type: 'response',
              method: 'POST',
              endpoint: '/api/chat/session',
              data: newSessionResponse.data,
              status: newSessionResponse.status,
              duration,
            };
            setApiLogs((prev) => [...prev, responseLog]);

            setSessionId(validSessionId);
            localStorage.setItem('chatSessionId', validSessionId);
            setIsSessionInitialized(true);

            showToast({
              type: 'info',
              message: '새로운 세션으로 시작합니다.',
            });
          } catch (newSessionError: unknown) {
            const duration = Date.now() - startTime;
            const errorLog: ApiLog = {
              id: `session-validate-err-${Date.now()}`,
              timestamp: new Date().toISOString(),
              type: 'response',
              method: 'POST',
              endpoint: '/api/chat/session',
              data: {
                error: newSessionError instanceof Error ? newSessionError.message : 'Unknown error',
              },
              status: (newSessionError as AxiosError<ApiErrorResponse>)?.response?.status || 0,
              duration,
            };
            setApiLogs((prev) => [...prev, errorLog]);

            // fallback 세션 생성
            const fallbackSessionId = generateFallbackSessionId();
            setSessionId(fallbackSessionId);
            setIsSessionInitialized(true);

            showToast({
              type: 'warning',
              message: '백엔드 연결 실패. 오프라인 모드로 동작합니다.',
            });
          }
        }
      } else {
        // 새 세션 생성
        logger.log('새 세션 생성');
        const startTime = Date.now();
        const requestLog: ApiLog = {
          id: `session-${Date.now()}`,
          timestamp: new Date().toISOString(),
          type: 'request',
          method: 'POST',
          endpoint: '/api/chat/session',
          data: {},
        };
        setApiLogs((prev) => [...prev, requestLog]);

        try {
          const response = await chatAPI.startNewSession();
          const duration = Date.now() - startTime;
          const newSessionId = response.data.session_id;

          const responseLog: ApiLog = {
            id: `session-res-${Date.now()}`,
            timestamp: new Date().toISOString(),
            type: 'response',
            method: 'POST',
            endpoint: '/api/chat/session',
            data: response.data,
            status: response.status,
            duration,
          };
          setApiLogs((prev) => [...prev, responseLog]);

          setSessionId(newSessionId);
          localStorage.setItem('chatSessionId', newSessionId);
          setIsSessionInitialized(true);
        } catch (error: unknown) {
          const duration = Date.now() - startTime;
          const errorLog: ApiLog = {
            id: `session-err-${Date.now()}`,
            timestamp: new Date().toISOString(),
            type: 'response',
            method: 'POST',
            endpoint: '/api/chat/session',
            data: {
              error: error instanceof Error ? error.message : 'Unknown error',
            },
            status: (error as AxiosError<ApiErrorResponse>)?.response?.status || 0,
            duration,
          };
          setApiLogs((prev) => [...prev, errorLog]);

          // fallback 세션 생성
          const fallbackSessionId = generateFallbackSessionId();
          setSessionId(fallbackSessionId);
          setIsSessionInitialized(true);

          showToast({
            type: 'warning',
            message: '백엔드 연결 실패. 오프라인 모드로 동작합니다.',
          });
        }
      }
    } catch (error) {
      logger.error('세션 초기화 실패:', error);
      const fallbackSessionId = generateFallbackSessionId();
      setSessionId(fallbackSessionId);
      setIsSessionInitialized(true);
      showToast({
        type: 'warning',
        message: '백엔드 연결 실패. 오프라인 모드로 동작합니다.',
      });
    }
  }, [chatAPI, showToast, synchronizeSessionId, isSessionInitialized, setMessages, setApiLogs]);

  // 컴포넌트 마운트 시 세션 초기화
  useEffect(() => {
    if (!isSessionInitialized) {
      initializeSession();
    }
  }, [isSessionInitialized, initializeSession]);

  /**
   * 새 세션 시작
   * 현재 세션을 버리고 새로운 세션을 생성
   */
  const handleNewSession = useCallback(async () => {
    try {
      logger.log('새 세션 시작 요청');
      const response = await chatAPI.startNewSession();
      const newSessionId = response.data.session_id;

      setSessionId(newSessionId);
      localStorage.setItem('chatSessionId', newSessionId);
      setMessages([]);
      setSessionInfo(null);

      showToast({
        type: 'success',
        message: '새로운 대화를 시작합니다.',
      });
    } catch (error) {
      logger.error('새 세션 시작 실패:', error);
      const fallbackSessionId = generateFallbackSessionId();
      setSessionId(fallbackSessionId);
      setMessages([]);
      setSessionInfo(null);

      showToast({
        type: 'warning',
        message: '백엔드 연결 실패. 오프라인 모드로 새 세션을 시작합니다.',
      });
    }
  }, [chatAPI, showToast, setMessages, setSessionInfo]);

  return {
    sessionId,
    isSessionInitialized,
    synchronizeSessionId,
    handleNewSession,
  };
}
