/**
 * Document 훅 모듈 내보내기
 *
 * 문서 관리 기능 관련 모든 훅을 중앙에서 관리합니다.
 *
 * @example
 * import {
 *   useDocumentList,       // 문서 목록 조회/정렬/검색/페이지네이션
 *   useDocumentSelection,  // 문서 선택/상세 보기
 *   useDocumentDelete,     // 문서 삭제 (단일/일괄/전체)
 * } from '@/hooks/document';
 */

// 문서 목록 관리
export { useDocumentList } from './useDocumentList';
export type { UseDocumentListReturn } from './useDocumentList';

// 문서 선택 관리
export { useDocumentSelection } from './useDocumentSelection';
export type { UseDocumentSelectionReturn } from './useDocumentSelection';

// 문서 삭제 관리
export { useDocumentDelete } from './useDocumentDelete';
export type { UseDocumentDeleteReturn } from './useDocumentDelete';
