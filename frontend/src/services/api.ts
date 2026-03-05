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
} from '../types';
import { logger } from '../utils/logger';
import { maskPhoneNumberDeep } from '../utils/privacy';

// Railway 배포 최적화 API URL 관리
const getAPIBaseURL = (): string => {
  // 개발 모드: 환경변수로 직접 백엔드 URL 사용 (프록시 대신)
  if (import.meta.env.DEV) {
    // 개발 환경에서도 직접 백엔드 URL 사용 (프록시 타임아웃 문제 해결)
    // 기본값을 Railway 프로덕션 백엔드로 설정
    const devApiUrl = import.meta.env.VITE_DEV_API_BASE_URL || 'http://localhost:8000';
    logger.log('개발 모드: 직접 백엔드 URL 사용:', devApiUrl);
    return devApiUrl;
  }

  // 1순위: Railway 환경변수 (VITE_API_BASE_URL)
  if (import.meta.env.VITE_API_BASE_URL) {
    logger.log('API URL 소스: Railway 환경변수 (VITE_API_BASE_URL)');
    return import.meta.env.VITE_API_BASE_URL;
  }

  // 2순위: 런타임 설정 (동적 변경 가능)
  if (typeof window !== 'undefined' && window.RUNTIME_CONFIG?.API_BASE_URL) {
    logger.log('API URL 소스: 런타임 설정 (config.js)');
    return window.RUNTIME_CONFIG.API_BASE_URL;
  }

  // 3순위: localhost 폴백 (개발용)
  const fallbackUrl = 'http://localhost:8000';

  // 프로덕션 환경 체크
  const isProduction = import.meta.env.PROD ||
    (typeof window !== 'undefined' && window.location.hostname !== 'localhost');

  if (isProduction) {
    logger.warn(
      'Railway 배포 환경 설정 필요:\n' +
      '1. Railway 대시보드에서 VITE_API_BASE_URL 환경변수 설정\n' +
      '2. 또는 public/config.js에서 API_BASE_URL 설정\n' +
      `현재 폴백 URL 사용 중: ${fallbackUrl}`
    );
  } else {
    logger.log('로컬 개발 환경: localhost:8000 사용');
  }

  return fallbackUrl;
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
    // 0. API Key 추가 (/api/* 경로에만 적용, /health는 제외)
    const isApiEndpoint = config.url?.startsWith('/api/');
    const isHealthEndpoint = config.url === '/health';

    if (isApiEndpoint && !isHealthEndpoint) {
      // 환경변수 우선 (빌드 타임)
      let apiKey = import.meta.env.VITE_API_KEY;

      // 런타임 설정 폴백 (Railway 배포 시 동적 설정)
      if (!apiKey && typeof window !== 'undefined' && window.RUNTIME_CONFIG?.API_KEY) {
        apiKey = window.RUNTIME_CONFIG.API_KEY;
      }

      if (apiKey) {
        config.headers['X-API-Key'] = apiKey;
      } else {
        logger.warn('API Key가 설정되지 않았습니다. /api/* 요청이 실패할 수 있습니다.');
        // 세션 생성 요청인 경우 더 자세한 경고
        if (config.url === '/api/chat/session') {
          logger.error('세션 생성 실패 원인: API Key가 설정되지 않았습니다.', {
            envKey: import.meta.env.VITE_API_KEY ? '있음' : '없음',
            runtimeKey: typeof window !== 'undefined' && window.RUNTIME_CONFIG?.API_KEY ? '있음' : '없음',
          });
        }
      }
    }

    // 세션 생성 API 호출 시 상세 로깅 (API Key 설정 후)
    if (config.url === '/api/chat/session') {
      logger.log('세션 생성 요청 상세 정보:', {
        url: `${config.baseURL}${config.url}`,
        method: config.method,
        data: config.data,
        headers: {
          'X-API-Key': config.headers['X-API-Key'] ? `${config.headers['X-API-Key'].substring(0, 8)}...` : '없음',
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
    if (response.data && typeof response.data === 'object') {
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
        data: error.response?.data,
        requestHeaders: originalRequest.headers,
        requestData: originalRequest.data,
        config: {
          url: `${originalRequest.baseURL}${originalRequest.url}`,
          method: originalRequest.method,
          timeout: originalRequest.timeout,
        },
      };
      logger.error('세션 생성 응답 실패:', JSON.stringify(errorDetails, null, 2));
      console.error('세션 생성 응답 실패 상세:', errorDetails);
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
        config: error.config,
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
  getDocuments: async (params?: {
    page?: number;
    limit?: number;
    search?: string;
    status?: string;
  }) => {
    const response = await api.get<{ documents: ApiDocument[]; total: number }>('/api/upload/documents', { params });
    return {
      ...response,
      data: {
        documents: response.data.documents.map(transformApiDocument),
        total: response.data.total,
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

// Chat API
export const chatAPI = {
  // 메시지 전송
  sendMessage: (message: string, sessionId?: string) =>
    api.post<ChatResponse>('/api/chat', {
      message,
      session_id: sessionId || localStorage.getItem('chatSessionId')
    }),

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

    return api.post<{ session_id: string }>('/api/chat/session', {}, {
      timeout: 30000, // 30초 타임아웃
    });
  },

  // 세션 정보 조회
  getSessionInfo: (sessionId: string) =>
    api.get<SessionInfo>(`/api/chat/session/${sessionId}/info`),
};

export default api;
