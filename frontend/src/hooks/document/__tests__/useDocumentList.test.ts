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
    mockGetDocuments.mockReturnValue(new Promise(() => {}));

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

  it('마운트 시 over-fetch 파라미터로 fetchDocuments를 호출해야 한다', async () => {
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

    // 전역 정렬/검색을 위해 page=1, 큰 page_size로 over-fetch한다.
    expect(mockGetDocuments).toHaveBeenCalledWith({
      page: 1,
      page_size: 10000,
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

  it('fetch 성공 시 totalPages가 필터링된 문서 수 기준으로 계산되어야 한다', async () => {
    // over-fetch로 받은 120건을 클라이언트에서 페이지네이션 → 120/50 = 2.4 → 3페이지
    const docs = Array.from({ length: 120 }, (_, i) =>
      createMockDocument({ id: `doc-${i}`, originalName: `doc-${i}.pdf` }),
    );
    mockGetDocuments.mockResolvedValue({
      data: { documents: docs, total: 120 },
    });

    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.totalPages).toBe(3);
    // 첫 페이지에는 PAGE_SIZE(50)건만 노출
    expect(result.current.documents).toHaveLength(50);
  });

  it('문서가 0건이어도 totalPages는 최소 1로 가드되어야 한다 (유령 0페이지 방지)', async () => {
    mockGetDocuments.mockResolvedValue({
      data: { documents: [], total: 0 },
    });

    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.totalPages).toBe(1);
    expect(result.current.documents).toHaveLength(0);
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

    mockGetDocuments.mockReturnValue(new Promise(() => {}));

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

    mockGetDocuments.mockReturnValue(new Promise(() => {}));

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

    mockGetDocuments.mockReturnValue(new Promise(() => {}));

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

    mockGetDocuments.mockReturnValue(new Promise(() => {}));

    act(() => {
      result.current.setPage(3);
    });

    expect(result.current.page).toBe(3);
  });

  // ============================================================
  // 핸들러 존재 여부 테스트
  // ============================================================

  it('모든 핸들러가 함수로 반환되어야 한다', () => {
    mockGetDocuments.mockReturnValue(new Promise(() => {}));

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

  // ============================================================
  // #48: 클라이언트 측 검색 필터 / 전역 정렬 회귀 테스트
  // ============================================================

  it('검색어로 클라이언트 측 필터링이 동작해야 한다 (백엔드 검색 미지원 보정)', async () => {
    const docs = [
      createMockDocument({ id: 'a', originalName: '보험약관.pdf' }),
      createMockDocument({ id: 'b', originalName: 'invoice-2026.xlsx' }),
      createMockDocument({ id: 'c', originalName: '보험청구서.docx' }),
    ];
    // 백엔드는 search를 무시하고 전체를 반환한다고 가정한다.
    mockGetDocuments.mockResolvedValue({ data: { documents: docs, total: 3 } });

    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.documents).toHaveLength(3);

    act(() => {
      result.current.handleSearch('보험');
    });

    await waitFor(() => {
      expect(result.current.documents).toHaveLength(2);
    });
    const names = result.current.documents.map((d) => d.originalName);
    expect(names).toContain('보험약관.pdf');
    expect(names).toContain('보험청구서.docx');
    expect(names).not.toContain('invoice-2026.xlsx');
  });

  it('정렬이 페이지 경계와 무관하게 전역으로 적용되어야 한다', async () => {
    // 파일명 정렬 시 페이지 단위가 아니라 전체 집합 기준으로 정렬되어야 한다.
    const docs = [
      createMockDocument({ id: '1', originalName: 'banana.pdf' }),
      createMockDocument({ id: '2', originalName: 'apple.pdf' }),
      createMockDocument({ id: '3', originalName: 'cherry.pdf' }),
    ];
    mockGetDocuments.mockResolvedValue({ data: { documents: docs, total: 3 } });

    const { result } = renderHook(() =>
      useDocumentList({ showToast: mockShowToast }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    act(() => {
      result.current.handleSort('filename');
      result.current.handleSortDirection(); // desc → asc
    });

    await waitFor(() => {
      expect(result.current.documents.map((d) => d.originalName)).toEqual([
        'apple.pdf',
        'banana.pdf',
        'cherry.pdf',
      ]);
    });
  });
});
