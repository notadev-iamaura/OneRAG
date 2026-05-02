/**
 * Chat API DI 패턴을 위한 타입 정의
 *
 * WebSocket DI 패턴(websocket.ts)과 동일한 구조를 따릅니다.
 * - 인터페이스 기반 추상화로 테스트 용이성 확보
 * - 팩토리 함수 타입으로 의존성 주입 지원
 * - 설정 타입으로 API 클라이언트 구성 관리
 *
 * @example
 * // 프로덕션: 실제 API 서비스 사용
 * const service = createChatAPIService({ baseURL: 'http://localhost:8000', timeout: 30000 });
 *
 * // 테스트: Mock 서비스 주입
 * const mockService: IChatAPIService = { sendMessage: vi.fn(), ... };
 */

import type { AxiosResponse } from 'axios';
import { getOperatorApiBaseUrl } from '../config/operatorSettings';

// ============================================================================
// 응답 타입 정의
// ============================================================================

/**
 * 검색 결과 소스 정보
 *
 * 채팅 응답에 포함되는 검색 결과 출처 정보입니다.
 * 기존 Source 타입과 호환되도록 최소한의 필수 필드만 정의합니다.
 */
export interface ChatAPISearchSource {
  /** 문서 제목 */
  title: string;
  /** 문서 내용 또는 미리보기 */
  content: string;
  /** 관련성 점수 (선택) */
  score?: number;
  /** 추가 메타데이터 (선택) */
  metadata?: Record<string, unknown>;
}

/**
 * Chat API 응답
 *
 * sendMessage 호출 시 반환되는 응답 데이터입니다.
 * 기존 ChatResponse 타입과 유사하지만, DI 패턴용으로 분리되었습니다.
 */
export interface ChatAPIResponse {
  /** AI 응답 답변 */
  answer: string;
  /** 세션 ID */
  session_id: string;
  /** 검색 결과 소스 목록 */
  sources: ChatAPISearchSource[];
  /** 추가 메타데이터 (선택) */
  metadata?: Record<string, unknown>;
}

/**
 * 세션 정보
 *
 * getSessionInfo 호출 시 반환되는 세션 상세 정보입니다.
 */
export interface ChatAPISessionInfo {
  /** 세션 ID */
  session_id: string;
  /** 세션 생성 일시 (ISO 8601 형식) */
  created_at: string;
  /** 세션 내 메시지 수 */
  message_count: number;
  /** 마지막 활동 일시 (선택, ISO 8601 형식) */
  last_activity?: string;
}

/**
 * 채팅 히스토리 항목
 *
 * getChatHistory 호출 시 반환되는 개별 메시지 항목입니다.
 */
export interface ChatAPIHistoryEntry {
  /** 메시지 역할: user(사용자), assistant(AI), system(시스템) */
  role: 'user' | 'assistant' | 'system';
  /** 메시지 내용 */
  content: string;
  /** 메시지 생성 일시 (ISO 8601 형식) */
  timestamp: string;
  /** 검색 결과 소스 (AI 응답 시, 선택) */
  sources?: ChatAPISearchSource[];
}

// ============================================================================
// 설정 타입 정의
// ============================================================================

/**
 * Chat API 설정
 *
 * API 클라이언트 초기화 시 사용되는 설정입니다.
 * WebSocketConfig와 동일한 패턴으로 설계되었습니다.
 */
export interface ChatAPIConfig {
  /**
   * API 기본 URL
   * @example 'http://localhost:8000'
   */
  baseURL: string;

  /**
   * 요청 타임아웃 (밀리초)
   * @default 30000
   */
  timeout: number;

  /**
   * 재시도 횟수 (선택)
   * 네트워크 오류 시 자동 재시도할 횟수입니다.
   * @default 3
   */
  retryAttempts?: number;

  /**
   * 재시도 지연 시간 (밀리초, 선택)
   * 재시도 사이의 대기 시간입니다.
   * @default 1000
   */
  retryDelay?: number;

  /**
   * API 키 (선택)
   * 인증이 필요한 경우 사용됩니다.
   */
  apiKey?: string;
}

// ============================================================================
// 서비스 인터페이스 정의
// ============================================================================

/**
 * Chat API 서비스 인터페이스
 *
 * DI 패턴을 위한 추상화된 인터페이스입니다.
 * 실제 구현체와 Mock 구현체 모두 이 인터페이스를 구현합니다.
 *
 * @example
 * // 실제 구현체
 * class ChatAPIService implements IChatAPIService {
 *   async sendMessage(message: string, sessionId?: string) { ... }
 * }
 *
 * // Mock 구현체 (테스트용)
 * const mockService: IChatAPIService = {
 *   sendMessage: vi.fn().mockResolvedValue({ data: { answer: 'mock' } }),
 *   ...
 * };
 */
export interface IChatAPIService {
  /**
   * 메시지 전송
   *
   * 사용자 메시지를 전송하고 AI 응답을 받습니다.
   *
   * @param message - 사용자 메시지
   * @param sessionId - 세션 ID (선택, 없으면 새 세션 생성)
   * @returns 채팅 응답
   */
  sendMessage(
    message: string,
    sessionId?: string
  ): Promise<AxiosResponse<ChatAPIResponse>>;

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
  ): Promise<AxiosResponse<{ messages: ChatAPIHistoryEntry[] }>>;

  /**
   * 새 세션 시작
   *
   * 새로운 채팅 세션을 생성합니다.
   *
   * @returns 새 세션 ID
   */
  startNewSession(): Promise<AxiosResponse<{ session_id: string }>>;

  /**
   * 세션 정보 조회
   *
   * 특정 세션의 상세 정보를 조회합니다.
   *
   * @param sessionId - 세션 ID
   * @returns 세션 정보
   */
  getSessionInfo(sessionId: string): Promise<AxiosResponse<ChatAPISessionInfo>>;
}

// ============================================================================
// 팩토리 타입 정의
// ============================================================================

/**
 * Chat API 서비스 팩토리 함수 타입
 *
 * DI 컨테이너에서 주입하는 핵심 타입입니다.
 * 설정을 받아 IChatAPIService 인스턴스를 반환합니다.
 *
 * @example
 * // 프로덕션 팩토리
 * const factory: ChatAPIFactory = (config) => new ChatAPIService(config);
 *
 * // 테스트 팩토리
 * const mockFactory: ChatAPIFactory = (config) => ({
 *   sendMessage: vi.fn(),
 *   getChatHistory: vi.fn(),
 *   startNewSession: vi.fn(),
 *   getSessionInfo: vi.fn(),
 * });
 *
 * @param config - Chat API 설정
 * @returns IChatAPIService 구현체
 */
export type ChatAPIFactory = (config: ChatAPIConfig) => IChatAPIService;

// ============================================================================
// 기본값 정의
// ============================================================================

/**
 * Chat API 기본 URL 해석
 *
 * api.ts의 getAPIBaseURL()과 동일한 우선순위 체인을 따릅니다:
 * 1. VITE_API_BASE_URL (빌드 타임)
 * 2. window.RUNTIME_CONFIG.API_BASE_URL (런타임)
 * 3. localhost:8000 (폴백)
 */
function getChatAPIBaseURL(): string {
  const operatorApiUrl = getOperatorApiBaseUrl();
  if (operatorApiUrl) {
    return operatorApiUrl;
  }

  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL;
  }
  if (typeof window !== 'undefined' && window.RUNTIME_CONFIG?.API_BASE_URL) {
    return window.RUNTIME_CONFIG.API_BASE_URL;
  }
  return 'http://localhost:8000';
}

/**
 * 기본 Chat API 설정
 *
 * 합리적인 기본값을 제공합니다.
 * - baseURL: api.ts와 동일한 URL 해석 로직 사용
 * - timeout: 30000ms (대용량 문서 처리 대응)
 * - retryAttempts: 3회 (네트워크 일시 장애 대응)
 * - retryDelay: 1000ms (서버 부하 방지)
 */
export const defaultChatAPIConfig: Required<Omit<ChatAPIConfig, 'apiKey'>> & {
  apiKey?: string;
} = {
  baseURL: getChatAPIBaseURL(),
  timeout: 30000,
  retryAttempts: 3,
  retryDelay: 1000,
  apiKey: undefined,
};
