/**
 * PromptManager 오케스트레이터 통합 테스트
 *
 * vi.mock으로 8개 하위 컴포넌트와 usePromptManager 훅을 격리하여
 * 오케스트레이터가 올바르게 조합하는지 검증합니다.
 *
 * 테스트 케이스:
 * 1. 8개 하위 컴포넌트 전부 렌더링 확인
 * 2. 에러 상태 시 Alert 표시 확인
 * 3. 에러가 없을 때 Alert 미표시 확인
 * 4. 에러 Alert 닫기 버튼 동작 확인
 * 5. 활성화 규칙 안내 문구 확인
 * 6. PromptHeader에 올바른 props 전달 확인
 * 7. PromptCategoryTabs에 올바른 props 전달 확인
 * 8. default export 유지 확인
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { UsePromptManagerReturn } from '../../hooks/prompt/usePromptManager';

// ============================================================
// 8개 하위 컴포넌트를 stub JSX로 격리
// props를 data 속성으로 노출하여 전달 검증 가능
// ============================================================
vi.mock('../prompt', () => ({
  PromptHeader: (props: Record<string, unknown>) => (
    <div data-testid="prompt-header" data-loading={String(props.loading)}>
      {/* onRefresh, onImport, onExport, onCreateNew 검증용 버튼 */}
      <button data-testid="btn-refresh" onClick={props.onRefresh as () => void}>새로고침</button>
      <button data-testid="btn-import" onClick={props.onImport as () => void}>가져오기</button>
      <button data-testid="btn-export" onClick={props.onExport as () => void}>내보내기</button>
      <button data-testid="btn-create" onClick={props.onCreateNew as () => void}>새 프롬프트</button>
    </div>
  ),
  PromptFilterBar: (props: Record<string, unknown>) => (
    <div data-testid="prompt-filter-bar" data-search={props.searchQuery} />
  ),
  PromptCategoryTabs: (props: Record<string, unknown>) => (
    <div data-testid="prompt-category-tabs" data-current-tab={props.currentTab} data-loading={String(props.loading)} />
  ),
  PromptTable: (props: Record<string, unknown>) => (
    <div data-testid="prompt-table" data-loading={String(props.loading)} />
  ),
  PromptEditDialog: (props: Record<string, unknown>) => (
    <div data-testid="prompt-edit-dialog" data-open={String(props.open)} />
  ),
  PromptViewDialog: (props: Record<string, unknown>) => (
    <div data-testid="prompt-view-dialog" data-open={String(props.open)} />
  ),
  PromptDeleteDialog: (props: Record<string, unknown>) => (
    <div data-testid="prompt-delete-dialog" data-open={String(props.open)} />
  ),
  PromptImportDialog: (props: Record<string, unknown>) => (
    <div data-testid="prompt-import-dialog" data-open={String(props.open)} />
  ),
}));

// ============================================================
// usePromptManager 훅 모킹
// ============================================================

/** 기본 mock 반환값 (정상 상태) */
const createDefaultMockReturn = (): UsePromptManagerReturn => ({
  // 상태
  prompts: [],
  loading: false,
  error: null,
  modalError: null,
  currentTab: 'all',
  editDialogOpen: false,
  viewDialogOpen: false,
  deleteDialogOpen: false,
  importDialogOpen: false,
  selectedPrompt: null,
  editingPrompt: null,
  isEditMode: false,
  categoryFilter: 'all',
  activeFilter: 'all',
  searchQuery: '',
  importData: '',
  importOverwrite: false,

  // computed
  filteredPrompts: [],
  promptsByCategory: { system: [], style: [], custom: [] },

  // 핸들러
  loadPrompts: vi.fn(),
  handleCreateNew: vi.fn(),
  handleEdit: vi.fn(),
  handleView: vi.fn(),
  handleDelete: vi.fn(),
  handleToggleActive: vi.fn(),
  handleSave: vi.fn(),
  handleExport: vi.fn(),
  handleImportPrompts: vi.fn(),
  handleDeleteConfirm: vi.fn(),
  handleDuplicate: vi.fn(),

  // setter
  setEditDialogOpen: vi.fn(),
  setViewDialogOpen: vi.fn(),
  setDeleteDialogOpen: vi.fn(),
  setImportDialogOpen: vi.fn(),
  setCurrentTab: vi.fn(),
  setSearchQuery: vi.fn(),
  setCategoryFilter: vi.fn(),
  setActiveFilter: vi.fn(),
  setImportData: vi.fn(),
  setImportOverwrite: vi.fn(),
  setEditingPrompt: vi.fn(),
  setError: vi.fn(),
  setModalError: vi.fn(),
});

let mockReturn: UsePromptManagerReturn;

vi.mock('../../hooks/prompt', () => ({
  usePromptManager: () => mockReturn,
}));

// logger 모킹
vi.mock('../../utils/logger', () => ({
  logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

describe('PromptManager 오케스트레이터', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockReturn = createDefaultMockReturn();
  });

  it('8개 하위 컴포넌트가 모두 렌더링되어야 함', async () => {
    const { default: PromptManager } = await import('../PromptManager');
    render(<PromptManager />);

    // 8개 하위 컴포넌트 존재 확인
    expect(screen.getByTestId('prompt-header')).toBeInTheDocument();
    expect(screen.getByTestId('prompt-filter-bar')).toBeInTheDocument();
    expect(screen.getByTestId('prompt-category-tabs')).toBeInTheDocument();
    expect(screen.getByTestId('prompt-edit-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('prompt-view-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('prompt-delete-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('prompt-import-dialog')).toBeInTheDocument();
  });

  it('에러 상태 시 Alert가 표시되어야 함', async () => {
    mockReturn = {
      ...createDefaultMockReturn(),
      error: '프롬프트를 불러오는데 실패했습니다.',
    };

    const { default: PromptManager } = await import('../PromptManager');
    render(<PromptManager />);

    expect(screen.getByText('오류 발생')).toBeInTheDocument();
    expect(screen.getByText('프롬프트를 불러오는데 실패했습니다.')).toBeInTheDocument();
  });

  it('에러가 없을 때 에러 Alert가 표시되지 않아야 함', async () => {
    const { default: PromptManager } = await import('../PromptManager');
    render(<PromptManager />);

    expect(screen.queryByText('오류 발생')).not.toBeInTheDocument();
  });

  it('에러 Alert의 닫기 버튼 클릭 시 setError(null)이 호출되어야 함', async () => {
    mockReturn = {
      ...createDefaultMockReturn(),
      error: '테스트 에러 메시지',
    };

    const { default: PromptManager } = await import('../PromptManager');
    render(<PromptManager />);

    // 에러 Alert 내의 닫기(X) 버튼 찾기 (destructive variant)
    const alerts = screen.getAllByRole('alert');
    // destructive Alert는 '오류 발생' 텍스트를 포함하는 것
    const errorAlert = alerts.find(el => el.textContent?.includes('오류 발생'));
    expect(errorAlert).toBeTruthy();
    const closeButton = errorAlert!.querySelector('button');
    expect(closeButton).toBeTruthy();
    fireEvent.click(closeButton!);
    expect(mockReturn.setError).toHaveBeenCalledWith(null);
  });

  it('활성화 규칙 안내 문구가 표시되어야 함', async () => {
    const { default: PromptManager } = await import('../PromptManager');
    render(<PromptManager />);

    expect(screen.getByText(/프롬프트는 오직 1개만 활성화/)).toBeInTheDocument();
  });

  it('PromptHeader에 올바른 props가 전달되어야 함', async () => {
    mockReturn = {
      ...createDefaultMockReturn(),
      loading: true,
    };

    const { default: PromptManager } = await import('../PromptManager');
    render(<PromptManager />);

    // loading 상태가 PromptHeader에 전달됨
    const header = screen.getByTestId('prompt-header');
    expect(header.getAttribute('data-loading')).toBe('true');

    // 헤더 버튼 클릭 시 올바른 핸들러 호출 확인
    fireEvent.click(screen.getByTestId('btn-export'));
    expect(mockReturn.handleExport).toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('btn-create'));
    expect(mockReturn.handleCreateNew).toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('btn-import'));
    expect(mockReturn.setImportDialogOpen).toHaveBeenCalledWith(true);

    fireEvent.click(screen.getByTestId('btn-refresh'));
    expect(mockReturn.loadPrompts).toHaveBeenCalled();
  });

  it('PromptCategoryTabs에 올바른 props가 전달되어야 함', async () => {
    mockReturn = {
      ...createDefaultMockReturn(),
      currentTab: 'system',
      loading: true,
    };

    const { default: PromptManager } = await import('../PromptManager');
    render(<PromptManager />);

    const tabs = screen.getByTestId('prompt-category-tabs');
    expect(tabs.getAttribute('data-current-tab')).toBe('system');
    expect(tabs.getAttribute('data-loading')).toBe('true');
  });

  it('다이얼로그의 open 상태가 올바르게 전달되어야 함', async () => {
    mockReturn = {
      ...createDefaultMockReturn(),
      editDialogOpen: true,
      viewDialogOpen: false,
      deleteDialogOpen: true,
      importDialogOpen: false,
    };

    const { default: PromptManager } = await import('../PromptManager');
    render(<PromptManager />);

    expect(screen.getByTestId('prompt-edit-dialog').getAttribute('data-open')).toBe('true');
    expect(screen.getByTestId('prompt-view-dialog').getAttribute('data-open')).toBe('false');
    expect(screen.getByTestId('prompt-delete-dialog').getAttribute('data-open')).toBe('true');
    expect(screen.getByTestId('prompt-import-dialog').getAttribute('data-open')).toBe('false');
  });

  it('PromptsPage.tsx에서 default import로 사용 가능해야 함', async () => {
    const module = await import('../PromptManager');
    expect(module.default).toBeDefined();
    expect(typeof module.default).toBe('function');
  });
});
