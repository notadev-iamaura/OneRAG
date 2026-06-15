import axios from 'axios';
import axiosRetry from 'axios-retry';
import {
  HealthStatus,
  Document,
  ApiDocument,
  UploadResponse,
  UploadStatus,
  ChatResponse,
  ChatHistoryEntry,
  SessionInfo,
  Source,
  SourceDetail,
} from '../types';
import type {
  StreamChatEvent,
  StreamChatClientOptions,
} from '../types/chatStreaming';
import { logger } from '../utils/logger';
import { maskPhoneNumberDeep } from '../utils/privacy';
import { getOperatorApiBaseUrl } from '../config/operatorSettings';

// Railway 배포 최적화 API URL 관리
const getAPIBaseURL = (): string => {
  const operatorApiUrl = getOperatorApiBaseUrl();
  if (operatorApiUrl) {
    logger.log('API URL 소스: 운영 설정');
    return operatorApiUrl;
  }

  // 1순위: 런타임 설정의 "비어있지 않은" 값만 인정한다(배포 후 동적 변경 가능).
  // 빈 문자열(미설정)은 무시해 빌드 타임 설정(VITE_API_BASE_URL)을 가리지 않게 한다(#15).
  // generate-config.js는 env 미설정 시 API_BASE_URL: ''를 항상 내보내므로, 과거처럼
  // hasOwnProperty + (값 || '')로 처리하면 same-origin이 강제되어 백엔드 URL을 덮어썼다.
  const runtimeUrl =
    typeof window !== 'undefined' && window.RUNTIME_CONFIG
      ? window.RUNTIME_CONFIG.API_BASE_URL
      : undefined;
  if (typeof runtimeUrl === 'string' && runtimeUrl.length > 0) {
    logger.log('API URL 소스: 런타임 설정 (config.js)');
    return runtimeUrl;
  }

  // 2순위: 빌드 타임 환경변수 (VITE_API_BASE_URL)
  if (import.meta.env.VITE_API_BASE_URL) {
    logger.log('API URL 소스: Railway 환경변수 (VITE_API_BASE_URL)');
    return import.meta.env.VITE_API_BASE_URL;
  }

  // 개발 모드: 환경변수로 직접 백엔드 URL 사용 (프록시 대신)
  if (import.meta.env.DEV) {
    const devApiUrl = import.meta.env.VITE_DEV_API_BASE_URL || 'http://localhost:8000';
    logger.log('개발 모드: 직접 백엔드 URL 사용:', devApiUrl);
    return devApiUrl;
  }

  // 아무 것도 설정되지 않은 경우에만 same-origin 폴백
  logger.log('API URL 소스: same-origin 폴백');
  return '';
};

const API_BASE_URL = getAPIBaseURL();

// 최종 API URL 정보 출력
logger.log('API Configuration:', {
  baseURL: API_BASE_URL || 'Using Vite proxy',
  environment: import.meta.env.MODE,
  isDev: import.meta.env.DEV,
  isProd: import.meta.env.PROD
});

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 300000, // 5분으로 연장 (큰 문서 처리 대응)
  headers: {
    'Content-Type': 'application/json',
  },
  // CORS 설정 추가 - Railway 백엔드 호환성
  withCredentials: false, // CORS 이슈 해결을 위해 credentials 비활성화
});

const isBinaryResponseData = (data: unknown): boolean => {
  if (typeof Blob !== 'undefined' && data instanceof Blob) {
    return true;
  }

  if (typeof ArrayBuffer !== 'undefined' && data instanceof ArrayBuffer) {
    return true;
  }

  return typeof ArrayBuffer !== 'undefined' && ArrayBuffer.isView(data);
};

const shouldMaskResponseData = (response: {
  data: unknown;
  config?: { responseType?: string };
}): boolean => {
  if (!response.data || typeof response.data !== 'object') {
    return false;
  }

  const responseType = response.config?.responseType;
  if (responseType === 'blob' || responseType === 'arraybuffer' || responseType === 'stream') {
    return false;
  }

  return !isBinaryResponseData(response.data);
};

const getHeaderValue = (headers: unknown, headerName: string): unknown => {
  if (!headers || typeof headers !== 'object') {
    return undefined;
  }

  const headerAccessor = headers as { get?: (name: string) => unknown };
  if (typeof headerAccessor.get === 'function') {
    const value = headerAccessor.get(headerName);
    if (value !== undefined) {
      return value;
    }
  }

  const normalizedHeaderName = headerName.toLowerCase();
  for (const [key, value] of Object.entries(headers as Record<string, unknown>)) {
    if (key.toLowerCase() === normalizedHeaderName) {
      return value;
    }
  }

  return undefined;
};

const summarizeSensitiveHeader = (headers: unknown, headerName: string): string => {
  return getHeaderValue(headers, headerName) ? '설정됨' : '없음';
};

const summarizePayloadForLog = (payload: unknown): string | null => {
  if (payload === undefined || payload === null) {
    return null;
  }

  if (typeof FormData !== 'undefined' && payload instanceof FormData) {
    return 'FormData';
  }

  if (typeof Blob !== 'undefined' && payload instanceof Blob) {
    return 'Blob';
  }

  if (isBinaryResponseData(payload)) {
    return 'binary';
  }

  if (Array.isArray(payload)) {
    return `array(${payload.length})`;
  }

  if (typeof payload === 'string') {
    return `string(${payload.length})`;
  }

  return typeof payload;
};

const summarizeHeadersForLog = (headers: unknown) => ({
  authorization: summarizeSensitiveHeader(headers, 'Authorization'),
  csrfToken: summarizeSensitiveHeader(headers, 'X-XSRF-TOKEN'),
  sessionId: summarizeSensitiveHeader(headers, 'X-Session-Id'),
  contentType: getHeaderValue(headers, 'Content-Type') ? '설정됨' : '없음',
});

// Axios 재시도 설정
axiosRetry(api, {
  retries: 3, // 최대 3회 재시도
  retryDelay: axiosRetry.exponentialDelay, // 지수 백오프 (1초, 2초, 4초)
  retryCondition: (error) => {
    // 네트워크 오류 또는 5xx 서버 오류 시 재시도
    return axiosRetry.isNetworkOrIdempotentRequestError(error) ||
      error.response?.status === 429 || // Rate limiting
      (error.response?.status !== undefined && error.response.status >= 500);
  },
  onRetry: (retryCount, error) => {
    logger.warn(`API 재시도 (${retryCount}/3):`, {
      url: error.config?.url,
      method: error.config?.method,
      status: error.response?.status,
    });
  },
});

/**
 * CSRF 토큰 조회 헬퍼
 */
const getCsrfToken = (): string | null => {
  const name = 'XSRF-TOKEN';
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) {
    return parts.pop()?.split(';').shift() || null;
  }
  return null;
};

// Request interceptor
api.interceptors.request.use(
  (config) => {
    const runtimeBaseURL = getAPIBaseURL();
    if (runtimeBaseURL && config.baseURL !== runtimeBaseURL) {
      config.baseURL = runtimeBaseURL;
    }

    // 세션 생성 API 호출 시 상세 로깅
    if (config.url === '/api/chat/session') {
      logger.log('세션 생성 요청 상세 정보:', {
        url: `${config.baseURL}${config.url}`,
        method: config.method,
        data: config.data,
        headers: {
          'Authorization': config.headers.Authorization ? '설정됨' : '없음',
          'X-Session-Id': config.headers['X-Session-Id'] || '없음 (새 세션 생성이므로 정상)',
          'Content-Type': config.headers['Content-Type'] || '없음',
        },
        timeout: config.timeout,
      });
    }

    // 1. JWT Access Token 추가
    const tokens = localStorage.getItem('auth_tokens');
    if (tokens) {
      try {
        const { accessToken } = JSON.parse(tokens);
        if (accessToken) {
          config.headers.Authorization = `Bearer ${accessToken}`;
        }
      } catch (error) {
        logger.warn('JWT 토큰 파싱 실패:', error);
      }
    }

    // 2. 세션 ID 추가 (chatSessionId 우선, 구버전 호환을 위해 sessionId 폴백)
    // 단, 새 세션 생성 요청(/api/chat/session POST)에는 세션 ID를 보내지 않음
    const isNewSessionRequest = config.url === '/api/chat/session' && config.method?.toLowerCase() === 'post';
    if (!isNewSessionRequest) {
      const sessionId = localStorage.getItem('chatSessionId') || localStorage.getItem('sessionId');
      if (sessionId) {
        config.headers['X-Session-Id'] = sessionId;
      }
    }

    // 3. CSRF 토큰 추가 (POST, PUT, DELETE, PATCH 요청)
    if (['post', 'put', 'delete', 'patch'].includes(config.method?.toLowerCase() || '')) {
      const csrfToken = getCsrfToken();
      if (csrfToken) {
        config.headers['X-XSRF-TOKEN'] = csrfToken;
      }
    }

    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor
api.interceptors.response.use(
  (response) => {
    // 세션 생성 API 응답 시 상세 로깅
    if (response.config.url === '/api/chat/session') {
      logger.log('세션 생성 응답 성공:', {
        status: response.status,
        data: response.data,
        headers: response.headers,
      });
    }

    // 전화번호 자동 마스킹 (응답 데이터에 적용)
    // 성능 최적화: response.data가 객체 또는 배열인 경우에만 처리
    if (shouldMaskResponseData(response)) {
      try {
        response.data = maskPhoneNumberDeep(response.data);
      } catch (maskingError) {
        // 마스킹 실패 시 원본 데이터 유지 (안전 장치)
        logger.warn('전화번호 마스킹 실패, 원본 데이터 반환:', maskingError);
      }
    }

    return response;
  },
  async (error) => {
    const originalRequest = error.config;

    // 세션 생성 API 에러 시 상세 로깅
    if (originalRequest?.url === '/api/chat/session') {
      const errorDetails = {
        message: error.message,
        code: error.code,
        status: error.response?.status,
        statusText: error.response?.statusText,
        responseData: summarizePayloadForLog(error.response?.data),
        requestHeaders: summarizeHeadersForLog(originalRequest.headers),
        requestData: summarizePayloadForLog(originalRequest.data),
        config: {
          baseURL: originalRequest.baseURL,
          url: originalRequest.url,
          method: originalRequest.method,
          timeout: originalRequest.timeout,
        },
      };
      logger.error('세션 생성 응답 실패:', errorDetails);
    }

    // 401 에러 처리: JWT 토큰 갱신 시도
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        // authService를 동적으로 import하여 순환 참조 방지
        const { authService } = await import('./authService');

        // 토큰 갱신 시도
        const newTokens = await authService.refreshToken();

        // 새 토큰으로 헤더 업데이트
        originalRequest.headers.Authorization = `Bearer ${newTokens.accessToken}`;

        // 원래 요청 재시도
        return api(originalRequest);
      } catch (refreshError) {
        // 토큰 갱신 실패 시 로그아웃 처리
        logger.error('토큰 갱신 실패, 로그아웃 처리:', refreshError);
        localStorage.removeItem('auth_tokens');
        localStorage.removeItem('user_info');
        localStorage.removeItem('sessionId');
        localStorage.removeItem('chatSessionId');

        // 랜딩 페이지로 리다이렉션 (/login 라우트가 없으므로 /로 이동)
        if (window.location.pathname !== '/') {
          window.location.href = '/';
        }

        return Promise.reject(refreshError);
      }
    }

    // 403 에러: 권한 없음
    if (error.response?.status === 403) {
      logger.warn('접근 권한 없음 (403 Forbidden)');
    }

    // CORS 오류 상세 로깅
    if (error.code === 'ERR_NETWORK' || error.message.includes('CORS')) {
      logger.warn('CORS 오류 감지:', {
        message: error.message,
        config: error.config ? {
          baseURL: error.config.baseURL,
          url: error.config.url,
          method: error.config.method,
          timeout: error.config.timeout,
          headers: summarizeHeadersForLog(error.config.headers),
          data: summarizePayloadForLog(error.config.data),
        } : null,
        백엔드_URL: API_BASE_URL
      });
    }

    return Promise.reject(error);
  }
);

// Health Check API
export const healthAPI = {
  check: () => {
    const healthApi = axios.create({
      baseURL: API_BASE_URL,
      timeout: 15000, // 15초로 설정
      headers: {
        'Content-Type': 'application/json',
      },
      withCredentials: false,
    });
    return healthApi.get<HealthStatus>('/health');
  },
};

// 고유한 임시 ID 생성을 위한 카운터
let tempIdCounter = 0;

// API 응답을 UI용 데이터로 변환하는 함수
const transformApiDocument = (apiDoc: ApiDocument): Document => {
  // 백엔드 응답에서 filename이 있으면 사용, 없으면 기본값
  const documentTitle = apiDoc.filename || 'Unknown Document';

  // 날짜 처리: 유효한 날짜인지 확인하고 변환
  const getValidDate = (dateString: string): string => {
    try {
      const date = new Date(dateString);
      // 1970년 이전이거나 유효하지 않은 날짜인 경우 현재 시간 사용
      if (isNaN(date.getTime()) || date.getFullYear() < 1990) {
        return new Date().toISOString();
      }
      return date.toISOString();
    } catch {
      return new Date().toISOString();
    }
  };

  return {
    id: apiDoc.id || `temp-${Date.now()}-${++tempIdCounter}-${Math.random().toString(36).substring(2, 11)}`, // 고유한 임시 ID 생성
    filename: documentTitle,
    originalName: documentTitle,
    size: apiDoc.file_size || 0,
    mimeType: 'application/octet-stream', // API에서 제공하지 않으므로 기본값
    uploadedAt: getValidDate(apiDoc.upload_date),
    status: (apiDoc.status as 'processing' | 'completed' | 'failed') || 'completed',
    chunks: apiDoc.chunk_count,
    metadata: {
      wordCount: 0, // 백엔드에서 제공하지 않으므로 기본값
    },
  };
};

// Document API
export const documentAPI = {
  // 문서 목록 조회
  // 백엔드 계약: 요청은 page_size, 응답 합계는 total_count.
  // 기존 호출부 호환을 위해 limit도 받아 page_size로 매핑하고,
  // 응답은 total ?? total_count 폴백으로 흡수한다.
  getDocuments: async (params?: {
    page?: number;
    limit?: number;
    page_size?: number;
    search?: string;
    status?: string;
  }) => {
    const { limit, page_size: pageSize, ...restParams } = params ?? {};
    const requestedPageSize = pageSize ?? limit;
    const requestParams = {
      ...restParams,
      ...(requestedPageSize !== undefined ? { page_size: requestedPageSize } : {}),
    };
    const response = await api.get<{ documents: ApiDocument[]; total?: number; total_count?: number }>(
      '/api/upload/documents',
      { params: requestParams }
    );
    return {
      ...response,
      data: {
        documents: response.data.documents.map(transformApiDocument),
        total: response.data.total ?? response.data.total_count ?? 0,
      },
    };
  },

  // 문서 상세 조회
  getDocument: (id: string) => api.get<Document>(`/api/upload/documents/${id}`),

  // 문서 업로드
  upload: (file: File, onProgress?: (progress: number) => void, settings?: { splitterType?: string; chunkSize?: number; chunkOverlap?: number }) => {
    const formData = new FormData();
    formData.append('file', file);

    // 업로드 설정이 있으면 추가
    if (settings) {
      if (settings.splitterType) {
        formData.append('splitter_type', settings.splitterType);
      }
      if (settings.chunkSize) {
        formData.append('chunk_size', settings.chunkSize.toString());
      }
      if (settings.chunkOverlap) {
        formData.append('chunk_overlap', settings.chunkOverlap.toString());
      }
    }

    return api.post<UploadResponse>('/api/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(progress);
        }
      },
    });
  },

  // 업로드 상태 확인 (메인 api 인스턴스 사용으로 Auth interceptor 적용)
  getUploadStatus: (jobId: string) =>
    api.get<UploadStatus>(`/api/upload/status/${jobId}`, {
      timeout: 60000, // 1분으로 설정
    }),

  // 문서 삭제 (단일)
  deleteDocument: (id: string) =>
    api.delete(`/api/upload/documents/${id}`),

  // 문서 일괄 삭제
  deleteDocuments: (ids: string[]) =>
    api.post('/api/upload/documents/bulk-delete', { ids }),

  // 전체 문서 삭제
  deleteAllDocuments: (confirmCode: string, reason: string, dryRun?: boolean) =>
    api.delete('/api/documents/all', {
      params: { dry_run: dryRun || false },
      data: { confirm_code: confirmCode, reason }
    }),

  // 문서 다운로드
  downloadDocument: (id: string) =>
    api.get(`/api/upload/documents/${id}/download`, {
      responseType: 'blob',
    }),
};

// ============================================
// POST /chat/stream SSE 클라이언트
//
// EventSource는 POST body를 지원하지 않으므로 fetch + ReadableStream으로 구현한다.
// OneRAG 백엔드 SSE 라인 포맷: `event: {type}\ndata: {json}\n\n`
// (JapanRAG의 data-envelope 포맷과 달리, event 라인으로 타입을, data 라인으로 payload를 추출)
// ============================================

/** SSE 스트리밍 채팅 엔드포인트 절대 URL을 만든다(런타임 base URL 반영). */
const buildChatStreamUrl = (): string => {
  const baseUrl = getAPIBaseURL();
  // baseUrl이 빈 문자열(same-origin)이면 상대 경로로 호출한다.
  return `${baseUrl}/api/chat/stream`;
};

/**
 * 단일 SSE 블록(`event: ...\ndata: ...`)을 파싱해 StreamChatEvent로 만든다.
 * - event 라인: 이벤트 타입(metadata/chunk/done/error)
 * - data 라인(들): JSON payload (여러 줄이면 줄바꿈으로 결합)
 * data JSON에 event 필드가 없으면 event 라인 값으로 보강한다.
 */
const parseChatStreamBlock = (block: string): StreamChatEvent | null => {
  let eventType: string | undefined;
  const dataLines: string[] = [];

  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) {
      eventType = line.slice('event:'.length).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart());
    }
  }

  const dataText = dataLines.join('\n');
  if (!dataText) {
    return null;
  }

  const parsed = JSON.parse(dataText) as Record<string, unknown>;
  // data payload에 event 필드가 없으면 event 라인으로 보강한다.
  if (typeof parsed.event !== 'string' && eventType) {
    parsed.event = eventType;
  }
  return parsed as unknown as StreamChatEvent;
};

/** 파싱된 이벤트를 타입별 콜백으로 디스패치한다. */
const dispatchChatStreamEvent = (
  event: StreamChatEvent,
  options?: StreamChatClientOptions
): void => {
  options?.onEvent?.(event);
  if (event.event === 'chunk') {
    options?.onChunk?.(event);
  } else if (event.event === 'done') {
    options?.onDone?.(event);
  } else if (event.event === 'error') {
    options?.onError?.(event);
  }
};

/** SSE 응답 스트림을 읽어 블록 단위로 파싱·디스패치하고 전체 이벤트 배열을 반환한다. */
const collectChatStreamEvents = async (
  response: Response,
  options?: StreamChatClientOptions
): Promise<StreamChatEvent[]> => {
  if (!response.ok) {
    throw new Error(`SSE chat request failed with status ${response.status}`);
  }
  if (!response.body) {
    throw new Error('SSE chat response body is not readable.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const events: StreamChatEvent[] = [];
  let buffer = '';

  const consumeBlock = (block: string) => {
    if (!block.trim()) return;
    const event = parseChatStreamBlock(block);
    if (!event) return;
    events.push(event);
    dispatchChatStreamEvent(event, options);
  };

  // 빈 줄(\n\n 또는 \r\n\r\n) 기준으로 SSE 블록을 분리한다(CRLF/LF 혼용 안전).
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });

    let delimiterIndex = buffer.search(/\r?\n\r?\n/);
    while (delimiterIndex >= 0) {
      const blockText = buffer.slice(0, delimiterIndex);
      const delimiterLength = buffer.startsWith('\r\n\r\n', delimiterIndex) ? 4 : 2;
      buffer = buffer.slice(delimiterIndex + delimiterLength);
      consumeBlock(blockText);
      delimiterIndex = buffer.search(/\r?\n\r?\n/);
    }

    if (done) break;
  }

  // 스트림 종료 후 남은 버퍼도 마지막 블록으로 처리한다.
  if (buffer.trim()) {
    consumeBlock(buffer);
  }

  return events;
};

// Chat API
export const chatAPI = {
  // 메시지 전송
  sendMessage: (message: string, sessionId?: string) =>
    api.post<ChatResponse>('/api/chat', {
      message,
      session_id: sessionId || localStorage.getItem('chatSessionId')
    }),

  /**
   * POST /chat/stream SSE 스트리밍 채팅.
   *
   * fetch + ReadableStream으로 SSE를 수신하며, options.signal로 중단할 수 있다.
   * 각 이벤트는 onEvent/onChunk/onDone/onError 콜백으로 전달된다.
   */
  streamMessage: async (
    message: string,
    sessionId?: string,
    options?: StreamChatClientOptions
  ): Promise<StreamChatEvent[]> => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    };

    // JWT Access Token (axios 인터셉터와 동일한 출처)
    const tokens = localStorage.getItem('auth_tokens');
    if (tokens) {
      try {
        const { accessToken } = JSON.parse(tokens);
        if (accessToken) {
          headers.Authorization = `Bearer ${accessToken}`;
        }
      } catch (error) {
        logger.warn('JWT 토큰 파싱 실패:', error);
      }
    }

    const effectiveSessionId = sessionId || localStorage.getItem('chatSessionId') || undefined;
    if (effectiveSessionId) {
      headers['X-Session-Id'] = effectiveSessionId;
    }

    const csrfToken = getCsrfToken();
    if (csrfToken) {
      headers['X-XSRF-TOKEN'] = csrfToken;
    }

    const requestInit: RequestInit = {
      method: 'POST',
      headers,
      body: JSON.stringify({
        message,
        session_id: effectiveSessionId ?? null,
        options: options?.options,
      }),
    };
    if (options?.signal) {
      requestInit.signal = options.signal;
    }

    const response = await fetch(buildChatStreamUrl(), requestInit);
    return collectChatStreamEvents(response, options);
  },

  // 채팅 기록 조회
  getChatHistory: (sessionId: string) =>
    api.get<{ messages: ChatHistoryEntry[] }>(`/api/chat/history/${sessionId}`),

  // 새 세션 시작 - 백엔드에서 새로운 채팅 세션 ID 생성
  startNewSession: () => {
    // 기존 api 인스턴스 사용하되 타임아웃만 다르게 설정
    logger.log('세션 생성 API 호출 시작:', {
      baseURL: API_BASE_URL,
      endpoint: '/api/chat/session',
    });

    return api.post<{ session_id: string; ws_token?: string | null }>('/api/chat/session', {}, {
      timeout: 30000, // 30초 타임아웃
    });
  },

  // 세션 정보 조회
  getSessionInfo: (sessionId: string) =>
    api.get<SessionInfo>(`/api/chat/session/${sessionId}/info`),

  /**
   * 청크(인용 출처) 전체 상세 조회 (lazy).
   *
   * content_preview([:300] 절단본) 대신 전체 원문을 받아오기 위한 호출.
   * source_id/document_id가 없으면 호출 자체를 거부한다.
   *
   * 주의: 이 엔드포인트는 백엔드 지원이 필요하다(GET /api/upload/documents/{document_id}/sources/{source_id}).
   * 백엔드가 아직 미지원이면 호출이 실패하므로, 호출부(useChatInteraction)에서
   * content_preview로 graceful fallback 처리한다.
   */
  getSourceDetail: (source: Pick<Source, 'source_id' | 'document_id' | 'page' | 'chunk'>) => {
    const documentId = source.document_id;
    const sourceId = source.source_id;
    if (!documentId || !sourceId) {
      return Promise.reject(new Error('source_id 또는 document_id가 없어 상세 조회를 할 수 없습니다.'));
    }
    return api.get<SourceDetail>(
      `/api/upload/documents/${encodeURIComponent(documentId)}/sources/${encodeURIComponent(sourceId)}`,
      {
        params: {
          page: source.page ?? undefined,
          chunk: source.chunk ?? undefined,
        },
      }
    );
  },
};

export default api;
