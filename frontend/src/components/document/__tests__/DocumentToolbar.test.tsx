/**
 * DocumentToolbar 컴포넌트 테스트
 *
 * 검색, 정렬, 뷰 모드 전환, 삭제 버튼 등 툴바 기능을 검증합니다.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { DocumentToolbar } from '../DocumentToolbar';
import { checkA11y } from '../../../test/axeHelper';

describe('DocumentToolbar', () => {
  const defaultProps = {
    searchQuery: '',
    sortField: 'uploadedAt' as const,
    sortDirection: 'desc' as const,
    viewMode: 'list' as const,
    loading: false,
    selectedCount: 0,
    onSearchChange: vi.fn(),
    onSortFieldChange: vi.fn(),
    onSortDirectionToggle: vi.fn(),
    onViewModeChange: vi.fn(),
    onRefresh: vi.fn(),
    onBulkDelete: vi.fn(),
    onDeleteAll: vi.fn(),
  };

  it('검색 입력 필드를 렌더링합니다', () => {
    render(<DocumentToolbar {...defaultProps} />);
    expect(screen.getByPlaceholderText('문서 검색...')).toBeInTheDocument();
  });

  it('아이콘 전용 컨트롤에 접근 가능한 이름을 제공합니다', async () => {
    const { container } = render(<DocumentToolbar {...defaultProps} />);

    expect(screen.getByRole('textbox', { name: '문서 검색' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '내림차순 정렬' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '목록 보기' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '격자 보기' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: '문서 새로고침' })).toBeInTheDocument();

    const results = await checkA11y(container);
    expect(results.violations).toHaveLength(0);
  });

  it('검색어 입력 시 onSearchChange를 호출합니다', () => {
    const onSearchChange = vi.fn();
    render(<DocumentToolbar {...defaultProps} onSearchChange={onSearchChange} />);
    const input = screen.getByPlaceholderText('문서 검색...');
    fireEvent.change(input, { target: { value: '테스트' } });
    expect(onSearchChange).toHaveBeenCalledWith('테스트');
  });

  it('정렬 방향 버튼 클릭 시 onSortDirectionToggle을 호출합니다', () => {
    const onSortDirectionToggle = vi.fn();
    render(<DocumentToolbar {...defaultProps} onSortDirectionToggle={onSortDirectionToggle} />);
    // 정렬 방향 토글 버튼 (ArrowDown 아이콘이 있는 버튼)
    const sortDirButton = screen.getByTestId('sort-direction-button');
    fireEvent.click(sortDirButton);
    expect(onSortDirectionToggle).toHaveBeenCalled();
  });

  it('리스트 뷰 모드 버튼 클릭 시 onViewModeChange("list")를 호출합니다', () => {
    const onViewModeChange = vi.fn();
    render(<DocumentToolbar {...defaultProps} viewMode="grid" onViewModeChange={onViewModeChange} />);
    const listButton = screen.getByTestId('view-mode-list');
    fireEvent.click(listButton);
    expect(onViewModeChange).toHaveBeenCalledWith('list');
  });

  it('그리드 뷰 모드 버튼 클릭 시 onViewModeChange("grid")를 호출합니다', () => {
    const onViewModeChange = vi.fn();
    render(<DocumentToolbar {...defaultProps} viewMode="list" onViewModeChange={onViewModeChange} />);
    const gridButton = screen.getByTestId('view-mode-grid');
    fireEvent.click(gridButton);
    expect(onViewModeChange).toHaveBeenCalledWith('grid');
  });

  it('선택된 문서가 없으면 선택 삭제 버튼이 표시되지 않습니다', () => {
    render(<DocumentToolbar {...defaultProps} selectedCount={0} />);
    expect(screen.queryByText(/선택 삭제/)).not.toBeInTheDocument();
  });

  it('선택된 문서가 있으면 선택 삭제 버튼이 표시됩니다', () => {
    render(<DocumentToolbar {...defaultProps} selectedCount={3} />);
    expect(screen.getByText(/선택 삭제 \(3\)/)).toBeInTheDocument();
  });

  it('선택 삭제 버튼 클릭 시 onBulkDelete를 호출합니다', () => {
    const onBulkDelete = vi.fn();
    render(<DocumentToolbar {...defaultProps} selectedCount={2} onBulkDelete={onBulkDelete} />);
    const bulkDeleteButton = screen.getByText(/선택 삭제/);
    fireEvent.click(bulkDeleteButton);
    expect(onBulkDelete).toHaveBeenCalled();
  });

  it('전체 삭제 버튼이 항상 표시됩니다', () => {
    render(<DocumentToolbar {...defaultProps} />);
    expect(screen.getByText('전체 삭제')).toBeInTheDocument();
  });

  it('전체 삭제 버튼 클릭 시 onDeleteAll을 호출합니다', () => {
    const onDeleteAll = vi.fn();
    render(<DocumentToolbar {...defaultProps} onDeleteAll={onDeleteAll} />);
    fireEvent.click(screen.getByText('전체 삭제'));
    expect(onDeleteAll).toHaveBeenCalled();
  });

  it('새로고침 버튼 클릭 시 onRefresh를 호출합니다', () => {
    const onRefresh = vi.fn();
    render(<DocumentToolbar {...defaultProps} onRefresh={onRefresh} />);
    const refreshButton = screen.getByTestId('refresh-button');
    fireEvent.click(refreshButton);
    expect(onRefresh).toHaveBeenCalled();
  });
});
