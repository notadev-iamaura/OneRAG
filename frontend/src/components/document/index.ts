/**
 * Document 컴포넌트 모듈 내보내기
 *
 * DocumentsTab의 하위 컴포넌트를 중앙에서 관리합니다.
 *
 * @example
 * import {
 *   DocumentToolbar,        // 검색/정렬/뷰 모드/삭제 버튼
 *   DocumentListView,       // 테이블 형태 문서 목록
 *   DocumentGridView,       // 그리드 형태 문서 카드
 *   DocumentDetailDialog,   // 문서 상세 정보 다이얼로그
 *   DocumentDeleteDialog,   // 단일 삭제 확인
 *   DocumentBulkDeleteDialog, // 일괄 삭제 확인
 *   DocumentDeleteAllDialog,  // 전체 삭제 2단계 확인
 * } from '@/components/document';
 */

// 툴바
export { DocumentToolbar } from './DocumentToolbar';
export type { DocumentToolbarProps } from './DocumentToolbar';

// 뷰 컴포넌트
export { DocumentListView } from './DocumentListView';
export type { DocumentListViewProps } from './DocumentListView';

export { DocumentGridView } from './DocumentGridView';
export type { DocumentGridViewProps } from './DocumentGridView';

// 다이얼로그 컴포넌트
export { DocumentDetailDialog } from './DocumentDetailDialog';
export type { DocumentDetailDialogProps } from './DocumentDetailDialog';

export { DocumentDeleteDialog } from './DocumentDeleteDialog';
export type { DocumentDeleteDialogProps } from './DocumentDeleteDialog';

export { DocumentBulkDeleteDialog } from './DocumentBulkDeleteDialog';
export type { DocumentBulkDeleteDialogProps } from './DocumentBulkDeleteDialog';

export { DocumentDeleteAllDialog } from './DocumentDeleteAllDialog';
export type { DocumentDeleteAllDialogProps } from './DocumentDeleteAllDialog';
