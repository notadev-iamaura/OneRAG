/**
 * DocumentDeleteDialog 컴포넌트 테스트
 *
 * 단일 문서 삭제 확인 다이얼로그의 렌더링, 확인/취소 동작을 검증합니다.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { DocumentDeleteDialog } from '../DocumentDeleteDialog';

describe('DocumentDeleteDialog', () => {
  const defaultProps = {
    open: true,
    loading: false,
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  };

  it('다이얼로그 제목을 렌더링합니다', () => {
    render(<DocumentDeleteDialog {...defaultProps} />);
    expect(screen.getByText('문서 삭제')).toBeInTheDocument();
  });

  it('경고 메시지를 표시합니다', () => {
    render(<DocumentDeleteDialog {...defaultProps} />);
    expect(screen.getByText(/이 문서를 삭제하시겠습니까/)).toBeInTheDocument();
    expect(screen.getByText(/되돌릴 수 없습니다/)).toBeInTheDocument();
  });

  it('취소 버튼 클릭 시 onCancel을 호출합니다', () => {
    const onCancel = vi.fn();
    render(<DocumentDeleteDialog {...defaultProps} onCancel={onCancel} />);
    fireEvent.click(screen.getByText('취소'));
    expect(onCancel).toHaveBeenCalled();
  });

  it('삭제하기 버튼 클릭 시 onConfirm을 호출합니다', () => {
    const onConfirm = vi.fn();
    render(<DocumentDeleteDialog {...defaultProps} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByText('삭제하기'));
    expect(onConfirm).toHaveBeenCalled();
  });

  it('로딩 중에는 "삭제 중..." 텍스트를 표시합니다', () => {
    render(<DocumentDeleteDialog {...defaultProps} loading={true} />);
    expect(screen.getByText('삭제 중...')).toBeInTheDocument();
  });

  it('로딩 중에는 취소 버튼이 비활성화됩니다', () => {
    render(<DocumentDeleteDialog {...defaultProps} loading={true} />);
    expect(screen.getByText('취소')).toBeDisabled();
  });

  it('로딩 중에는 삭제 버튼이 비활성화됩니다', () => {
    render(<DocumentDeleteDialog {...defaultProps} loading={true} />);
    expect(screen.getByText('삭제 중...')).toBeDisabled();
  });
});
