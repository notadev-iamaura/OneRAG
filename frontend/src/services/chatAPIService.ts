/**
 * Chat API 서비스 팩토리
 *
 * DI 패턴을 위한 Chat API 서비스 생성 함수입니다.
 * WebSocketProvider와 동일한 패턴으로 구현되었습니다.
 *
 * @example
 * // 기본 설정으로 서비스 생성
 * const service = createChatAPIService({
 *   baseURL: 'http://localhost:8000',
 *   timeout: 30000,
 * });
 *
 * // 서비스 사용
 * const response = await service.sendMessage('안녕하세요');
 */

import axios from 'axios';
import type { AxiosInstance, AxiosResponse } from 'axios';
import type {
  IChatAPIService,
  ChatAPIConfig,
  ChatAPIResponse,
  ChatAPISessionInfo,
  ChatAPIHistoryEntry,
} from '../types/chatAPI';

/**
 * Chat API 서비스 생성 함수
 *
 * 주어진 설정으로 IChatAPIService 구현체를 생성합니다.
 *
 * @param config - Chat API 설정
 * @returns IChatAPIService 구현체
 */
export function createChatAPIService(config: ChatAPIConfig): IChatAPIService {
  // Axios 인스턴스 생성
  const axiosInstance: AxiosInstance = axios.create({
    baseURL: config.baseURL,
    timeout: config.timeout,
    headers: {
      'Content-Type': 'application/json',
    },
  });

  // API Key 헤더 설정 (있는 경우)
  if (config.apiKey) {
    axiosInstance.defaults.headers.common['X-API-Key'] = config.apiKey;
  }

  /**
   * localStorage에서 세션 ID 가져오기
   */
  function getSessionIdFromStorage(): string | null {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('chatSessionId');
    }
    return null;
  }

  return {
    /**
     * 메시지 전송
     *
     * 사용자 메시지를 전송하고 AI 응답을 받습니다.
     *
     * @param message - 사용자 메시지
     * @param sessionId - 세션 ID (선택, 없으면 localStorage에서 조회)
     * @returns 채팅 응답
     */
    sendMessage(
      message: string,
      sessionId?: string
    ): Promise<AxiosResponse<ChatAPIResponse>> {
      const effectiveSessionId = sessionId || getSessionIdFromStorage();

      return axiosInstance.post('/api/chat', {
        message,
        session_id: effectiveSessionId,
      });
    },

    /**
     * 채팅 히스토리 조회
     *
     * 특정 세션의 채팅 기록을 조회합니다.
     *
     * @param sessionId - 세션 ID
     * @returns 채팅 히스토리 목록
     */
    getChatHistory(
      sessionId: string
    ): Promise<AxiosResponse<{ messages: ChatAPIHistoryEntry[] }>> {
      return axiosInstance.get(`/api/chat/history/${sessionId}`);
    },

    /**
     * 새 세션 시작
     *
     * 새로운 채팅 세션을 생성합니다.
     *
     * @returns 새 세션 ID
     */
    startNewSession(): Promise<AxiosResponse<{ session_id: string; ws_token?: string | null }>> {
      return axiosInstance.post('/api/chat/session', {}, { timeout: 30000 });
    },

    /**
     * 세션 정보 조회
     *
     * 특정 세션의 상세 정보를 조회합니다.
     *
     * @param sessionId - 세션 ID
     * @returns 세션 정보
     */
    getSessionInfo(
      sessionId: string
    ): Promise<AxiosResponse<ChatAPISessionInfo>> {
      return axiosInstance.get(`/api/chat/session/${sessionId}/info`);
    },
  };
}
