/**
 * 문서 목록 관리 훅
 *
 * 문서 조회, 정렬, 검색, 페이지네이션, 뷰 모드를 관리합니다.
 * documentAPI를 통해 백엔드와 통신하며, showToast 콜백으로 사용자에게 알림을 전달합니다.
 *
 * @example
 * const list = useDocumentList({ showToast });
 * // list.documents, list.fetchDocuments(), list.handleSort('filename') 등
 */
import { useState, useCallback, useEffect } from 'react';
import type { Document, ToastMessage } from '../../types';
import type { SortField, SortDirection } from '../../utils/documentUtils';
import { sortDocuments as sortDocumentsUtil } from '../../utils/documentUtils';
import { documentAPI } from '../../services/api';

/** useDocumentList 훅의 옵션 */
interface UseDocumentListOptions {
  /** 토스트 메시지 표시 콜백 */
  showToast: (message: Omit<ToastMessage, 'id'>) => void;
}

/** useDocumentList 훅의 반환 타입 */
export interface UseDocumentListReturn {
  /** 문서 목록 */
  documents: Document[];
  /** 로딩 상태 */
  loading: boolean;
  /** 조회 오류 여부 */
  fetchError: boolean;
  /** 현재 페이지 */
  page: number;
  /** 전체 페이지 수 */
  totalPages: number;
  /** 정렬 필드 */
  sortField: SortField;
  /** 정렬 방향 */
  sortDirection: SortDirection;
  /** 검색어 */
  searchQuery: string;
  /** 보기 모드 (list 또는 grid) */
  viewMode: 'list' | 'grid';
  /** 문서 목록 새로고침 */
  fetchDocuments: () => Promise<void>;
  /** 정렬 필드 변경 핸들러 */
  handleSort: (field: SortField) => void;
  /** 정렬 방향 토글 핸들러 */
  handleSortDirection: () => void;
  /** 검색어 변경 핸들러 */
  handleSearch: (query: string) => void;
  /** 보기 모드 변경 핸들러 */
  setViewMode: (mode: 'list' | 'grid') => void;
  /** 페이지 변경 핸들러 */
  setPage: (page: number) => void;
}

/** 페이지당 문서 수 */
const PAGE_SIZE = 50;

/**
 * 문서 목록 관리 훅
 *
 * 마운트 시 자동으로 문서를 조회하며,
 * page, searchQuery, sortField, sortDirection 변경 시 자동 재조회합니다.
 */
export const useDocumentList = ({
  showToast,
}: UseDocumentListOptions): UseDocumentListReturn => {
  // 문서 목록 상태
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);

  // 페이지네이션 상태
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  // 정렬 상태
  const [sortField, setSortField] = useState<SortField>('uploadedAt');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  // 검색 및 뷰 모드 상태
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('list');

  // 정렬 유틸리티 래퍼 (현재 정렬 상태를 바인딩)
  const sortDocuments = useCallback(
    (docs: Document[]) => sortDocumentsUtil(docs, sortField, sortDirection),
    [sortField, sortDirection],
  );

  /** 문서 목록을 서버에서 조회합니다 */
  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    setFetchError(false);
    try {
      const response = await documentAPI.getDocuments({
        page,
        limit: PAGE_SIZE,
        search: searchQuery,
      });
      const sortedDocuments = sortDocuments(response.data.documents);
      setDocuments(sortedDocuments);
      setTotalPages(Math.ceil(response.data.total / PAGE_SIZE));
    } catch {
      setFetchError(true);
      showToast({ type: 'error', message: '문서 목록 로드 실패' });
    } finally {
      setLoading(false);
    }
  }, [page, searchQuery, showToast, sortDocuments]);

  // 마운트 및 의존성 변경 시 자동 조회
  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  /** 정렬 필드를 변경합니다 */
  const handleSort = useCallback((field: SortField) => {
    setSortField(field);
  }, []);

  /** 정렬 방향을 토글합니다 (asc ↔ desc) */
  const handleSortDirection = useCallback(() => {
    setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
  }, []);

  /** 검색어를 변경합니다 */
  const handleSearch = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  return {
    // 상태
    documents,
    loading,
    fetchError,
    page,
    totalPages,
    sortField,
    sortDirection,
    searchQuery,
    viewMode,
    // 핸들러
    fetchDocuments,
    handleSort,
    handleSortDirection,
    handleSearch,
    setViewMode,
    setPage,
  };
};
