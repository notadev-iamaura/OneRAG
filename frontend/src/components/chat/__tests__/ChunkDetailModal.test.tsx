import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ChunkDetailModal } from '../ChunkDetailModal';
import { Source } from '../../types/chat';

// Mock formatFullContent to avoiding parsing issues in component tests
vi.mock('../../../utils/chat/formatters', () => ({
    formatFullContent: vi.fn((text) => `Formatted: ${text}`),
}));

describe('ChunkDetailModal', () => {
    const mockOnClose = vi.fn();
    const mockChunk: Source = {
        id: 1,
        document: 'doc.pdf',
        content_preview: 'Content Check',
        relevance: 0.9,
    };

    const defaultProps = {
        open: true,
        onClose: mockOnClose,
        selectedChunk: mockChunk as Source,
        documentInfoItems: [],
    };

    it('should render modal content when open', () => {
        render(<ChunkDetailModal {...defaultProps} />);
        expect(screen.getByText('RAG 참고 자료 상세')).toBeInTheDocument();
        expect(screen.getByText(/Formatted: Content Check/)).toBeInTheDocument();
    });

    it('should not render when open is false', () => {
        render(<ChunkDetailModal {...defaultProps} open={false} />);
        // Dialog hidden. With Shadcn/UI Dialog, it often renders nothing or hidden div. 
        // queryByText should return null for visible content usually.
        expect(screen.queryByText('RAG 참고 자료 상세')).not.toBeInTheDocument();
    });

    it('should call onClose when close button or close action clicked', () => {
        render(<ChunkDetailModal {...defaultProps} />);

        // Find by text since it's a button with text "닫기"
        const closeBtn = screen.getByText('닫기');
        fireEvent.click(closeBtn);
        expect(mockOnClose).toHaveBeenCalled();
    });

    it('should render document info items', () => {
        render(<ChunkDetailModal {...defaultProps} documentInfoItems={[{ label: 'Type', value: 'PDF' }]} />);
        expect(screen.getByText('Type')).toBeInTheDocument();
        expect(screen.getByText('PDF')).toBeInTheDocument();
    });

    it('should show fallback if no document info', () => {
        render(<ChunkDetailModal {...defaultProps} documentInfoItems={[]} />);
        expect(screen.getByText('문서 정보를 불러올 수 없습니다.')).toBeInTheDocument();
    });
});
