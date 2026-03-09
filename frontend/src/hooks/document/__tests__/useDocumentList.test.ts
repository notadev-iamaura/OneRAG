/**
 * useDocumentList 훅 단위 테스트
 *
 * 문서 목록 조회, 정렬, 검색, 페이지네이션, 뷰 모드 전환을 검증합니다.
 * documentAPI를 모킹하여 네트워크 의존성을 제거합니다.
 */
import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useDocumentList } from '../useDocumentList';
import { documentAPI } from '../../../services/api';
import type { Document } from '../../../types';

// documentAPI 모킹
vi.mock('../../../services/api', () => ({
  documentAPI: {
    getDocuments: vi.fn(),
  },
}));

// logger 모킹
vi.mock('../../../utils/logger', () => ({
  logger: {
    log: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

/** 테스트용 문서 데이터 생성 헬퍼 */
const createMockDocument = (overrides: Partial<Document> = {}): Document => ({
  id: 'doc-1',
  filename: 'test.pdf',
  originalName: 'test.pdf',
  size: 1024,
  mimeType: 'application/pdf',
  uploadedAt: '2026-01-01T00:00:00Z',
  status: 'completed',
  chunks: 10,
  ...overrides,
});

describe('useDocumentList', () => {
  const mockShowToast = vi.fn();
  const mockGetDocuments = documentAPI.getDocuments as ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    // 기본 성공 응답 설정
    mockGetDocuments.mockResolvedValue({
      data: { documents: [], total: 0 },
    });
  });

  // ============================================================
  // 초기 상태 테스트
  // ============================================================

  it('초기 상태가 올바르게 설정되어야 한다', () => {
    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    expect(result.current.documents).toEqual([]);
    expect(result.current.loading).toBe(true); // 초기 fetch 시작
    expect(result.current.fetchError).toBe(false);
    expect(result.current.page).toBe(1);
    expect(result.current.totalPages).toBe(1);
    expect(result.current.sortField).toBe('uploadedAt');
    expect(result.current.sortDirection).toBe('desc');
    expect(result.current.searchQuery).toBe('');
    expect(result.current.viewMode).toBe('list');
  });

  // ============================================================
  // fetchDocuments 테스트
  // ============================================================

  it('마운트 시 fetchDocuments를 호출해야 한다', async () => {
    const docs = [createMockDocument()];
    mockGetDocuments.mockResolvedValue({
      data: { documents: docs, total: 1 },
    });

    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(mockGetDocuments).toHaveBeenCalledWith({
      page: 1,
      limit: 50,
      search: '',
    });
    expect(result.current.documents).toHaveLength(1);
    expect(result.current.fetchError).toBe(false);
  });

  it('fetch 실패 시 fetchError가 true가 되고 에러 토스트를 표시해야 한다', async () => {
    mockGetDocuments.mockRejectedValue(new Error('네트워크 오류'));

    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.fetchError).toBe(true);
    expect(mockShowToast).toHaveBeenCalledWith({
      type: 'error',
      message: '문서 목록 로드 실패',
    });
  });

  it('fetch 성공 시 totalPages가 올바르게 계산되어야 한다', async () => {
    mockGetDocuments.mockResolvedValue({
      data: { documents: [], total: 120 },
    });

    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    // 120 / 50 = 2.4 → Math.ceil → 3
    expect(result.current.totalPages).toBe(3);
  });

  // ============================================================
  // 정렬 테스트
  // ============================================================

  it('handleSort로 정렬 필드를 변경할 수 있어야 한다', async () => {
    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    act(() => {
      result.current.handleSort('filename');
    });

    expect(result.current.sortField).toBe('filename');
  });

  it('handleSortDirection으로 정렬 방향을 토글할 수 있어야 한다', async () => {
    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    // 초기값: desc → asc로 토글
    act(() => {
      result.current.handleSortDirection();
    });

    expect(result.current.sortDirection).toBe('asc');

    // asc → desc로 다시 토글
    act(() => {
      result.current.handleSortDirection();
    });

    expect(result.current.sortDirection).toBe('desc');
  });

  // ============================================================
  // 검색 테스트
  // ============================================================

  it('handleSearch로 검색어를 설정할 수 있어야 한다', async () => {
    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    act(() => {
      result.current.handleSearch('test query');
    });

    expect(result.current.searchQuery).toBe('test query');
  });

  // ============================================================
  // 뷰 모드 테스트
  // ============================================================

  it('setViewMode로 뷰 모드를 변경할 수 있어야 한다', async () => {
    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    act(() => {
      result.current.setViewMode('grid');
    });

    expect(result.current.viewMode).toBe('grid');
  });

  // ============================================================
  // 페이지 이동 테스트
  // ============================================================

  it('setPage로 페이지를 변경할 수 있어야 한다', async () => {
    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    act(() => {
      result.current.setPage(3);
    });

    expect(result.current.page).toBe(3);
  });

  // ============================================================
  // 핸들러 존재 여부 테스트
  // ============================================================

  it('모든 핸들러가 함수로 반환되어야 한다', () => {
    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    expect(typeof result.current.fetchDocuments).toBe('function');
    expect(typeof result.current.handleSort).toBe('function');
    expect(typeof result.current.handleSortDirection).toBe('function');
    expect(typeof result.current.handleSearch).toBe('function');
    expect(typeof result.current.setViewMode).toBe('function');
    expect(typeof result.current.setPage).toBe('function');
  });
});
