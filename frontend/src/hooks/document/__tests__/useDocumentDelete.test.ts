/**
 * useDocumentDelete 훅 단위 테스트
 *
 * 단일 삭제, 일괄 삭제, 전체 삭제(2단계 확인) 플로우와 각 취소 핸들러를 검증합니다.
 * documentAPI를 모킹하여 네트워크 의존성을 제거합니다.
 */
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useDocumentDelete } from '../useDocumentDelete';
import { documentAPI } from '../../../services/api';

// documentAPI 모킹
vi.mock('../../../services/api', () => ({
  documentAPI: {
    deleteDocument: vi.fn(),
    deleteDocuments: vi.fn(),
    deleteAllDocuments: vi.fn(),
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

describe('useDocumentDelete', () => {
  const mockShowToast = vi.fn();
  const mockOnDeleted = vi.fn();
  const mockClearSelection = vi.fn();

  const defaultProps = {
    showToast: mockShowToast,
    onDeleted: mockOnDeleted,
    clearSelection: mockClearSelection,
  };

  const mockDeleteDocument = documentAPI.deleteDocument as ReturnType<typeof vi.fn>;
  const mockDeleteDocuments = documentAPI.deleteDocuments as ReturnType<typeof vi.fn>;
  const mockDeleteAllDocuments = documentAPI.deleteAllDocuments as ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockDeleteDocument.mockResolvedValue({});
    mockDeleteDocuments.mockResolvedValue({});
    mockDeleteAllDocuments.mockResolvedValue({});
  });

  // ============================================================
  // 초기 상태 테스트
  // ============================================================

  it('초기 상태가 올바르게 설정되어야 한다', () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    expect(result.current.deleteConfirmOpen).toBe(false);
    expect(result.current.bulkDeleteConfirmOpen).toBe(false);
    expect(result.current.deleteAllConfirmOpen).toBe(false);
    expect(result.current.deleteAllStep).toBe('confirm');
    expect(result.current.deleteAllTyping).toBe('');
    expect(result.current.documentToDelete).toBeNull();
    expect(result.current.deleteLoading).toBe(false);
    expect(result.current.bulkDeleteLoading).toBe(false);
    expect(result.current.deleteAllLoading).toBe(false);
  });

  // ============================================================
  // 단일 삭제 플로우 테스트
  // ============================================================

  it('handleDeleteSingle로 삭제 확인 다이얼로그를 열어야 한다', () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    act(() => {
      result.current.handleDeleteSingle('doc-1');
    });

    expect(result.current.documentToDelete).toBe('doc-1');
    expect(result.current.deleteConfirmOpen).toBe(true);
  });

  it('confirmDeleteSingle로 문서를 삭제하고 성공 토스트를 표시해야 한다', async () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    // 삭제 대상 설정
    act(() => {
      result.current.handleDeleteSingle('doc-1');
    });

    // 삭제 확인
    await act(async () => {
      await result.current.confirmDeleteSingle();
    });

    expect(mockDeleteDocument).toHaveBeenCalledWith('doc-1');
    expect(mockShowToast).toHaveBeenCalledWith({
      type: 'success',
      message: '문서 삭제 완료',
    });
    expect(mockOnDeleted).toHaveBeenCalled();
    expect(result.current.deleteConfirmOpen).toBe(false);
    expect(result.current.documentToDelete).toBeNull();
  });

  it('confirmDeleteSingle 실패 시 에러 토스트를 표시해야 한다', async () => {
    mockDeleteDocument.mockRejectedValue({
      response: { data: { message: '삭제 권한 없음' } },
    });

    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    act(() => {
      result.current.handleDeleteSingle('doc-1');
    });

    await act(async () => {
      await result.current.confirmDeleteSingle();
    });

    expect(mockShowToast).toHaveBeenCalledWith({
      type: 'error',
      message: '삭제 권한 없음',
    });
  });

  it('confirmDeleteSingle 실패 시 기본 에러 메시지를 사용해야 한다', async () => {
    mockDeleteDocument.mockRejectedValue(new Error('network error'));

    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    act(() => {
      result.current.handleDeleteSingle('doc-1');
    });

    await act(async () => {
      await result.current.confirmDeleteSingle();
    });

    expect(mockShowToast).toHaveBeenCalledWith({
      type: 'error',
      message: '삭제 실패',
    });
  });

  it('documentToDelete가 없으면 confirmDeleteSingle이 아무것도 하지 않아야 한다', async () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    await act(async () => {
      await result.current.confirmDeleteSingle();
    });

    expect(mockDeleteDocument).not.toHaveBeenCalled();
  });

  it('handleDeleteCancel로 단일 삭제를 취소할 수 있어야 한다', () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    // 삭제 다이얼로그 열기
    act(() => {
      result.current.handleDeleteSingle('doc-1');
    });
    expect(result.current.deleteConfirmOpen).toBe(true);

    // 취소
    act(() => {
      result.current.handleDeleteCancel();
    });

    expect(result.current.deleteConfirmOpen).toBe(false);
    expect(result.current.documentToDelete).toBeNull();
  });

  // ============================================================
  // 일괄 삭제 플로우 테스트
  // ============================================================

  it('handleDeleteBulk로 일괄 삭제 다이얼로그를 열어야 한다', () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    act(() => {
      result.current.handleDeleteBulk();
    });

    expect(result.current.bulkDeleteConfirmOpen).toBe(true);
  });

  it('confirmDeleteBulk로 선택된 문서를 일괄 삭제해야 한다', async () => {
    const selectedDocuments = new Set(['doc-1', 'doc-2', 'doc-3']);

    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    await act(async () => {
      await result.current.confirmDeleteBulk(selectedDocuments);
    });

    expect(mockDeleteDocuments).toHaveBeenCalledWith(['doc-1', 'doc-2', 'doc-3']);
    expect(mockShowToast).toHaveBeenCalledWith({
      type: 'success',
      message: '3개 문서 삭제 완료',
    });
    expect(mockClearSelection).toHaveBeenCalled();
    expect(mockOnDeleted).toHaveBeenCalled();
    expect(result.current.bulkDeleteConfirmOpen).toBe(false);
  });

  it('선택된 문서가 없으면 confirmDeleteBulk가 다이얼로그를 닫아야 한다', async () => {
    const emptySelection = new Set<string>();

    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    act(() => {
      result.current.handleDeleteBulk();
    });

    await act(async () => {
      await result.current.confirmDeleteBulk(emptySelection);
    });

    expect(mockDeleteDocuments).not.toHaveBeenCalled();
    expect(result.current.bulkDeleteConfirmOpen).toBe(false);
  });

  it('confirmDeleteBulk에서 유효하지 않은 문서 ID(temp-)를 필터링해야 한다', async () => {
    const selectedDocuments = new Set(['doc-1', 'temp-123', 'doc-2']);

    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    await act(async () => {
      await result.current.confirmDeleteBulk(selectedDocuments);
    });

    expect(mockDeleteDocuments).toHaveBeenCalledWith(['doc-1', 'doc-2']);
    expect(mockShowToast).toHaveBeenCalledWith({
      type: 'success',
      message: '2개 문서 삭제 완료',
    });
  });

  it('유효한 문서가 모두 없으면 경고 토스트를 표시해야 한다', async () => {
    const selectedDocuments = new Set(['temp-1', 'temp-2']);

    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    await act(async () => {
      await result.current.confirmDeleteBulk(selectedDocuments);
    });

    expect(mockDeleteDocuments).not.toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith({
      type: 'warning',
      message: '삭제할 수 있는 유효한 문서가 없습니다.',
    });
  });

  it('handleBulkDeleteCancel로 일괄 삭제를 취소할 수 있어야 한다', () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    act(() => {
      result.current.handleDeleteBulk();
    });
    expect(result.current.bulkDeleteConfirmOpen).toBe(true);

    act(() => {
      result.current.handleBulkDeleteCancel();
    });
    expect(result.current.bulkDeleteConfirmOpen).toBe(false);
  });

  // ============================================================
  // 전체 삭제 2단계 플로우 테스트
  // ============================================================

  it('handleDeleteAll로 전체 삭제 다이얼로그를 열어야 한다', () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    act(() => {
      result.current.handleDeleteAll();
    });

    expect(result.current.deleteAllConfirmOpen).toBe(true);
  });

  it('confirmDeleteAll 1단계에서 typing 단계로 전환해야 한다', async () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    // 전체 삭제 다이얼로그 열기
    act(() => {
      result.current.handleDeleteAll();
    });

    // 1단계: confirm → typing
    await act(async () => {
      await result.current.confirmDeleteAll();
    });

    expect(result.current.deleteAllStep).toBe('typing');
    expect(mockDeleteAllDocuments).not.toHaveBeenCalled();
  });

  it('confirmDeleteAll 2단계에서 올바른 문구 입력 시 삭제를 실행해야 한다', async () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    // 전체 삭제 다이얼로그 열기
    act(() => {
      result.current.handleDeleteAll();
    });

    // 1단계 → 2단계 전환
    await act(async () => {
      await result.current.confirmDeleteAll();
    });

    // 올바른 문구 입력
    act(() => {
      result.current.setDeleteAllTyping('문서 삭제에 동의합니다.');
    });

    // 2단계 확인
    await act(async () => {
      await result.current.confirmDeleteAll();
    });

    expect(mockDeleteAllDocuments).toHaveBeenCalledWith(
      'DELETE_ALL_DOCUMENTS',
      '사용자 요청',
      false,
    );
    expect(mockShowToast).toHaveBeenCalledWith({
      type: 'success',
      message: '모든 문서 삭제 완료',
    });
    expect(mockClearSelection).toHaveBeenCalled();
    expect(mockOnDeleted).toHaveBeenCalled();
  });

  it('confirmDeleteAll 2단계에서 잘못된 문구 입력 시 에러 토스트를 표시해야 한다', async () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    act(() => {
      result.current.handleDeleteAll();
    });

    // 1단계 → 2단계
    await act(async () => {
      await result.current.confirmDeleteAll();
    });

    // 잘못된 문구
    act(() => {
      result.current.setDeleteAllTyping('잘못된 입력');
    });

    // 2단계 확인 시도
    await act(async () => {
      await result.current.confirmDeleteAll();
    });

    expect(mockDeleteAllDocuments).not.toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith({
      type: 'error',
      message: '문구를 정확히 입력해주세요.',
    });
  });

  it('handleDeleteAllCancel로 전체 삭제를 취소하고 상태를 초기화해야 한다', async () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    // 전체 삭제 → typing 단계까지 진행
    act(() => {
      result.current.handleDeleteAll();
    });

    await act(async () => {
      await result.current.confirmDeleteAll();
    });

    act(() => {
      result.current.setDeleteAllTyping('일부 입력');
    });

    // 취소
    act(() => {
      result.current.handleDeleteAllCancel();
    });

    expect(result.current.deleteAllConfirmOpen).toBe(false);
    expect(result.current.deleteAllStep).toBe('confirm');
    expect(result.current.deleteAllTyping).toBe('');
  });

  // ============================================================
  // 핸들러 존재 여부 테스트
  // ============================================================

  it('모든 핸들러가 함수로 반환되어야 한다', () => {
    const { result } = renderHook(() => useDocumentDelete(defaultProps));

    expect(typeof result.current.handleDeleteSingle).toBe('function');
    expect(typeof result.current.handleDeleteBulk).toBe('function');
    expect(typeof result.current.handleDeleteAll).toBe('function');
    expect(typeof result.current.handleDeleteCancel).toBe('function');
    expect(typeof result.current.handleBulkDeleteCancel).toBe('function');
    expect(typeof result.current.handleDeleteAllCancel).toBe('function');
    expect(typeof result.current.confirmDeleteSingle).toBe('function');
    expect(typeof result.current.confirmDeleteBulk).toBe('function');
    expect(typeof result.current.confirmDeleteAll).toBe('function');
    expect(typeof result.current.setDeleteAllTyping).toBe('function');
  });
});
