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

import { useState, useCallback, useEffect, useRef } from 'react';
import { AxiosError } from 'axios';
import { logger } from '../../utils/logger';
import { createClientId } from '../../utils/clientId';
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
  /** 기존 세션으로 전환하고 히스토리를 로드하는 함수 */
  switchSession: (targetSessionId: string) => Promise<void>;
  /** 새 세션 시작 함수 */
  handleNewSession: () => Promise<void>;
}

// 세션 ID와 생성 시각을 저장하는 localStorage 키.
const CHAT_SESSION_ID_STORAGE_KEY = 'chatSessionId';
const CHAT_SESSION_CREATED_AT_STORAGE_KEY = 'chatSessionCreatedAt';

// 클라이언트 세션 복원 윈도우(30일).
// 대화 내용은 백엔드 PostgreSQL(postgres_chat_store)에 영속화되므로, PG가 진실원본이다.
// 짧은 윈도우로 저장된 세션을 폐기하면 PG에 멀쩡한 대화방이 있어도 다음 진입 시
// '방 사라짐'으로 보인다. 윈도우를 30일로 넉넉히 잡아 활성 사용자의 대화방이
// 클라이언트 만료로 사라지지 않게 한다.
const CHAT_SESSION_RESTORE_TTL_MS = 30 * 24 * 60 * 60 * 1000;

/**
 * 저장된 세션 생성 시각이 복원 가능한 윈도우(30일) 안에 있는지 판정한다.
 * 생성 시각이 없거나(레거시/누락) 만료됐으면 false.
 */
function isStoredChatSessionRestorable(createdAtValue: string | null): boolean {
  const createdAt = Number(createdAtValue);
  return (
    Number.isFinite(createdAt) &&
    createdAt > 0 &&
    createdAt >= Date.now() - CHAT_SESSION_RESTORE_TTL_MS
  );
}

/**
 * 세션 ID와 생성 시각을 함께 저장한다(복원 TTL 윈도우 기준점 갱신).
 * 히스토리 로드 성공/실패와 무관하게 '활성 세션'을 표시하는 용도로 호출한다.
 */
function persistChatSessionId(newSessionId: string): void {
  localStorage.setItem(CHAT_SESSION_ID_STORAGE_KEY, newSessionId);
  localStorage.setItem(CHAT_SESSION_CREATED_AT_STORAGE_KEY, String(Date.now()));
}

/**
 * 저장된 세션 ID와 생성 시각을 모두 제거한다(세션 폐기).
 */
function clearStoredChatSessionId(): void {
  localStorage.removeItem(CHAT_SESSION_ID_STORAGE_KEY);
  localStorage.removeItem(CHAT_SESSION_CREATED_AT_STORAGE_KEY);
}

/**
 * Fallback 세션 ID 생성
 */
function generateFallbackSessionId(): string {
  return createClientId('fallback');
}

function persistWebSocketToken(sessionId: string, token?: string | null): void {
  if (!token || typeof window === 'undefined') {
    return;
  }

  try {
    localStorage.setItem(`chatWsToken:${sessionId}`, token);
    localStorage.setItem('chatWsToken', token);
  } catch (error) {
    logger.warn('WebSocket 세션 토큰 저장 실패:', error);
  }
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

  // switchSession 빠른 연속 전환 race 방어용 토큰.
  // 가장 최근에 요청한 대상 세션 ID만 화면에 반영하고, 늦게 도착한 이전 응답은 버린다.
  const latestSelectRef = useRef<string | null>(null);

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
      persistChatSessionId(newSessionId);

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

  const switchSession = useCallback(async (targetSessionId: string) => {
    if (!targetSessionId || targetSessionId === sessionId) {
      return;
    }

    logger.log('세션 사이드바 전환:', { from: sessionId, to: targetSessionId });

    // 이번 전환을 최신 요청으로 표시 (빠른 연속 클릭 race 방어 토큰)
    latestSelectRef.current = targetSessionId;

    setMessages([]);
    setSessionInfo(null);
    // 이전 방의 API 로그를 초기화한다. RAG Trace 패널이 메시지에 트레이스가 없을 때
    // 보조로 참조하는 전역 로그가 새 방으로 넘어와 이전 방 메트릭을 고정 표시하는 것을 방지한다.
    setApiLogs([]);
    setSessionId(targetSessionId);
    persistChatSessionId(targetSessionId);

    try {
      const response = await chatAPI.getChatHistory(targetSessionId);

      // race 가드: await 동안 더 최신 전환이 발생했다면 이 응답은 버린다.
      // (늦게 도착한 이전 요청 응답이 최신 화면을 덮어쓰는 것을 방지)
      if (latestSelectRef.current !== targetSessionId) {
        logger.log('세션 전환 응답 무시 (더 최신 전환 존재):', {
          ignored: targetSessionId,
          latest: latestSelectRef.current,
        });
        return;
      }

      const historyMessages = Array.isArray(response.data.messages)
        ? response.data.messages.map((msg, index) => mapHistoryEntryToChatMessage(msg, index))
        : [];
      setMessages(historyMessages);
      setIsSessionInitialized(true);
    } catch (historyError) {
      // 늦게 도착한 이전 요청의 에러도 최신 화면에 영향 주지 않도록 가드
      if (latestSelectRef.current !== targetSessionId) {
        return;
      }
      logger.warn('선택한 세션의 채팅 기록을 불러올 수 없습니다:', historyError);
      setMessages([]);
      showToast({
        type: 'warning',
        message: '선택한 대화 기록을 불러올 수 없습니다.',
      });
    }
  }, [chatAPI, sessionId, setMessages, setSessionInfo, setApiLogs, showToast]);

  /**
   * 세션 초기화
   * localStorage에 저장된 세션이 있으면 히스토리 로드, 없으면 새 세션 생성
   */
  const initializeSession = useCallback(async () => {
    if (isSessionInitialized) {
      logger.log('세션 초기화 이미 완료됨, 스킵');
      return;
    }

    let storedSessionId = localStorage.getItem(CHAT_SESSION_ID_STORAGE_KEY);

    // fallback 세션이면 새로 생성
    if (storedSessionId && storedSessionId.startsWith('fallback-')) {
      logger.log('fallback 세션 감지, 백엔드 세션 생성을 재시도합니다:', storedSessionId);
      clearStoredChatSessionId();
      storedSessionId = null;
    }

    // 복원 윈도우(30일)를 벗어났거나 생성 시각이 없으면 새 세션을 생성한다.
    // (활성 사용자의 대화방은 30일 윈도우 안에서 그대로 유지된다.)
    if (
      storedSessionId &&
      !isStoredChatSessionRestorable(
        localStorage.getItem(CHAT_SESSION_CREATED_AT_STORAGE_KEY)
      )
    ) {
      logger.log('저장된 세션 생성 시각이 없거나 만료되어 새 세션을 생성합니다:', storedSessionId);
      clearStoredChatSessionId();
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
          // 복원 성공 → 생성 시각(TTL)을 갱신해 활성 세션으로 유지한다.
          persistChatSessionId(storedSessionId);
          setIsSessionInitialized(true);
        } catch (historyError) {
          // [대화방 소실 방지] 히스토리 로드 실패를 '세션 폐기'로 승격하지 않는다.
          //
          // 과거에는 일시적 네트워크/타임아웃/5xx/멀티 인스턴스 미스 한 번에도
          // 곧바로 새 세션을 생성해 localStorage의 session_id를 덮어썼다.
          // 그 결과 백엔드 PostgreSQL(postgres_chat_store)에 멀쩡한 대화방이
          // 있어도 그 참조를 영구 분실했다.
          //
          // OneRAG 백엔드는 대화를 PG에 영속화하고, 전송 시 같은 session_id로
          // 세션을 복원하므로(진실원본은 PG), 여기서는 저장된 세션을 그대로
          // 유지하고 빈 화면으로 진입한다. 사용자가 메시지를 보내면 백엔드가
          // 같은 대화방으로 이어주고, 다음 진입 시 이력도 정상 복원된다.
          logger.warn('채팅 기록 로드 실패 — 세션 유지(전송 시 복원):', historyError);
          setSessionId(storedSessionId);
          setMessages([]);
          // 생성 시각(TTL)을 갱신해 활성 세션으로 유지한다(일시 오류로 만료시키지 않음).
          persistChatSessionId(storedSessionId);
          setIsSessionInitialized(true);

          showToast({
            type: 'warning',
            message: '대화 기록을 불러오지 못했습니다. 메시지를 보내면 이어서 복원됩니다.',
          });
        }
      } else {
        // 새 세션 생성
        logger.log('새 세션 생성');
        const startTime = Date.now();
        const requestLog: ApiLog = {
          id: createClientId('session-request'),
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
            id: createClientId('session-response'),
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
          persistChatSessionId(newSessionId);
          persistWebSocketToken(newSessionId, response.data.ws_token);
          setIsSessionInitialized(true);
        } catch (error: unknown) {
          const duration = Date.now() - startTime;
          const errorLog: ApiLog = {
            id: createClientId('session-error'),
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
      persistChatSessionId(newSessionId);
      persistWebSocketToken(newSessionId, response.data.ws_token);
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
    switchSession,
    handleNewSession,
  };
}
