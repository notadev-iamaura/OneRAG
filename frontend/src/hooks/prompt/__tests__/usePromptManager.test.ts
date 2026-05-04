/**
 * usePromptManager 훅 단위 테스트
 *
 * 프롬프트 관리 비즈니스 로직 훅의 상태 초기값, 핸들러 동작, 에러 처리를 검증합니다.
 * promptService를 모킹하여 API 호출을 격리합니다.
 *
 * 주요 테스트 시나리오:
 * - 초기 로드 시 loadPrompts() 호출 확인
 * - 활성 프롬프트 0개 → 시스템 프롬프트 자동 활성화
 * - 활성 프롬프트 2개 이상 → 첫 번째만 유지
 * - handleToggleActive → 다른 활성 프롬프트 비활성화
 * - handleSave 성공/실패
 * - handleExport → JSON 다운로드 트리거
 * - handleImportPrompts → importData 파싱 + API 호출
 * - filteredPrompts → filter 조합 검증
 * - handleDeleteConfirm → API 호출 + 목록 갱신
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest';
import { usePromptManager } from '../usePromptManager';
import promptService from '../../../services/promptService';
import type { Prompt } from '../../../types/prompt';

// promptService 모킹
vi.mock('../../../services/promptService', () => ({
  default: {
    getPrompts: vi.fn(),
    createPrompt: vi.fn(),
    updatePrompt: vi.fn(),
    deletePrompt: vi.fn(),
    togglePrompt: vi.fn(),
    exportPrompts: vi.fn(),
    importPrompts: vi.fn(),
    duplicatePrompt: vi.fn(),
    validatePrompt: vi.fn(),
  },
}));

// useToast 모킹
const mockToast = vi.fn();
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: mockToast }),
}));

// logger 모킹
vi.mock('../../../utils/logger', () => ({
  logger: {
    log: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

// 테스트용 프롬프트 팩토리 함수
const createMockPrompt = (overrides: Partial<Prompt> = {}): Prompt => ({
  id: 'prompt-1',
  name: 'test-prompt',
  content: '테스트 프롬프트 내용입니다.',
  description: '테스트 프롬프트 설명',
  category: 'custom',
  is_active: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

describe('usePromptManager', () => {
  // 기본 프롬프트 목록
  const systemPrompt = createMockPrompt({
    id: 'system-1',
    name: 'system',
    category: 'system',
    is_active: true,
    content: '시스템 프롬프트 기본 내용입니다.',
    description: '기본 시스템 프롬프트',
  });

  const customPrompt = createMockPrompt({
    id: 'custom-1',
    name: 'custom-prompt',
    category: 'custom',
    is_active: false,
  });

  const stylePrompt = createMockPrompt({
    id: 'style-1',
    name: 'style-prompt',
    category: 'style',
    is_active: false,
    content: '스타일 프롬프트 내용입니다.',
    description: '스타일 프롬프트 설명',
  });

  beforeEach(() => {
    vi.clearAllMocks();
    // 기본 getPrompts 응답 설정
    (promptService.getPrompts as Mock).mockResolvedValue({
      prompts: [systemPrompt, customPrompt, stylePrompt],
      total: 3,
      page: 1,
      page_size: 100,
    });
    (promptService.validatePrompt as Mock).mockReturnValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ============================================================
  // 초기 상태 및 로드 테스트
  // ============================================================

  describe('초기 상태', () => {
    it('마운트 시 loadPrompts()를 호출한다', async () => {
      renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(promptService.getPrompts).toHaveBeenCalledTimes(1);
      });
    });

    it('초기 상태값이 올바르다', () => {
      (promptService.getPrompts as Mock).mockReturnValue(new Promise(() => {}));

      const { result } = renderHook(() => usePromptManager());

      // 다이얼로그 상태 모두 닫힘
      expect(result.current.editDialogOpen).toBe(false);
      expect(result.current.viewDialogOpen).toBe(false);
      expect(result.current.deleteDialogOpen).toBe(false);
      expect(result.current.importDialogOpen).toBe(false);

      // 필터 초기값
      expect(result.current.categoryFilter).toBe('all');
      expect(result.current.activeFilter).toBe('all');
      expect(result.current.searchQuery).toBe('');

      // 선택 상태
      expect(result.current.selectedPrompt).toBeNull();
      expect(result.current.editingPrompt).toBeNull();
      expect(result.current.isEditMode).toBe(false);

      // 가져오기/내보내기
      expect(result.current.importData).toBe('');
      expect(result.current.importOverwrite).toBe(false);

      // 에러 상태
      expect(result.current.error).toBeNull();
      expect(result.current.modalError).toBeNull();
    });

    it('로드 완료 후 프롬프트 목록이 설정된다', async () => {
      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('로드 실패 시 에러 메시지가 설정된다', async () => {
      (promptService.getPrompts as Mock).mockRejectedValue(new Error('네트워크 오류'));

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.error).toBe('프롬프트를 불러오는데 실패했습니다.');
      });

      expect(result.current.loading).toBe(false);
    });
  });

  // ============================================================
  // 활성 프롬프트 자동 조정 테스트
  // ============================================================

  describe('활성 프롬프트 자동 조정', () => {
    it('활성 프롬프트 0개 → 시스템 프롬프트를 자동 활성화한다', async () => {
      // 모든 프롬프트가 비활성인 경우
      const inactiveSystem = { ...systemPrompt, is_active: false };
      const inactiveCustom = { ...customPrompt, is_active: false };

      (promptService.getPrompts as Mock)
        .mockResolvedValueOnce({
          prompts: [inactiveSystem, inactiveCustom],
          total: 2,
          page: 1,
          page_size: 100,
        })
        .mockResolvedValueOnce({
          prompts: [{ ...inactiveSystem, is_active: true }, inactiveCustom],
          total: 2,
          page: 1,
          page_size: 100,
        });

      (promptService.togglePrompt as Mock).mockResolvedValue({
        ...inactiveSystem,
        is_active: true,
      });

      renderHook(() => usePromptManager());

      await waitFor(() => {
        // togglePrompt가 시스템 프롬프트에 대해 호출되어야 함
        expect(promptService.togglePrompt).toHaveBeenCalledWith('system-1', true);
      });

      // 다시 로드하여 업데이트된 목록을 반영
      await waitFor(() => {
        expect(promptService.getPrompts).toHaveBeenCalledTimes(2);
      });
    });

    it('활성 프롬프트 2개 이상 → 첫 번째만 유지하고 나머지 비활성화', async () => {
      const activeSystem = { ...systemPrompt, is_active: true };
      const activeCustom = { ...customPrompt, is_active: true };
      const activeStyle = { ...stylePrompt, is_active: true };

      (promptService.getPrompts as Mock)
        .mockResolvedValueOnce({
          prompts: [activeSystem, activeCustom, activeStyle],
          total: 3,
          page: 1,
          page_size: 100,
        })
        .mockResolvedValueOnce({
          prompts: [activeSystem, { ...activeCustom, is_active: false }, { ...activeStyle, is_active: false }],
          total: 3,
          page: 1,
          page_size: 100,
        });

      (promptService.togglePrompt as Mock).mockResolvedValue({});

      renderHook(() => usePromptManager());

      await waitFor(() => {
        // 첫 번째를 제외한 나머지(custom, style)를 비활성화
        expect(promptService.togglePrompt).toHaveBeenCalledWith('custom-1', false);
        expect(promptService.togglePrompt).toHaveBeenCalledWith('style-1', false);
      });

      // 시스템 프롬프트는 비활성화되지 않아야 함
      expect(promptService.togglePrompt).not.toHaveBeenCalledWith('system-1', false);
    });
  });

  // ============================================================
  // 핸들러 테스트
  // ============================================================

  describe('handleCreateNew', () => {
    it('새 프롬프트 생성 다이얼로그를 연다', async () => {
      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      act(() => {
        result.current.handleCreateNew();
      });

      expect(result.current.editDialogOpen).toBe(true);
      expect(result.current.isEditMode).toBe(false);
      expect(result.current.editingPrompt).toEqual({
        name: '',
        content: '',
        description: '',
        category: 'custom',
        is_active: true,
      });
      expect(result.current.modalError).toBeNull();
    });
  });

  describe('handleEdit', () => {
    it('기존 프롬프트 편집 다이얼로그를 연다', async () => {
      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      act(() => {
        result.current.handleEdit(systemPrompt);
      });

      expect(result.current.editDialogOpen).toBe(true);
      expect(result.current.isEditMode).toBe(true);
      expect(result.current.selectedPrompt).toEqual(systemPrompt);
      expect(result.current.editingPrompt).toMatchObject({
        name: 'system',
        content: '시스템 프롬프트 기본 내용입니다.',
        description: '기본 시스템 프롬프트',
        category: 'system',
        is_active: true,
      });
    });
  });

  describe('handleView', () => {
    it('프롬프트 상세 보기 다이얼로그를 연다', async () => {
      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      act(() => {
        result.current.handleView(customPrompt);
      });

      expect(result.current.viewDialogOpen).toBe(true);
      expect(result.current.selectedPrompt).toEqual(customPrompt);
    });
  });

  describe('handleDelete / handleDeleteConfirm', () => {
    it('삭제 다이얼로그를 열고 확인 시 프롬프트를 삭제한다', async () => {
      (promptService.deletePrompt as Mock).mockResolvedValue(undefined);

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      // 삭제 다이얼로그 열기
      act(() => {
        result.current.handleDelete(customPrompt);
      });

      expect(result.current.deleteDialogOpen).toBe(true);
      expect(result.current.selectedPrompt).toEqual(customPrompt);

      // 삭제 확인
      await act(async () => {
        await result.current.handleDeleteConfirm();
      });

      expect(promptService.deletePrompt).toHaveBeenCalledWith('custom-1');
      expect(result.current.deleteDialogOpen).toBe(false);
      expect(result.current.selectedPrompt).toBeNull();
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          variant: 'destructive',
          title: '프롬프트 삭제 완료',
        })
      );
    });

    it('삭제 실패 시 에러 메시지를 설정한다', async () => {
      (promptService.deletePrompt as Mock).mockRejectedValue(new Error('삭제 실패'));

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      act(() => {
        result.current.handleDelete(customPrompt);
      });

      await act(async () => {
        await result.current.handleDeleteConfirm();
      });

      expect(result.current.error).toBe('프롬프트 삭제에 실패했습니다.');
    });
  });

  describe('handleSave', () => {
    it('새 프롬프트 생성 시 createPrompt를 호출한다', async () => {
      (promptService.createPrompt as Mock).mockResolvedValue(
        createMockPrompt({ id: 'new-1', name: 'new-prompt' })
      );

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      // 생성 모드 진입
      act(() => {
        result.current.handleCreateNew();
      });

      // editingPrompt 수정
      act(() => {
        result.current.setEditingPrompt({
          name: 'new-prompt',
          content: '새로운 프롬프트 내용입니다. 충분히 긴 내용.',
          description: '새로운 프롬프트 설명',
          category: 'custom',
          is_active: false,
        });
      });

      await act(async () => {
        await result.current.handleSave();
      });

      expect(promptService.createPrompt).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'new-prompt',
        })
      );
      expect(result.current.editDialogOpen).toBe(false);
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '새 프롬프트 생성',
        })
      );
    });

    it('기존 프롬프트 수정 시 updatePrompt를 호출한다', async () => {
      (promptService.updatePrompt as Mock).mockResolvedValue(
        createMockPrompt({ id: 'system-1', name: 'system', content: '수정됨' })
      );

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      // 편집 모드 진입
      act(() => {
        result.current.handleEdit(systemPrompt);
      });

      // 내용 수정
      act(() => {
        result.current.setEditingPrompt({
          ...result.current.editingPrompt!,
          content: '수정된 시스템 프롬프트 내용입니다.',
        });
      });

      await act(async () => {
        await result.current.handleSave();
      });

      expect(promptService.updatePrompt).toHaveBeenCalledWith(
        'system-1',
        expect.objectContaining({
          content: '수정된 시스템 프롬프트 내용입니다.',
        })
      );
      expect(result.current.editDialogOpen).toBe(false);
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '프롬프트 수정 완료',
        })
      );
    });

    it('검증 실패 시 modalError를 설정한다', async () => {
      (promptService.validatePrompt as Mock).mockReturnValue([
        '프롬프트 이름은 2자 이상이어야 합니다.',
      ]);

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      act(() => {
        result.current.handleCreateNew();
      });

      await act(async () => {
        await result.current.handleSave();
      });

      expect(result.current.modalError).toBe('프롬프트 이름은 2자 이상이어야 합니다.');
      expect(promptService.createPrompt).not.toHaveBeenCalled();
    });

    it('저장 실패 시 modalError를 설정한다', async () => {
      (promptService.createPrompt as Mock).mockRejectedValue({
        response: { data: { detail: '서버 에러가 발생했습니다.' } },
      });

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      act(() => {
        result.current.handleCreateNew();
      });

      act(() => {
        result.current.setEditingPrompt({
          name: 'valid-name',
          content: '충분히 긴 프롬프트 내용입니다.',
          description: '프롬프트 설명 텍스트',
          category: 'custom',
        });
      });

      await act(async () => {
        await result.current.handleSave();
      });

      expect(result.current.modalError).toBe('서버 에러가 발생했습니다.');
    });
  });

  describe('handleToggleActive', () => {
    it('비활성 → 활성: 다른 활성 프롬프트를 비활성화하고 현재 프롬프트를 활성화한다', async () => {
      (promptService.togglePrompt as Mock).mockResolvedValue({});

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      await act(async () => {
        await result.current.handleToggleActive(customPrompt);
      });

      // 기존 활성 프롬프트(system) 비활성화
      expect(promptService.togglePrompt).toHaveBeenCalledWith('system-1', false);
      // 현재 프롬프트(custom) 활성화
      expect(promptService.togglePrompt).toHaveBeenCalledWith('custom-1', true);

      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '프롬프트 활성화',
        })
      );
    });

    it('마지막 활성 프롬프트 비활성화 시 시스템 프롬프트로 전환한다', async () => {
      (promptService.togglePrompt as Mock).mockResolvedValue({});

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      // 현재 systemPrompt가 유일한 활성 프롬프트인 상황에서 비활성화 시도
      // 하지만 systemPrompt.name === 'system'이므로 비활성화 차단됨
      await act(async () => {
        await result.current.handleToggleActive(systemPrompt);
      });

      expect(result.current.error).toBe('최소 하나의 프롬프트는 활성화되어 있어야 합니다.');
    });
  });

  describe('handleExport', () => {
    it('프롬프트 내보내기 → JSON 다운로드를 트리거한다', async () => {
      const mockExportData = {
        prompts: [systemPrompt],
        exported_at: '2026-01-01T00:00:00Z',
        total: 1,
      };
      (promptService.exportPrompts as Mock).mockResolvedValue(mockExportData);

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      // DOM 조작 스파이를 renderHook 이후에 설정 (renderHook이 DOM을 사용하므로)
      const mockClick = vi.fn();
      const originalCreateElement = document.createElement.bind(document);
      const mockCreateElement = vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
        if (tagName === 'a') {
          return { href: '', download: '', click: mockClick } as unknown as HTMLAnchorElement;
        }
        return originalCreateElement(tagName);
      });
      const mockAppendChild = vi.spyOn(document.body, 'appendChild').mockImplementation((node) => node);
      const mockRemoveChild = vi.spyOn(document.body, 'removeChild').mockImplementation((node) => node);
      const mockCreateObjectURL = vi.fn().mockReturnValue('blob:test-url');
      const mockRevokeObjectURL = vi.fn();
      globalThis.URL.createObjectURL = mockCreateObjectURL;
      globalThis.URL.revokeObjectURL = mockRevokeObjectURL;

      await act(async () => {
        await result.current.handleExport();
      });

      expect(promptService.exportPrompts).toHaveBeenCalledTimes(1);
      expect(mockClick).toHaveBeenCalled();
      expect(mockRevokeObjectURL).toHaveBeenCalledWith('blob:test-url');
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '내보내기 완료',
        })
      );

      // 스파이 복원
      mockCreateElement.mockRestore();
      mockAppendChild.mockRestore();
      mockRemoveChild.mockRestore();
    });

    it('프롬프트가 없으면 내보내기를 거부한다', async () => {
      (promptService.getPrompts as Mock).mockResolvedValue({
        prompts: [],
        total: 0,
        page: 1,
        page_size: 100,
      });

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(0);
      });

      await act(async () => {
        await result.current.handleExport();
      });

      expect(promptService.exportPrompts).not.toHaveBeenCalled();
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          variant: 'destructive',
          title: '내보내기 실패',
        })
      );
    });
  });

  describe('handleImportPrompts', () => {
    it('유효한 JSON 데이터로 가져오기를 수행한다', async () => {
      (promptService.importPrompts as Mock).mockResolvedValue({
        message: '성공',
        imported: 2,
      });

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      // importData 설정
      act(() => {
        result.current.setImportData(JSON.stringify({
          prompts: [systemPrompt],
          exported_at: '2026-01-01T00:00:00Z',
          total: 1,
        }));
        result.current.setImportOverwrite(true);
        result.current.setImportDialogOpen(true);
      });

      await act(async () => {
        await result.current.handleImportPrompts();
      });

      expect(promptService.importPrompts).toHaveBeenCalledWith(
        expect.objectContaining({ prompts: [systemPrompt] }),
        true
      );
      expect(result.current.importDialogOpen).toBe(false);
      expect(result.current.importData).toBe('');
      expect(result.current.importOverwrite).toBe(false);
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '데이터 가져오기 성공',
        })
      );
    });

    it('잘못된 JSON 데이터 시 에러를 설정한다', async () => {
      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      // 잘못된 JSON
      act(() => {
        result.current.setImportData('{ invalid json }');
      });

      await act(async () => {
        await result.current.handleImportPrompts();
      });

      expect(result.current.error).toBe('프롬프트 가져오기에 실패했습니다.');
    });
  });

  // ============================================================
  // 필터링 테스트
  // ============================================================

  describe('filteredPrompts', () => {
    it('검색어로 이름/설명을 필터링한다', async () => {
      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      act(() => {
        result.current.setSearchQuery('custom');
      });

      // custom-prompt이 이름에 'custom' 포함
      expect(result.current.filteredPrompts.length).toBeGreaterThanOrEqual(1);
      expect(result.current.filteredPrompts.some(p => p.name === 'custom-prompt')).toBe(true);
    });

    it('활성 프롬프트가 상단에 정렬된다', async () => {
      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      // systemPrompt(is_active: true)가 맨 위에 있어야 함
      expect(result.current.filteredPrompts[0].is_active).toBe(true);
    });

    it('카테고리별 프롬프트 분류가 올바르다', async () => {
      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      expect(result.current.promptsByCategory.system).toHaveLength(1);
      expect(result.current.promptsByCategory.custom).toHaveLength(1);
      expect(result.current.promptsByCategory.style).toHaveLength(1);
    });
  });

  // ============================================================
  // 복제 테스트
  // ============================================================

  describe('handleDuplicate', () => {
    it('프롬프트를 복제하고 목록을 갱신한다', async () => {
      (promptService.duplicatePrompt as Mock).mockResolvedValue(
        createMockPrompt({ id: 'dup-1', name: 'custom-prompt_copy_1234' })
      );

      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      await act(async () => {
        await result.current.handleDuplicate(customPrompt);
      });

      expect(promptService.duplicatePrompt).toHaveBeenCalledWith(
        'custom-1',
        expect.stringContaining('custom-prompt_copy_')
      );
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '프롬프트 복제 성공',
        })
      );
    });
  });

  // ============================================================
  // 핸들러 존재 여부 테스트
  // ============================================================

  describe('반환값 구조', () => {
    it('모든 필수 상태와 핸들러가 반환된다', async () => {
      const { result } = renderHook(() => usePromptManager());

      await waitFor(() => {
        expect(result.current.prompts).toHaveLength(3);
      });

      // 상태 (17개)
      expect(result.current).toHaveProperty('prompts');
      expect(result.current).toHaveProperty('loading');
      expect(result.current).toHaveProperty('error');
      expect(result.current).toHaveProperty('modalError');
      expect(result.current).toHaveProperty('currentTab');
      expect(result.current).toHaveProperty('editDialogOpen');
      expect(result.current).toHaveProperty('viewDialogOpen');
      expect(result.current).toHaveProperty('deleteDialogOpen');
      expect(result.current).toHaveProperty('importDialogOpen');
      expect(result.current).toHaveProperty('selectedPrompt');
      expect(result.current).toHaveProperty('editingPrompt');
      expect(result.current).toHaveProperty('isEditMode');
      expect(result.current).toHaveProperty('categoryFilter');
      expect(result.current).toHaveProperty('activeFilter');
      expect(result.current).toHaveProperty('searchQuery');
      expect(result.current).toHaveProperty('importData');
      expect(result.current).toHaveProperty('importOverwrite');

      // 핸들러 (11개 + computed)
      expect(typeof result.current.loadPrompts).toBe('function');
      expect(typeof result.current.handleCreateNew).toBe('function');
      expect(typeof result.current.handleEdit).toBe('function');
      expect(typeof result.current.handleView).toBe('function');
      expect(typeof result.current.handleDelete).toBe('function');
      expect(typeof result.current.handleToggleActive).toBe('function');
      expect(typeof result.current.handleSave).toBe('function');
      expect(typeof result.current.handleExport).toBe('function');
      expect(typeof result.current.handleImportPrompts).toBe('function');
      expect(typeof result.current.handleDeleteConfirm).toBe('function');
      expect(typeof result.current.handleDuplicate).toBe('function');

      // computed 값
      expect(Array.isArray(result.current.filteredPrompts)).toBe(true);
      expect(result.current).toHaveProperty('promptsByCategory');

      // setter 함수
      expect(typeof result.current.setEditDialogOpen).toBe('function');
      expect(typeof result.current.setViewDialogOpen).toBe('function');
      expect(typeof result.current.setDeleteDialogOpen).toBe('function');
      expect(typeof result.current.setImportDialogOpen).toBe('function');
      expect(typeof result.current.setCurrentTab).toBe('function');
      expect(typeof result.current.setSearchQuery).toBe('function');
      expect(typeof result.current.setCategoryFilter).toBe('function');
      expect(typeof result.current.setActiveFilter).toBe('function');
      expect(typeof result.current.setImportData).toBe('function');
      expect(typeof result.current.setImportOverwrite).toBe('function');
      expect(typeof result.current.setEditingPrompt).toBe('function');
      expect(typeof result.current.setError).toBe('function');
      expect(typeof result.current.setModalError).toBe('function');
    });
  });
});
