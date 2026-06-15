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
 * 전역 정렬/검색을 위한 over-fetch 페이지 크기.
 *
 * OneRAG 백엔드 list_documents는 search/sort_field/sort_direction 파라미터를
 * 지원하지 않으므로(2026-06 기준), 한 번에 충분히 많은 문서를 받아와
 * 클라이언트에서 검색 필터 → 전역 정렬 → 페이지 슬라이스를 수행한다.
 * (백엔드가 server-side 검색/정렬을 지원하게 되면 이 over-fetch를 제거하고
 *  sort_field/sort_direction/search를 그대로 전달하도록 전환하면 된다.)
 */
const GLOBAL_FETCH_PAGE_SIZE = 10000;

/**
 * 문서가 검색어와 일치하는지 판별한다(파일명/원본명/타입/상태 결합, 대소문자 무시).
 * 검색어가 비어 있으면 모든 문서를 통과시킨다.
 */
const matchesSearch = (doc: Document, normalizedQuery: string): boolean => {
  if (!normalizedQuery) return true;
  const haystack = [
    doc.originalName,
    doc.filename,
    doc.mimeType,
    doc.status,
    doc.id,
  ]
    .filter((value): value is string => typeof value === 'string')
    .join(' ')
    .toLowerCase();
  return haystack.includes(normalizedQuery);
};

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

  /**
   * 문서 목록을 서버에서 조회합니다.
   *
   * 백엔드가 검색/정렬을 지원하지 않으므로 한 번에 많은 문서를 받아온 뒤
   * 클라이언트에서 검색 필터 → 전역 정렬 → 현재 페이지 슬라이스를 수행한다.
   * 이렇게 하면 (1) 검색이 실제로 동작하고, (2) 정렬이 페이지 단위가 아닌
   * 전역 정렬이 되며, (3) totalPages가 필터링 결과 기준으로 정확해진다.
   */
  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    setFetchError(false);
    try {
      const response = await documentAPI.getDocuments({
        page: 1,
        page_size: GLOBAL_FETCH_PAGE_SIZE,
        // server-side 검색이 지원되면 활용되도록 search도 함께 전달한다(미지원 시 무시됨).
        search: searchQuery,
      });

      const allDocuments = response.data.documents;
      const normalizedQuery = searchQuery.trim().toLowerCase();

      // 1) 검색 필터 (백엔드가 검색을 무시해도 클라이언트에서 보정)
      const filtered = allDocuments.filter((doc) => matchesSearch(doc, normalizedQuery));

      // 2) 전역 정렬 (페이지 경계와 무관하게 전체 집합 정렬)
      const sorted = sortDocumentsUtil(filtered, sortField, sortDirection);

      // 3) 현재 페이지 슬라이스
      const startIndex = (page - 1) * PAGE_SIZE;
      const pageItems = sorted.slice(startIndex, startIndex + PAGE_SIZE);

      setDocuments(pageItems);
      // 0건일 때 totalPages=0 유령 상태를 방지하기 위해 최소 1로 가드한다.
      setTotalPages(Math.max(1, Math.ceil(sorted.length / PAGE_SIZE)));
    } catch {
      setFetchError(true);
      showToast({ type: 'error', message: '문서 목록 로드 실패' });
    } finally {
      setLoading(false);
    }
  }, [page, searchQuery, sortField, sortDirection, showToast]);

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
