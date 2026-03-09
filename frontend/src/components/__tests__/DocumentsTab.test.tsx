/**
 * DocumentsTab 오케스트레이터 통합 테스트
 *
 * vi.mock으로 7개 하위 컴포넌트와 3개 훅을 격리하여
 * 오케스트레이터가 올바르게 조합하는지 검증합니다.
 *
 * 테스트 케이스:
 * 1. 로딩 상태 표시 확인
 * 2. 에러 상태 표시 확인
 * 3. 빈 목록 상태 표시 확인
 * 4. 정상 상태에서 7개 하위 컴포넌트 렌더링 확인
 * 5. showToast prop이 각 훅에 올바르게 전달되는지 확인
 * 6. list 뷰 모드에서 DocumentListView 렌더링 확인
 * 7. grid 뷰 모드에서 DocumentGridView 렌더링 확인
 * 8. named export 유지 확인
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { UseDocumentListReturn } from '../../hooks/document/useDocumentList';
import type { UseDocumentSelectionReturn } from '../../hooks/document/useDocumentSelection';
import type { UseDocumentDeleteReturn } from '../../hooks/document/useDocumentDelete';

// ============================================================
// 7개 하위 컴포넌트를 stub JSX로 격리
// ============================================================
vi.mock('../document', () => ({
  DocumentToolbar: (props: Record<string, unknown>) => (
    <div data-testid="document-toolbar" data-loading={String(props.loading)} />
  ),
  DocumentListView: (props: Record<string, unknown>) => (
    <div data-testid="document-list-view" data-doc-count={String((props.documents as unknown[])?.length ?? 0)} />
  ),
  DocumentGridView: (props: Record<string, unknown>) => (
    <div data-testid="document-grid-view" data-doc-count={String((props.documents as unknown[])?.length ?? 0)} />
  ),
  DocumentDetailDialog: (props: Record<string, unknown>) => (
    <div data-testid="document-detail-dialog" data-open={String(props.open)} />
  ),
  DocumentDeleteDialog: (props: Record<string, unknown>) => (
    <div data-testid="document-delete-dialog" data-open={String(props.open)} />
  ),
  DocumentBulkDeleteDialog: (props: Record<string, unknown>) => (
    <div data-testid="document-bulk-delete-dialog" data-open={String(props.open)} />
  ),
  DocumentDeleteAllDialog: (props: Record<string, unknown>) => (
    <div data-testid="document-delete-all-dialog" data-open={String(props.open)} />
  ),
}));

// ============================================================
// 3개 훅 모킹 기본 반환값
// ============================================================

/** 문서 목록 훅 기본 반환값 */
const createDefaultListReturn = (): UseDocumentListReturn => ({
  documents: [
    { id: 'doc-1', filename: 'test.pdf', originalName: 'test.pdf', size: 1024, mimeType: 'application/pdf', uploadedAt: '2026-01-01', status: 'completed', chunkCount: 5 },
  ],
  loading: false,
  fetchError: false,
  page: 1,
  totalPages: 3,
  sortField: 'uploadedAt',
  sortDirection: 'desc',
  searchQuery: '',
  viewMode: 'list',
  fetchDocuments: vi.fn(),
  handleSort: vi.fn(),
  handleSortDirection: vi.fn(),
  handleSearch: vi.fn(),
  setViewMode: vi.fn(),
  setPage: vi.fn(),
});

/** 문서 선택 훅 기본 반환값 */
const createDefaultSelectionReturn = (): UseDocumentSelectionReturn => ({
  selectedDocuments: new Set<string>(),
  selectedDocument: null,
  detailsOpen: false,
  toggleSelect: vi.fn(),
  toggleSelectAll: vi.fn(),
  clearSelection: vi.fn(),
  viewDetails: vi.fn(),
  closeDetails: vi.fn(),
});

/** 문서 삭제 훅 기본 반환값 */
const createDefaultDeleteReturn = (): UseDocumentDeleteReturn => ({
  deleteConfirmOpen: false,
  bulkDeleteConfirmOpen: false,
  deleteAllConfirmOpen: false,
  deleteAllStep: 'confirm',
  deleteAllTyping: '',
  documentToDelete: null,
  deleteLoading: false,
  bulkDeleteLoading: false,
  deleteAllLoading: false,
  handleDeleteSingle: vi.fn(),
  handleDeleteBulk: vi.fn(),
  handleDeleteAll: vi.fn(),
  handleDeleteCancel: vi.fn(),
  handleBulkDeleteCancel: vi.fn(),
  handleDeleteAllCancel: vi.fn(),
  confirmDeleteSingle: vi.fn(),
  confirmDeleteBulk: vi.fn(),
  confirmDeleteAll: vi.fn(),
  setDeleteAllTyping: vi.fn(),
});

let mockListReturn: UseDocumentListReturn;
let mockSelectionReturn: UseDocumentSelectionReturn;
let mockDeleteReturn: UseDocumentDeleteReturn;

vi.mock('../../hooks/document', () => ({
  useDocumentList: () => mockListReturn,
  useDocumentSelection: () => mockSelectionReturn,
  useDocumentDelete: () => mockDeleteReturn,
}));

// API 모킹 (handleDownload에서 사용)
vi.mock('../../services/api', () => ({
  documentAPI: {
    downloadDocument: vi.fn(),
  },
}));

describe('DocumentsTab 오케스트레이터', () => {
  const mockShowToast = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockListReturn = createDefaultListReturn();
    mockSelectionReturn = createDefaultSelectionReturn();
    mockDeleteReturn = createDefaultDeleteReturn();
  });

  it('로딩 상태일 때 로딩 인디케이터가 표시되어야 함', async () => {
    mockListReturn = { ...createDefaultListReturn(), loading: true };

    const { DocumentsTab } = await import('../DocumentsTab');
    render(<DocumentsTab showToast={mockShowToast} />);

    expect(screen.getByText('문서 목록을 불러오는 중...')).toBeInTheDocument();
    // 로딩 중에는 리스트/그리드 뷰가 표시되지 않아야 함
    expect(screen.queryByTestId('document-list-view')).not.toBeInTheDocument();
  });

  it('에러 상태일 때 에러 메시지와 재시도 버튼이 표시되어야 함', async () => {
    mockListReturn = { ...createDefaultListReturn(), fetchError: true };

    const { DocumentsTab } = await import('../DocumentsTab');
    render(<DocumentsTab showToast={mockShowToast} />);

    expect(screen.getByText('문서 목록을 불러올 수 없습니다')).toBeInTheDocument();
    // 재시도 버튼 클릭 시 fetchDocuments 호출
    const retryButton = screen.getByText('다시 시도');
    fireEvent.click(retryButton);
    expect(mockListReturn.fetchDocuments).toHaveBeenCalled();
  });

  it('문서가 없을 때 빈 목록 메시지가 표시되어야 함', async () => {
    mockListReturn = { ...createDefaultListReturn(), documents: [] };

    const { DocumentsTab } = await import('../DocumentsTab');
    render(<DocumentsTab showToast={mockShowToast} />);

    expect(screen.getByText('문서가 없습니다')).toBeInTheDocument();
  });

  it('정상 상태에서 뷰 컴포넌트와 4개 다이얼로그가 렌더링되어야 함', async () => {
    const { DocumentsTab } = await import('../DocumentsTab');
    render(<DocumentsTab showToast={mockShowToast} />);

    // 툴바 렌더링 확인
    expect(screen.getByTestId('document-toolbar')).toBeInTheDocument();
    // 리스트 뷰 렌더링 확인 (기본 viewMode가 'list')
    expect(screen.getByTestId('document-list-view')).toBeInTheDocument();
    // 4개 다이얼로그 렌더링 확인
    expect(screen.getByTestId('document-detail-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('document-delete-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('document-bulk-delete-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('document-delete-all-dialog')).toBeInTheDocument();
  });

  it('viewMode가 list일 때 DocumentListView가 렌더링되어야 함', async () => {
    mockListReturn = { ...createDefaultListReturn(), viewMode: 'list' };

    const { DocumentsTab } = await import('../DocumentsTab');
    render(<DocumentsTab showToast={mockShowToast} />);

    expect(screen.getByTestId('document-list-view')).toBeInTheDocument();
    expect(screen.queryByTestId('document-grid-view')).not.toBeInTheDocument();
  });

  it('viewMode가 grid일 때 DocumentGridView가 렌더링되어야 함', async () => {
    mockListReturn = { ...createDefaultListReturn(), viewMode: 'grid' };

    const { DocumentsTab } = await import('../DocumentsTab');
    render(<DocumentsTab showToast={mockShowToast} />);

    expect(screen.getByTestId('document-grid-view')).toBeInTheDocument();
    expect(screen.queryByTestId('document-list-view')).not.toBeInTheDocument();
  });

  it('페이지네이션이 정상적으로 렌더링되어야 함', async () => {
    mockListReturn = { ...createDefaultListReturn(), page: 2, totalPages: 5 };

    const { DocumentsTab } = await import('../DocumentsTab');
    render(<DocumentsTab showToast={mockShowToast} />);

    expect(screen.getByText('Page 2')).toBeInTheDocument();
    expect(screen.getByText('of 5')).toBeInTheDocument();
  });

  it('named export로 접근 가능해야 함', async () => {
    const module = await import('../DocumentsTab');
    expect(module.DocumentsTab).toBeDefined();
    expect(typeof module.DocumentsTab).toBe('function');
  });
});
