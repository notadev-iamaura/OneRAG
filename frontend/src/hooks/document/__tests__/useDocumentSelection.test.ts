/**
 * useDocumentSelection 훅 단위 테스트
 *
 * 문서 선택/해제, 전체 선택, 상세 보기 열기/닫기를 검증합니다.
 */
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useDocumentSelection } from '../useDocumentSelection';
import type { Document } from '../../../types';

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

describe('useDocumentSelection', () => {
  const mockShowToast = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ============================================================
  // 초기 상태 테스트
  // ============================================================

  it('초기 상태가 올바르게 설정되어야 한다', () => {
    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    expect(result.current.selectedDocuments).toEqual(new Set());
    expect(result.current.selectedDocument).toBeNull();
    expect(result.current.detailsOpen).toBe(false);
  });

  // ============================================================
  // toggleSelect 테스트
  // ============================================================

  it('toggleSelect로 문서를 선택할 수 있어야 한다', () => {
    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    act(() => {
      result.current.toggleSelect('doc-1');
    });

    expect(result.current.selectedDocuments.has('doc-1')).toBe(true);
    expect(result.current.selectedDocuments.size).toBe(1);
  });

  it('toggleSelect로 이미 선택된 문서를 해제할 수 있어야 한다', () => {
    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    // 선택
    act(() => {
      result.current.toggleSelect('doc-1');
    });
    expect(result.current.selectedDocuments.has('doc-1')).toBe(true);

    // 해제
    act(() => {
      result.current.toggleSelect('doc-1');
    });
    expect(result.current.selectedDocuments.has('doc-1')).toBe(false);
    expect(result.current.selectedDocuments.size).toBe(0);
  });

  it('유효하지 않은 문서 ID(temp- 접두사)로 선택 시 경고 토스트를 표시해야 한다', () => {
    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    act(() => {
      result.current.toggleSelect('temp-123');
    });

    expect(mockShowToast).toHaveBeenCalledWith({
      type: 'warning',
      message: '선택할 수 없는 문서입니다.',
    });
    expect(result.current.selectedDocuments.size).toBe(0);
  });

  it('빈 문서 ID로 선택 시 경고 토스트를 표시해야 한다', () => {
    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    act(() => {
      result.current.toggleSelect('');
    });

    expect(mockShowToast).toHaveBeenCalledWith({
      type: 'warning',
      message: '선택할 수 없는 문서입니다.',
    });
  });

  // ============================================================
  // toggleSelectAll 테스트
  // ============================================================

  it('toggleSelectAll로 모든 유효한 문서를 선택할 수 있어야 한다', () => {
    const documents: Document[] = [
      createMockDocument({ id: 'doc-1' }),
      createMockDocument({ id: 'doc-2' }),
      createMockDocument({ id: 'doc-3' }),
    ];

    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    act(() => {
      result.current.toggleSelectAll(documents);
    });

    expect(result.current.selectedDocuments.size).toBe(3);
    expect(result.current.selectedDocuments.has('doc-1')).toBe(true);
    expect(result.current.selectedDocuments.has('doc-2')).toBe(true);
    expect(result.current.selectedDocuments.has('doc-3')).toBe(true);
  });

  it('모든 문서가 이미 선택되어 있으면 toggleSelectAll로 전체 해제해야 한다', () => {
    const documents: Document[] = [
      createMockDocument({ id: 'doc-1' }),
      createMockDocument({ id: 'doc-2' }),
    ];

    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    // 전체 선택
    act(() => {
      result.current.toggleSelectAll(documents);
    });
    expect(result.current.selectedDocuments.size).toBe(2);

    // 전체 해제
    act(() => {
      result.current.toggleSelectAll(documents);
    });
    expect(result.current.selectedDocuments.size).toBe(0);
  });

  it('toggleSelectAll 시 유효하지 않은 문서(temp- 접두사)는 제외해야 한다', () => {
    const documents: Document[] = [
      createMockDocument({ id: 'doc-1' }),
      createMockDocument({ id: 'temp-123' }),
      createMockDocument({ id: 'doc-2' }),
    ];

    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    act(() => {
      result.current.toggleSelectAll(documents);
    });

    expect(result.current.selectedDocuments.size).toBe(2);
    expect(result.current.selectedDocuments.has('temp-123')).toBe(false);
  });

  // ============================================================
  // clearSelection 테스트
  // ============================================================

  it('clearSelection으로 선택을 초기화할 수 있어야 한다', () => {
    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    // 먼저 문서 선택
    act(() => {
      result.current.toggleSelect('doc-1');
      result.current.toggleSelect('doc-2');
    });
    expect(result.current.selectedDocuments.size).toBe(2);

    // 선택 초기화
    act(() => {
      result.current.clearSelection();
    });
    expect(result.current.selectedDocuments.size).toBe(0);
  });

  // ============================================================
  // viewDetails / closeDetails 테스트
  // ============================================================

  it('viewDetails로 문서 상세 보기를 열 수 있어야 한다', () => {
    const doc = createMockDocument({ id: 'doc-1' });

    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    act(() => {
      result.current.viewDetails(doc);
    });

    expect(result.current.selectedDocument).toEqual(doc);
    expect(result.current.detailsOpen).toBe(true);
  });

  it('closeDetails로 문서 상세 보기를 닫을 수 있어야 한다', () => {
    const doc = createMockDocument({ id: 'doc-1' });

    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    // 열기
    act(() => {
      result.current.viewDetails(doc);
    });
    expect(result.current.detailsOpen).toBe(true);

    // 닫기
    act(() => {
      result.current.closeDetails();
    });
    expect(result.current.detailsOpen).toBe(false);
  });

  // ============================================================
  // 핸들러 존재 여부 테스트
  // ============================================================

  it('모든 핸들러가 함수로 반환되어야 한다', () => {
    const { result } = renderHook(() =>
      useDocumentSelection({ showToast: mockShowToast }),
    );

    expect(typeof result.current.toggleSelect).toBe('function');
    expect(typeof result.current.toggleSelectAll).toBe('function');
    expect(typeof result.current.clearSelection).toBe('function');
    expect(typeof result.current.viewDetails).toBe('function');
    expect(typeof result.current.closeDetails).toBe('function');
  });
});
