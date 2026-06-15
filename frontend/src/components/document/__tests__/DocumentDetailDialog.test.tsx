/**
 * DocumentDetailDialog 컴포넌트 테스트
 *
 * 문서 상세 정보 다이얼로그의 렌더링과 닫기 동작을 검증합니다.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { DocumentDetailDialog } from '../DocumentDetailDialog';
import type { Document } from '../../../types';

/** 테스트용 문서 데이터 팩토리 */
const createMockDocument = (overrides: Partial<Document> = {}): Document => ({
  id: 'doc-detail-1',
  filename: 'detail-test.pdf',
  originalName: 'detail-original.pdf',
  size: 5120,
  mimeType: 'application/pdf',
  uploadedAt: '2026-02-20T14:00:00Z',
  status: 'completed',
  chunks: 15,
  metadata: { pageCount: 10, wordCount: 3000 },
  ...overrides,
});

describe('DocumentDetailDialog', () => {
  const defaultProps = {
    open: true,
    document: createMockDocument(),
    onClose: vi.fn(),
  };

  it('다이얼로그 제목을 렌더링합니다', () => {
    render(<DocumentDetailDialog {...defaultProps} />);
    expect(screen.getByText('문서 상세 정보')).toBeInTheDocument();
  });

  it('문서 파일명을 표시합니다', () => {
    render(<DocumentDetailDialog {...defaultProps} />);
    expect(screen.getByText('detail-original.pdf')).toBeInTheDocument();
  });

  it('문서 ID를 표시합니다', () => {
    render(<DocumentDetailDialog {...defaultProps} />);
    expect(screen.getByText('doc-detail-1')).toBeInTheDocument();
  });

  it('파일 크기를 포맷하여 표시합니다', () => {
    render(<DocumentDetailDialog {...defaultProps} />);
    expect(screen.getByText('5 KB')).toBeInTheDocument();
  });

  it('MIME 타입을 표시합니다', () => {
    render(<DocumentDetailDialog {...defaultProps} />);
    expect(screen.getByText('application/pdf')).toBeInTheDocument();
  });

  it('상태를 표시합니다', () => {
    render(<DocumentDetailDialog {...defaultProps} />);
    expect(screen.getByText('completed')).toBeInTheDocument();
  });

  it('청크 수를 표시합니다', () => {
    render(<DocumentDetailDialog {...defaultProps} />);
    expect(screen.getByText('15개')).toBeInTheDocument();
  });

  it('페이지 수를 표시합니다 (metadata 있을 때)', () => {
    render(<DocumentDetailDialog {...defaultProps} />);
    expect(screen.getByText('10P')).toBeInTheDocument();
  });

  it('단어 수를 표시합니다 (metadata 있을 때)', () => {
    render(<DocumentDetailDialog {...defaultProps} />);
    expect(screen.getByText('3000개')).toBeInTheDocument();
  });

  it('닫기 버튼 클릭 시 onClose를 호출합니다', () => {
    const onClose = vi.fn();
    render(<DocumentDetailDialog {...defaultProps} onClose={onClose} />);
    fireEvent.click(screen.getByText('닫기'));
    expect(onClose).toHaveBeenCalled();
  });

  it('document가 null이면 상세 정보를 표시하지 않습니다', () => {
    render(<DocumentDetailDialog {...defaultProps} document={null} />);
    expect(screen.queryByText('detail-original.pdf')).not.toBeInTheDocument();
  });

  it('카운트가 0이면 해당 행을 숨기고 길잃은 "0"을 렌더링하지 않습니다', () => {
    const zeroCountDoc = createMockDocument({
      chunks: 0,
      metadata: { pageCount: 0, wordCount: 0 },
    });
    render(<DocumentDetailDialog {...defaultProps} document={zeroCountDoc} />);

    // 0인 카운트 행은 라벨/값 모두 표시되지 않아야 한다.
    expect(screen.queryByText('0개')).not.toBeInTheDocument();
    expect(screen.queryByText('0P')).not.toBeInTheDocument();
    expect(screen.queryByText('청크 수')).not.toBeInTheDocument();
    expect(screen.queryByText('페이지 수')).not.toBeInTheDocument();
    expect(screen.queryByText('단어 수')).not.toBeInTheDocument();
  });

  it('카운트가 undefined여도 행을 숨깁니다', () => {
    const noCountDoc = createMockDocument({
      chunks: undefined,
      metadata: {},
    });
    render(<DocumentDetailDialog {...defaultProps} document={noCountDoc} />);

    expect(screen.queryByText('청크 수')).not.toBeInTheDocument();
    expect(screen.queryByText('페이지 수')).not.toBeInTheDocument();
    expect(screen.queryByText('단어 수')).not.toBeInTheDocument();
  });
});
