/**
 * 문서 유틸리티 함수 모음
 *
 * DocumentsTab에서 사용하는 순수 함수들을 분리하여
 * 테스트 용이성과 재사용성을 높입니다.
 *
 * - sortDocuments: 문서 배열을 지정된 필드/방향으로 정렬
 * - formatFileSize: 바이트 단위 파일 크기를 사람이 읽기 좋은 형태로 변환
 */
import type { Document } from '../types';

/** 정렬 가능한 필드 타입 */
export type SortField = 'filename' | 'size' | 'uploadedAt' | 'type';

/** 정렬 방향 타입 */
export type SortDirection = 'asc' | 'desc';

/**
 * 문서 배열을 지정된 필드와 방향에 따라 정렬합니다.
 * 원본 배열을 변이시키지 않고 새 배열을 반환합니다 (불변성 보장).
 *
 * @param docs - 정렬할 문서 배열
 * @param sortField - 정렬 기준 필드 (filename, size, uploadedAt, type)
 * @param sortDirection - 정렬 방향 (asc: 오름차순, desc: 내림차순)
 * @returns 정렬된 새 문서 배열
 */
export const sortDocuments = (
  docs: Document[],
  sortField: SortField,
  sortDirection: SortDirection,
): Document[] => {
  return [...docs].sort((a, b) => {
    let aValue: string | number;
    let bValue: string | number;

    switch (sortField) {
      case 'filename':
        // originalName 우선, 없으면 filename으로 폴백
        aValue = (a.originalName || a.filename).toLowerCase();
        bValue = (b.originalName || b.filename).toLowerCase();
        break;
      case 'size':
        aValue = a.size;
        bValue = b.size;
        break;
      case 'uploadedAt':
        aValue = new Date(a.uploadedAt).getTime();
        bValue = new Date(b.uploadedAt).getTime();
        break;
      case 'type':
        // 파일 확장자 기준 정렬
        aValue = (a.originalName || a.filename).split('.').pop()?.toLowerCase() || '';
        bValue = (b.originalName || b.filename).split('.').pop()?.toLowerCase() || '';
        break;
      default:
        return 0;
    }

    if (aValue < bValue) return sortDirection === 'asc' ? -1 : 1;
    if (aValue > bValue) return sortDirection === 'asc' ? 1 : -1;
    return 0;
  });
};

/**
 * 바이트 단위 파일 크기를 사람이 읽기 좋은 형태로 변환합니다.
 *
 * @param bytes - 파일 크기 (바이트)
 * @returns 포맷된 파일 크기 문자열 (예: "1.5 KB", "2.3 MB")
 */
export const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};
