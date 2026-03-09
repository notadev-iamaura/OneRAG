/**
 * DocumentGridView 컴포넌트 테스트
 *
 * 그리드 형태 문서 카드 렌더링, 선택 상태 표시, 액션 버튼을 검증합니다.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { DocumentGridView } from '../DocumentGridView';
import type { Document } from '../../../types';

/** 테스트용 문서 데이터 팩토리 */
const createMockDocument = (overrides: Partial<Document> = {}): Document => ({
  id: 'doc-1',
  filename: 'test.pdf',
  originalName: 'test-original.pdf',
  size: 2048,
  mimeType: 'application/pdf',
  uploadedAt: '2026-01-15T10:30:00Z',
  status: 'completed',
  chunks: 10,
  ...overrides,
});

describe('DocumentGridView', () => {
  const defaultProps = {
    documents: [] as Document[],
    selectedDocuments: new Set<string>(),
    onToggleSelect: vi.fn(),
    onViewDetails: vi.fn(),
    onDownload: vi.fn(),
    onDeleteSingle: vi.fn(),
  };

  it('문서 카드를 렌더링합니다', () => {
    const doc = createMockDocument();
    render(<DocumentGridView {...defaultProps} documents={[doc]} />);
    expect(screen.getByText('test-original.pdf')).toBeInTheDocument();
    expect(screen.getByText('2 KB')).toBeInTheDocument();
    expect(screen.getByText(/10 Chunks/)).toBeInTheDocument();
  });

  it('여러 문서 카드를 렌더링합니다', () => {
    const docs = [
      createMockDocument({ id: 'doc-1', originalName: '문서A.pdf' }),
      createMockDocument({ id: 'doc-2', originalName: '문서B.xlsx' }),
    ];
    render(<DocumentGridView {...defaultProps} documents={docs} />);
    expect(screen.getByText('문서A.pdf')).toBeInTheDocument();
    expect(screen.getByText('문서B.xlsx')).toBeInTheDocument();
  });

  it('체크박스 클릭 시 onToggleSelect를 호출합니다', () => {
    const onToggleSelect = vi.fn();
    const doc = createMockDocument();
    render(<DocumentGridView {...defaultProps} documents={[doc]} onToggleSelect={onToggleSelect} />);
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);
    expect(onToggleSelect).toHaveBeenCalledWith('doc-1');
  });

  it('상세 버튼 클릭 시 onViewDetails를 호출합니다', () => {
    const onViewDetails = vi.fn();
    const doc = createMockDocument();
    render(<DocumentGridView {...defaultProps} documents={[doc]} onViewDetails={onViewDetails} />);
    fireEvent.click(screen.getByText('상세'));
    expect(onViewDetails).toHaveBeenCalledWith(doc);
  });

  it('받기 버튼 클릭 시 onDownload를 호출합니다', () => {
    const onDownload = vi.fn();
    const doc = createMockDocument();
    render(<DocumentGridView {...defaultProps} documents={[doc]} onDownload={onDownload} />);
    fireEvent.click(screen.getByText('받기'));
    expect(onDownload).toHaveBeenCalledWith(doc);
  });

  it('삭제 버튼 클릭 시 onDeleteSingle을 호출합니다', () => {
    const onDeleteSingle = vi.fn();
    const doc = createMockDocument();
    render(<DocumentGridView {...defaultProps} documents={[doc]} onDeleteSingle={onDeleteSingle} />);
    fireEvent.click(screen.getByText('삭제'));
    expect(onDeleteSingle).toHaveBeenCalledWith('doc-1');
  });

  it('유효하지 않은 문서 ID의 삭제 버튼은 비활성화됩니다', () => {
    const doc = createMockDocument({ id: 'temp-999' });
    render(<DocumentGridView {...defaultProps} documents={[doc]} />);
    const deleteButton = screen.getByText('삭제');
    expect(deleteButton).toBeDisabled();
  });
});
