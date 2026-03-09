/**
 * DocumentListView 컴포넌트 테스트
 *
 * 테이블 형태의 문서 목록 렌더링, 체크박스 선택, 액션 버튼을 검증합니다.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { DocumentListView } from '../DocumentListView';
import type { Document } from '../../../types';

/** 테스트용 문서 데이터 팩토리 */
const createMockDocument = (overrides: Partial<Document> = {}): Document => ({
  id: 'doc-1',
  filename: 'test.pdf',
  originalName: 'test-original.pdf',
  size: 1024,
  mimeType: 'application/pdf',
  uploadedAt: '2026-01-15T10:30:00Z',
  status: 'completed',
  chunks: 5,
  ...overrides,
});

describe('DocumentListView', () => {
  const defaultProps = {
    documents: [] as Document[],
    selectedDocuments: new Set<string>(),
    onToggleSelect: vi.fn(),
    onToggleSelectAll: vi.fn(),
    onViewDetails: vi.fn(),
    onDownload: vi.fn(),
    onDeleteSingle: vi.fn(),
  };

  it('문서가 없을 때 테이블 헤더만 렌더링합니다', () => {
    render(<DocumentListView {...defaultProps} />);
    expect(screen.getByText('파일명')).toBeInTheDocument();
    expect(screen.getByText('크기')).toBeInTheDocument();
    expect(screen.getByText('업로드 일시')).toBeInTheDocument();
    expect(screen.getByText('상태')).toBeInTheDocument();
    expect(screen.getByText('액션')).toBeInTheDocument();
  });

  it('문서 행을 올바르게 렌더링합니다', () => {
    const doc = createMockDocument();
    render(<DocumentListView {...defaultProps} documents={[doc]} />);
    expect(screen.getByText('test-original.pdf')).toBeInTheDocument();
    expect(screen.getByText('1 KB')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
  });

  it('체크박스 선택 시 onToggleSelect를 호출합니다', () => {
    const onToggleSelect = vi.fn();
    const doc = createMockDocument();
    render(<DocumentListView {...defaultProps} documents={[doc]} onToggleSelect={onToggleSelect} />);
    // 문서 행의 체크박스 (두 번째 체크박스, 첫 번째는 전체 선택)
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[1]); // 개별 문서 체크박스
    expect(onToggleSelect).toHaveBeenCalledWith('doc-1');
  });

  it('전체 선택 체크박스 클릭 시 onToggleSelectAll을 호출합니다', () => {
    const onToggleSelectAll = vi.fn();
    const doc = createMockDocument();
    render(<DocumentListView {...defaultProps} documents={[doc]} onToggleSelectAll={onToggleSelectAll} />);
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[0]); // 전체 선택 체크박스
    expect(onToggleSelectAll).toHaveBeenCalled();
  });

  it('상세 보기 버튼 클릭 시 onViewDetails를 호출합니다', () => {
    const onViewDetails = vi.fn();
    const doc = createMockDocument();
    render(<DocumentListView {...defaultProps} documents={[doc]} onViewDetails={onViewDetails} />);
    const detailButton = screen.getByTestId('detail-button-doc-1');
    fireEvent.click(detailButton);
    expect(onViewDetails).toHaveBeenCalledWith(doc);
  });

  it('다운로드 버튼 클릭 시 onDownload를 호출합니다', () => {
    const onDownload = vi.fn();
    const doc = createMockDocument();
    render(<DocumentListView {...defaultProps} documents={[doc]} onDownload={onDownload} />);
    const downloadButton = screen.getByTestId('download-button-doc-1');
    fireEvent.click(downloadButton);
    expect(onDownload).toHaveBeenCalledWith(doc);
  });

  it('삭제 버튼 클릭 시 onDeleteSingle을 호출합니다', () => {
    const onDeleteSingle = vi.fn();
    const doc = createMockDocument();
    render(<DocumentListView {...defaultProps} documents={[doc]} onDeleteSingle={onDeleteSingle} />);
    const deleteButton = screen.getByTestId('delete-button-doc-1');
    fireEvent.click(deleteButton);
    expect(onDeleteSingle).toHaveBeenCalledWith('doc-1');
  });

  it('유효하지 않은 문서 ID의 삭제 버튼은 비활성화됩니다', () => {
    const doc = createMockDocument({ id: 'temp-123' });
    render(<DocumentListView {...defaultProps} documents={[doc]} />);
    const deleteButton = screen.getByTestId('delete-button-temp-123');
    expect(deleteButton).toBeDisabled();
  });
});
