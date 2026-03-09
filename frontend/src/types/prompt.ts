/**
 * 프롬프트 타입 및 상수 정의
 *
 * promptService.ts에서 분리된 타입/상수 모듈입니다.
 * 프롬프트 관련 인터페이스와 카테고리/스타일 상수를 정의합니다.
 *
 * 주요 타입:
 * - Prompt: 프롬프트 엔티티
 * - CreatePromptRequest: 프롬프트 생성 요청
 * - UpdatePromptRequest: 프롬프트 수정 요청
 * - PromptListResponse: 프롬프트 목록 응답 (페이지네이션 포함)
 * - PromptExport: 프롬프트 내보내기 데이터
 * - PromptImportRequest: 프롬프트 가져오기 요청
 */

// 프롬프트 엔티티 타입
export interface Prompt {
  id: string;
  name: string;
  content: string;
  description: string;
  category: 'system' | 'style' | 'custom';
  is_active: boolean;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// 프롬프트 목록 응답 (페이지네이션 포함)
export interface PromptListResponse {
  prompts: Prompt[];
  total: number;
  page: number;
  page_size: number;
}

// 프롬프트 생성 요청
export interface CreatePromptRequest {
  name: string;
  content: string;
  description: string;
  category: 'system' | 'style' | 'custom';
  is_active?: boolean;
  metadata?: Record<string, unknown>;
}

// 프롬프트 수정 요청 (모든 필드 선택적)
export interface UpdatePromptRequest {
  name?: string;
  content?: string;
  description?: string;
  category?: 'system' | 'style' | 'custom';
  is_active?: boolean;
  metadata?: Record<string, unknown>;
}

// 프롬프트 내보내기 데이터
export interface PromptExport {
  prompts: Prompt[];
  exported_at: string;
  total: number;
}

// 프롬프트 가져오기 요청
export interface PromptImportRequest {
  prompts: Prompt[];
  exported_at: string;
  total: number;
}

// 프롬프트 스타일 옵션 (답변 형식 선택)
export const PROMPT_STYLES = [
  { value: 'system', label: '기본', description: '표준 시스템 프롬프트' },
  { value: 'detailed', label: '자세한 답변', description: '상세하고 포괄적인 응답' },
  { value: 'concise', label: '간결한 답변', description: '핵심만 간단하게' },
  { value: 'professional', label: '전문적 답변', description: '비즈니스 및 전문 분야용' },
  { value: 'educational', label: '교육적 답변', description: '학습 및 설명 중심' },
] as const;

// 프롬프트 카테고리 옵션
export const PROMPT_CATEGORIES = [
  { value: 'system', label: '시스템', description: '기본 시스템 프롬프트' },
  { value: 'style', label: '스타일', description: '답변 스타일 프롬프트' },
  { value: 'custom', label: '커스텀', description: '사용자 정의 프롬프트' },
] as const;
