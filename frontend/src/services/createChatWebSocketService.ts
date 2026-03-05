/**
 * 채팅 스트리밍 WebSocket 서비스 팩토리 함수
 *
 * DI(의존성 주입) 패턴을 적용하여 테스트 시 Mock WebSocket 주입 가능
 * - 팩토리 함수로 WebSocket 생성 로직 분리
 * - 기존 chatWebSocketService의 모든 기능 유지
 * - 이벤트 리스너 시스템 (on/off/emit)
 * - 자동 재연결 (지수 백오프)
 *
 * @example
 * // 프로덕션: 기본 WebSocket 사용
 * const service = createChatWebSocketService();
 *
 * // 테스트: Mock WebSocket 주입
 * const mockFactory = (url) => new MockWebSocket(url);
 * const service = createChatWebSocketService(mockFactory);
 */

import { logger } from '../utils/logger';
import type {
  IWebSocket,
  WebSocketFactory,
  WebSocketConfig,
} from '../types/websocket';
import {
  defaultWebSocketFactory,
  defaultWebSocketConfig,
  WebSocketReadyState,
} from '../types/websocket';
import type {
  ChatWebSocketRequest,
  ChatWebSocketResponse,
  StreamingState,
  EventCallback,
} from '../types/chatStreaming';

/**
 * ChatWebSocketService 인터페이스
 *
 * 팩토리 함수가 반환하는 서비스 객체의 타입입니다.
 */
export interface IChatWebSocketService {
  /** WebSocket 연결 상태 */
  readonly isConnected: boolean;
  /** 현재 스트리밍 상태 */
  readonly currentState: StreamingState;

  /** WebSocket 연결 */
  connect(sessionId: string): Promise<void>;
  /** 메시지 전송 */
  sendMessage(content: string): string;
  /** 연결 해제 (이벤트 리스너 포함 전체 정리) */
  disconnect(): void;
  /** 연결만 해제 (이벤트 리스너 보존, handleStop용) */
  stop(): void;
  /** 이벤트 리스너 등록 */
  on(event: string, callback: EventCallback): void;
  /** 이벤트 리스너 제거 */
  off(event: string, callback: EventCallback): void;
  /** 재연결 횟수 초기화 */
  resetReconnectAttempts(): void;
}

/**
 * WebSocket 기본 URL 가져오기
 *
 * api.ts의 VITE_DEV_API_BASE_URL 또는 런타임 설정 사용
 */
const getWSBaseURL = (): string => {
  // 개발 모드: 환경변수 우선
  if (import.meta.env.DEV) {
    const devWsUrl = import.meta.env.VITE_DEV_WS_BASE_URL;
    if (devWsUrl) {
      return devWsUrl;
    }
    // HTTP URL을 WSS로 변환
    const devApiUrl =
      import.meta.env.VITE_DEV_API_BASE_URL ||
      'http://localhost:8000';
    return devApiUrl.replace('https://', 'wss://').replace('http://', 'ws://');
  }

  // 런타임 설정 우선
  if (typeof window !== 'undefined' && window.RUNTIME_CONFIG?.WS_BASE_URL) {
    return window.RUNTIME_CONFIG.WS_BASE_URL;
  }

  // 빌드 타임 환경 변수
  if (import.meta.env.VITE_WS_BASE_URL) {
    return import.meta.env.VITE_WS_BASE_URL;
  }

  // API URL에서 WS URL 유추
  if (import.meta.env.VITE_API_BASE_URL) {
    const apiUrl = import.meta.env.VITE_API_BASE_URL;
    return apiUrl.replace('https://', 'wss://').replace('http://', 'ws://');
  }

  // Railway 환경 자동 감지
  if (typeof window !== 'undefined') {
    const currentHost = window.location.host;
    if (
      currentHost.includes('railway.app') ||
      currentHost.includes('-production')
    ) {
      return `wss://${currentHost}`;
    }
  }

  // 기본값: localhost 폴백 (개발용)
  return 'ws://localhost:8000';
};

/**
 * ChatWebSocketService 팩토리 함수
 *
 * DI 패턴을 적용하여 WebSocket 팩토리를 외부에서 주입받습니다.
 *
 * @param createWebSocket - WebSocket 팩토리 함수 (기본값: 실제 WebSocket)
 * @param config - WebSocket 설정 (재연결 정책 등)
 * @returns IChatWebSocketService 인스턴스
 */
export function createChatWebSocketService(
  createWebSocket: WebSocketFactory = defaultWebSocketFactory,
  config: WebSocketConfig = {}
): IChatWebSocketService {
  // 설정 병합
  const mergedConfig = { ...defaultWebSocketConfig, ...config };

  // 내부 상태
  let ws: IWebSocket | null = null;
  let reconnectAttempts = 0;
  let state: StreamingState = 'idle';
  let sessionId: string | null = null;
  let reconnectTimeoutId: number | null = null;
  const eventListeners: Map<string, EventCallback[]> = new Map();

  logger.log('🚀 ChatWebSocketService 초기화 (DI 패턴)');

  /**
   * 이벤트 발생 (내부용)
   */
  const emit = (event: string, data: unknown): void => {
    const listeners = eventListeners.get(event);
    if (listeners) {
      listeners.forEach((callback) => {
        try {
          callback(data);
        } catch (error) {
          logger.error(`이벤트 핸들러 오류 [${event}]:`, error);
        }
      });
    }
  };

  /**
   * 재연결 스케줄링 (지수 백오프)
   */
  const scheduleReconnect = (): void => {
    if (reconnectAttempts >= mergedConfig.maxReconnectAttempts) {
      logger.error('❌ Chat WebSocket 재연결 최대 시도 횟수 초과');
      emit('reconnect_failed', {
        attempts: reconnectAttempts,
        maxAttempts: mergedConfig.maxReconnectAttempts,
      });
      return;
    }

    reconnectAttempts++;
    // 지수 백오프: interval, interval*2, interval*4, ...
    const delay =
      mergedConfig.reconnectInterval * Math.pow(2, reconnectAttempts - 1);

    logger.log(
      `🔄 Chat WebSocket 재연결 시도 ${reconnectAttempts}/${mergedConfig.maxReconnectAttempts} (${delay}ms 후)`
    );

    reconnectTimeoutId = window.setTimeout(() => {
      if (sessionId) {
        connect(sessionId).catch((error) => {
          logger.error('재연결 실패:', error);
        });
      }
    }, delay);
  };

  /**
   * 수신 메시지 처리
   */
  const handleMessage = (event: MessageEvent): void => {
    try {
      const data: ChatWebSocketResponse = JSON.parse(event.data);
      logger.log('📨 Chat WebSocket 메시지:', data.type, data.message_id);

      // 스트리밍 종료 상태 업데이트
      if (data.type === 'stream_end' || data.type === 'stream_error') {
        state = 'idle';
      }

      // 타입별 이벤트 발생
      emit(data.type, data);

      // 범용 message 이벤트도 발생 (모든 메시지 타입 수신 가능)
      emit('message', data);
    } catch (error) {
      logger.error('❌ Chat WebSocket 메시지 파싱 오류:', error, event.data);
      emit('parse_error', { error, rawData: event.data });
    }
  };

  /**
   * WebSocket 연결 초기화
   */
  const connect = (newSessionId: string): Promise<void> => {
    return new Promise((resolve, reject) => {
      // 이미 같은 세션으로 연결된 경우
      if (
        ws?.readyState === WebSocketReadyState.OPEN &&
        sessionId === newSessionId
      ) {
        logger.log('✅ Chat WebSocket 이미 연결됨');
        resolve();
        return;
      }

      // 기존 연결 정리
      if (ws) {
        ws.close(1000, '새 세션 연결');
        ws = null;
      }

      // 재연결 타이머 취소
      if (reconnectTimeoutId) {
        clearTimeout(reconnectTimeoutId);
        reconnectTimeoutId = null;
      }

      sessionId = newSessionId;
      state = 'connecting';

      const wsBaseUrl = getWSBaseURL();
      const wsUrl = `${wsBaseUrl}/chat-ws?session_id=${encodeURIComponent(newSessionId)}`;
      logger.log('🔗 Chat WebSocket 연결 시도:', wsUrl);

      try {
        // DI 핵심: 주입된 팩토리로 WebSocket 생성
        ws = createWebSocket(wsUrl);

        // 연결 성공
        ws.onopen = () => {
          logger.log('✅ Chat WebSocket 연결됨');
          reconnectAttempts = 0;
          state = 'idle';
          emit('connection', { connected: true });
          resolve();
        };

        // 메시지 수신
        ws.onmessage = (event) => {
          handleMessage(event);
        };

        // 연결 종료
        ws.onclose = (event) => {
          logger.log(
            '🔌 Chat WebSocket 연결 해제:',
            event.code,
            event.reason
          );
          state = 'idle';
          emit('connection', { connected: false });

          // 비정상 종료 시 재연결 시도 (정상 종료 코드 1000 제외)
          if (event.code !== 1000 && sessionId) {
            scheduleReconnect();
          }
        };

        // 에러 발생
        ws.onerror = (error) => {
          logger.error('❌ Chat WebSocket 오류:', error);
          state = 'error';
          emit('error', { error });
          reject(new Error('WebSocket 연결 실패'));
        };
      } catch (error) {
        logger.error('❌ Chat WebSocket 연결 실패:', error);
        state = 'error';
        reject(error);
      }
    });
  };

  /**
   * 메시지 전송 (스트리밍 시작)
   */
  const sendMessage = (content: string): string => {
    if (ws?.readyState !== WebSocketReadyState.OPEN) {
      throw new Error('WebSocket이 연결되지 않았습니다.');
    }

    if (!sessionId) {
      throw new Error('세션 ID가 설정되지 않았습니다.');
    }

    // 고유한 메시지 ID 생성
    const messageId = `msg_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;

    const request: ChatWebSocketRequest = {
      type: 'message',
      message_id: messageId,
      content,
      session_id: sessionId,
    };

    state = 'streaming';
    ws.send(JSON.stringify(request));

    logger.log('📤 Chat 메시지 전송:', {
      messageId,
      content: content.length > 50 ? content.substring(0, 50) + '...' : content,
    });

    return messageId;
  };

  /**
   * 이벤트 리스너 등록
   */
  const on = (event: string, callback: EventCallback): void => {
    if (!eventListeners.has(event)) {
      eventListeners.set(event, []);
    }
    eventListeners.get(event)!.push(callback);
  };

  /**
   * 이벤트 리스너 제거
   */
  const off = (event: string, callback: EventCallback): void => {
    const listeners = eventListeners.get(event);
    if (listeners) {
      const index = listeners.indexOf(callback);
      if (index > -1) {
        listeners.splice(index, 1);
      }
    }
  };

  /**
   * WebSocket 연결 해제 (이벤트 리스너 포함 전체 정리)
   */
  const disconnect = (): void => {
    // 재연결 타이머 취소
    if (reconnectTimeoutId) {
      clearTimeout(reconnectTimeoutId);
      reconnectTimeoutId = null;
    }

    if (ws) {
      logger.log('🔌 Chat WebSocket 연결 해제 (전체 정리)');
      ws.close(1000, '클라이언트 연결 해제');
      ws = null;
    }

    sessionId = null;
    state = 'idle';
    reconnectAttempts = 0;
    eventListeners.clear();
  };

  /**
   * WebSocket 연결만 해제 (이벤트 리스너 보존)
   * handleStop 등에서 사용 — 다음 메시지 전송 시 재연결 가능
   */
  const stop = (): void => {
    // 재연결 타이머 취소
    if (reconnectTimeoutId) {
      clearTimeout(reconnectTimeoutId);
      reconnectTimeoutId = null;
    }

    if (ws) {
      logger.log('⏹️ Chat WebSocket 연결 중단 (이벤트 리스너 보존)');
      ws.close(1000, '스트리밍 중단');
      ws = null;
    }

    state = 'idle';
    reconnectAttempts = 0;
    // 이벤트 리스너는 보존 — sessionId도 보존하여 재연결 가능
  };

  /**
   * 재연결 횟수 초기화
   */
  const resetReconnectAttempts = (): void => {
    reconnectAttempts = 0;
  };

  // 서비스 객체 반환
  return {
    get isConnected() {
      return ws?.readyState === WebSocketReadyState.OPEN;
    },
    get currentState() {
      return state;
    },
    connect,
    sendMessage,
    disconnect,
    stop,
    on,
    off,
    resetReconnectAttempts,
  };
}

/**
 * 기본 ChatWebSocketService 인스턴스
 *
 * 기존 싱글톤 패턴과 호환성 유지를 위해 제공합니다.
 * 새로운 코드에서는 createChatWebSocketService() 팩토리 함수를 직접 사용하세요.
 */
export const chatWebSocketServiceDI = createChatWebSocketService();
