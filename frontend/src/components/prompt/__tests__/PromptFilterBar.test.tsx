/**
 * PromptFilterBar 컴포넌트 테스트
 *
 * 프롬프트 필터 바의 렌더링과 인터랙션을 검증합니다.
 * - 카테고리 필터 렌더링
 * - 활성 상태 필터 렌더링
 * - 검색어 입력
 * - 총 개수 표시
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { PromptFilterBar } from '../PromptFilterBar';

describe('PromptFilterBar', () => {
  const defaultProps = {
    searchQuery: '',
    categoryFilter: 'all',
    activeFilter: 'all',
    filteredCount: 5,
    onSearchQueryChange: vi.fn(),
    onCategoryFilterChange: vi.fn(),
    onActiveFilterChange: vi.fn(),
  };

  it('검색 입력 필드를 렌더링해야 한다', () => {
    render(<PromptFilterBar {...defaultProps} />);
    expect(screen.getByPlaceholderText('이름 또는 설명으로 검색...')).toBeInTheDocument();
  });

  it('검색어 입력 시 onSearchQueryChange가 호출되어야 한다', () => {
    render(<PromptFilterBar {...defaultProps} />);
    const searchInput = screen.getByPlaceholderText('이름 또는 설명으로 검색...');
    fireEvent.change(searchInput, { target: { value: '테스트' } });
    expect(defaultProps.onSearchQueryChange).toHaveBeenCalledWith('테스트');
  });

  it('필터링된 프롬프트 총 개수를 표시해야 한다', () => {
    render(<PromptFilterBar {...defaultProps} />);
    expect(screen.getByText('총 5개')).toBeInTheDocument();
  });

  it('개수가 0인 경우에도 표시해야 한다', () => {
    render(<PromptFilterBar {...defaultProps} filteredCount={0} />);
    expect(screen.getByText('총 0개')).toBeInTheDocument();
  });
});
