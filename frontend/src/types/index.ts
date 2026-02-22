// API Response Types
export interface HealthStatus {
  status: string;
  timestamp: string;
  uptime: number;
  version: string;
  environment: string;
}

// API 응답에서 받는 실제 문서 타입 (백엔드 응답 구조에 맞게 수정)
export interface ApiDocument {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  upload_date: string;
  status: string;
  chunk_count: number;
  processing_time?: number | null;
  error_message?: string | null;
}

// 프론트엔드에서 사용하는 문서 타입
export interface Document {
  id: string;
  filename: string;
  originalName: string;
  size: number;
  mimeType: string;
  uploadedAt: string;
  status: 'processing' | 'completed' | 'failed';
  chunks?: number;
  metadata?: {
    pageCount?: number;
    wordCount?: number;
  };
}

export interface UploadResponse {
  success: boolean;
  jobId: string;
  message: string;
}

export interface UploadStatus {
  job_id: string;
  status: 'processing' | 'completed' | 'failed' | 'completed_with_errors';
  progress: number;
  message: string;
  filename?: string;
  chunk_count?: number;
  processing_time?: number;
  error_message?: string | null;
  timestamp?: string;
  documentId?: string; // 백워드 호환성을 위해 유지
  error?: string; // 백워드 호환성을 위해 유지
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  sources?: Source[];
}

export interface SourceAdditionalMetadata {
  folder?: string;
  full_path?: string;
  uploaded_at?: string;
  batch_processed?: boolean;
  bm42_idf?: boolean;
  doc_type?: string;
  table_count?: number;
  has_images?: boolean;
  data_root?: string;
  priority_level?: string;
  priority_numeric?: number;
  document_series?: string;
  doc_category?: string;
  law_id?: string;
  law_serial_number?: string;
  law_name?: string;
  law_slug?: string;
  agency?: string;
  legal_department?: string;
  agency_phone?: string;
  enacted_date?: string;
  effective_date?: string;
  promulgation_number?: string;
  revision_type?: string;
  revision_reason?: string;
  article_count?: number;
  has_appendix?: boolean;
  appendix_promulgation_date?: string;
  display_title?: string;
  normalized_filename?: string;
  file_url_status?: string;
  multi_query_count?: number;
  score_details?: {
    avg_score?: number;
    max_score?: number;
    diversity_bonus?: number;
  };
}

export interface Source {
  id: number;
  document: string;
  page?: number | null;
  chunk?: number | null;
  relevance: number;
  content_preview: string;
  file_type?: string | null;
  file_path?: string | null;
  file_size?: number | null;
  total_chunks?: number | null;
  file_hash?: string | null;
  load_timestamp?: string | null;
  sheet_name?: string | null;
  format?: string | null;
  json_type?: string | null;
  item_index?: number | null;
  rerank_method?: string | null;
  original_score?: number | null;
  additional_metadata?: SourceAdditionalMetadata | null;
}

export interface ChatResponse {
  answer: string;
  sources: Source[];
  session_id: string;
  processing_time: number;
  tokens_used: number;
  timestamp: string;
  model_info?: {
    provider: string;
    model: string;
    generation_time: number;
    model_config?: Record<string, unknown>;
  };
}

export interface ChatHistoryEntry {
  id?: string | number;
  role?: 'user' | 'assistant';
  message?: string;
  question?: string;
  prompt?: string;
  response?: string;
  answer?: string;
  content?: string;
  user_message?: string;
  assistant_message?: string;
  session_id?: string;
  timestamp?: string;
  created_at?: string;
  updated_at?: string;
  sources?: Source[];
}

// 세션 정보 API 응답 타입
export interface SessionInfo {
  session_id: string;
  messageCount: number;
  tokensUsed: number;
  processingTime: number;
  modelInfo: {
    provider: string;
    model: string;
    generation_time: number;
    model_config?: Record<string, unknown>;
  };
  timestamp: string;
}


// UI State Types
export interface ToastMessage {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  message: string;
  duration?: number;
}

export interface PaginationState {
  page: number;
  pageSize: number;
  total: number;
}

// Form Types
export interface UploadFormData {
  file: File | null;
  description?: string;
}

export interface SearchFilters {
  query: string;
  status?: Document['status'];
  dateFrom?: string;
  dateTo?: string;
}

// ChatEmptyState Settings Types
export interface ChatEmptyStateSettings {
  mainMessage: string;
  subMessage: string;
  suggestions: string[];
}

export interface ChatEmptyStateSettingsUpdateRequest {
  mainMessage?: string;
  subMessage?: string;
  suggestions?: string[];
}

// WebSocket DI 패턴 타입
export type {
  IWebSocket,
  WebSocketFactory,
  WebSocketConfig,
  WebSocketReadyStateType,
} from './websocket';
export {
  WebSocketReadyState,
  defaultWebSocketFactory,
  defaultWebSocketConfig,
} from './websocket';

// Chat API DI 패턴 타입
export type {
  IChatAPIService,
  ChatAPIFactory,
  ChatAPIConfig,
  ChatAPIResponse,
  ChatAPISessionInfo,
  ChatAPIHistoryEntry,
  ChatAPISearchSource,
} from './chatAPI';
export { defaultChatAPIConfig } from './chatAPI';
