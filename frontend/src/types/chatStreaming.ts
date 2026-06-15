/**
 * 채팅 스트리밍 WebSocket 메시지 프로토콜 타입 정의
 *
 * 이 파일은 프론트엔드와 백엔드 간의 WebSocket 통신에 사용되는
 * 모든 메시지 타입을 정의합니다.
 */

import { Source } from './index';

// ============================================
// 클라이언트 → 서버 메시지 타입
// ============================================

/**
 * 클라이언트에서 서버로 전송하는 메시지
 */
export interface ChatWebSocketRequest {
  type: 'message';
  message_id: string;
  content: string;
  session_id: string;
}

// ============================================
// 서버 → 클라이언트 메시지 타입
// ============================================

/**
 * 스트리밍 시작 메시지
 * 서버가 응답 생성을 시작했음을 알림
 *
 * 백엔드 스키마: app/api/schemas/websocket.py::StreamStartEvent
 */
export interface StreamStartMessage {
  type: 'stream_start';
  message_id: string;
  session_id: string;
  timestamp: string; // ISO 8601 형식
}

/**
 * 스트리밍 토큰 메시지
 * LLM이 생성한 토큰 조각을 전달
 *
 * 백엔드 스키마: app/api/schemas/websocket.py::StreamTokenEvent
 */
export interface StreamTokenMessage {
  type: 'stream_token';
  message_id: string;
  token: string;
  index: number; // 토큰 인덱스 (0부터 시작)
}

/**
 * 스트리밍 소스 메시지
 * RAG 검색 결과 (참조 문서) 전달
 */
export interface StreamSourcesMessage {
  type: 'stream_sources';
  message_id: string;
  sources: Source[];
}

/**
 * 스트리밍 완료 메시지
 * 응답 생성이 완료되었음을 알림
 *
 * 백엔드 스키마: app/api/schemas/websocket.py::StreamEndEvent
 */
export interface StreamEndMessage {
  type: 'stream_end';
  message_id: string;
  total_tokens: number;
  processing_time_ms: number;
}

/**
 * 스트리밍 에러 메시지
 * 응답 생성 중 오류 발생
 *
 * 백엔드 스키마: app/api/schemas/websocket.py::WSStreamErrorEvent
 */
export interface StreamErrorMessage {
  type: 'stream_error';
  message_id: string;
  error_code: string; // 예: GEN-001, SEARCH-003, WS-001-INVALID_JSON
  message: string; // 사용자 친화적 에러 메시지
  solutions: string[]; // 해결 방법 목록
}

/**
 * 서버에서 클라이언트로 전송되는 모든 메시지 타입 (Union Type)
 */
export type ChatWebSocketResponse =
  | StreamStartMessage
  | StreamTokenMessage
  | StreamSourcesMessage
  | StreamEndMessage
  | StreamErrorMessage;

// ============================================
// SSE (POST /chat/stream) 이벤트 타입
//
// 백엔드 계약(app/api/schemas/streaming.py)과 1:1로 매핑한다.
// SSE 라인 포맷: `event: {type}\ndata: {json}\n\n`
// WebSocket 프로토콜과 별도 네임스페이스로 둔다.
// ============================================

/** 메타데이터 이벤트: 검색 결과 수/리랭킹 여부 등 (백엔드 StreamMetadataEvent) */
export interface StreamMetadataEvent {
  event: 'metadata';
  session_id: string;
  search_results: number;
  reranking_applied?: boolean;
  query_expansion?: string | null;
  timestamp?: string | null;
}

/** 청크 이벤트: LLM 응답 텍스트 조각 (백엔드 StreamChunkEvent) */
export interface StreamChunkEvent {
  event: 'chunk';
  data: string;
  chunk_index: number;
}

/** 완료 이벤트: 토큰 수/처리 시간/소스 등 (백엔드 StreamDoneEvent) */
export interface StreamDoneEvent {
  event: 'done';
  session_id: string;
  message_id: string;
  total_chunks: number;
  tokens_used?: number;
  processing_time?: number;
  sources?: Source[];
}

/** 에러 이벤트 (백엔드 StreamErrorEvent) */
export interface SseStreamErrorEvent {
  event: 'error';
  error_code: string;
  message: string;
  suggestion?: string | null;
}

/** SSE 이벤트 유니온 */
export type StreamChatEvent =
  | StreamMetadataEvent
  | StreamChunkEvent
  | StreamDoneEvent
  | SseStreamErrorEvent;

/**
 * POST /chat/stream 클라이언트 옵션
 */
export interface StreamChatClientOptions {
  /** 중단(abort) 시그널 */
  signal?: AbortSignal;
  /** 백엔드로 전달할 추가 옵션(temperature 등) */
  options?: Record<string, unknown>;
  /** 모든 이벤트 콜백 */
  onEvent?: (event: StreamChatEvent) => void;
  /** chunk 이벤트 콜백 */
  onChunk?: (event: StreamChunkEvent) => void;
  /** done 이벤트 콜백 */
  onDone?: (event: StreamDoneEvent) => void;
  /** error 이벤트 콜백 */
  onError?: (event: SseStreamErrorEvent) => void;
}

/** RAG 진행 단계 (검색 → 재순위 → 생성 → 완료) */
export type RagProgressPhase =
  | 'idle'
  | 'searching'
  | 'retrieval_done'
  | 'generating'
  | 'completed'
  | 'error';

/** RAG 진행 상태 */
export interface RagProgressState {
  phase: RagProgressPhase;
  label?: string;
  searchResults?: number;
  rerankingApplied?: boolean;
  updatedAt?: string;
}

// ============================================
// 상태 타입
// ============================================

/**
 * 스트리밍 연결/처리 상태
 */
export type StreamingState = 'idle' | 'connecting' | 'streaming' | 'error';

/**
 * 스트리밍 중인 메시지의 상태
 * 토큰이 누적되면서 업데이트됨
 */
export interface StreamingMessage {
  /** 메시지 고유 ID */
  id: string;
  /** 누적된 응답 텍스트 */
  content: string;
  /** RAG 소스 (스트리밍 완료 전에 수신 가능) */
  sources?: Source[];
  /** 현재 스트리밍 상태 */
  state: StreamingState;
  /** 에러 발생 시 에러 메시지 */
  error?: string;
}

// ============================================
// 이벤트 타입 (서비스 내부용)
// ============================================

/**
 * WebSocket 연결 상태 이벤트 데이터
 */
export interface ConnectionEventData {
  connected: boolean;
}

/**
 * 재연결 실패 이벤트 데이터
 */
export interface ReconnectFailedEventData {
  attempts: number;
  maxAttempts: number;
}

/**
 * 이벤트 리스너 콜백 타입
 */
export type EventCallback = (data: unknown) => void;
