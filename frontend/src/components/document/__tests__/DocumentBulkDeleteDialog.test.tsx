/**
 * DocumentBulkDeleteDialog 컴포넌트 테스트
 *
 * 일괄 삭제 확인 다이얼로그의 렌더링, 선택 개수 표시, 확인/취소 동작을 검증합니다.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { DocumentBulkDeleteDialog } from '../DocumentBulkDeleteDialog';

describe('DocumentBulkDeleteDialog', () => {
  const defaultProps = {
    open: true,
    loading: false,
    selectedCount: 5,
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  };

  it('선택된 문서 개수를 제목에 표시합니다', () => {
    render(<DocumentBulkDeleteDialog {...defaultProps} />);
    expect(screen.getByText('5개 문서 삭제')).toBeInTheDocument();
  });

  it('경고 메시지를 표시합니다', () => {
    render(<DocumentBulkDeleteDialog {...defaultProps} />);
    expect(screen.getByText(/선택한 모든 문서를 영구적으로 삭제합니다/)).toBeInTheDocument();
  });

  it('취소 버튼 클릭 시 onCancel을 호출합니다', () => {
    const onCancel = vi.fn();
    render(<DocumentBulkDeleteDialog {...defaultProps} onCancel={onCancel} />);
    fireEvent.click(screen.getByText('취소'));
    expect(onCancel).toHaveBeenCalled();
  });

  it('삭제 승인 버튼 클릭 시 onConfirm을 호출합니다', () => {
    const onConfirm = vi.fn();
    render(<DocumentBulkDeleteDialog {...defaultProps} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByText('삭제 승인'));
    expect(onConfirm).toHaveBeenCalled();
  });

  it('로딩 중에는 취소 버튼이 비활성화됩니다', () => {
    render(<DocumentBulkDeleteDialog {...defaultProps} loading={true} />);
    expect(screen.getByText('취소')).toBeDisabled();
  });

  it('로딩 중에는 삭제 승인 버튼이 비활성화됩니다', () => {
    render(<DocumentBulkDeleteDialog {...defaultProps} loading={true} />);
    expect(screen.getByText('삭제 승인')).toBeDisabled();
  });

  it('선택 개수가 변경되면 제목이 업데이트됩니다', () => {
    const { rerender } = render(<DocumentBulkDeleteDialog {...defaultProps} selectedCount={3} />);
    expect(screen.getByText('3개 문서 삭제')).toBeInTheDocument();
    rerender(<DocumentBulkDeleteDialog {...defaultProps} selectedCount={10} />);
    expect(screen.getByText('10개 문서 삭제')).toBeInTheDocument();
  });
});
