import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ChatMessageItem } from '../ChatMessageItem';
import { ChatMessage, Source as SourceType } from '../../../types';
import { TooltipProvider } from '@/components/ui/tooltip';

vi.mock('../../MarkdownRenderer', () => ({
    MarkdownRenderer: ({ content }: { content: string }) => <div data-testid="markdown">{content}</div>
}));

vi.mock('../../../utils/chat/formatters', () => ({
    formatSourcePreview: (text: string) => text,
    formatTimestamp: () => '10:00 AM'
}));

describe('ChatMessageItem', () => {
    const mockCopyToClipboard = vi.fn();
    const mockOnChunkClick = vi.fn();
    const userMessage: ChatMessage = {
        id: '1', role: 'user', content: 'Hello', timestamp: 'now'
    };
    const botMessage: ChatMessage = {
        id: '2', role: 'assistant', content: 'Hi there', timestamp: 'now',
        sources: [{ id: 1, document: 'doc.pdf', relevance: 0.9, content_preview: 'preview' }] as unknown as SourceType[]
    };

    const renderWithContext = (element: React.ReactElement) => {
        return render(
            <TooltipProvider>
                {element}
            </TooltipProvider>
        );
    };

    it('should render user message correctly', () => {
        renderWithContext(<ChatMessageItem message={userMessage} isAnimated={true} copyToClipboard={mockCopyToClipboard} onChunkClick={mockOnChunkClick} />);
        expect(screen.getByText('Hello')).toBeInTheDocument();
    });

    it('should render assistant message with markdown', () => {
        renderWithContext(<ChatMessageItem message={botMessage} isAnimated={true} copyToClipboard={mockCopyToClipboard} onChunkClick={mockOnChunkClick} />);
        expect(screen.getByTestId('markdown')).toHaveTextContent('Hi there');
    });

    it('should show sources for assistant message if present', () => {
        renderWithContext(<ChatMessageItem message={botMessage} isAnimated={true} copyToClipboard={mockCopyToClipboard} onChunkClick={mockOnChunkClick} />);
        expect(screen.getByText(/참고한 문서/)).toBeInTheDocument();
    });

    it('should call onChunkClick when source is clicked', () => {
        renderWithContext(<ChatMessageItem message={botMessage} isAnimated={true} copyToClipboard={mockCopyToClipboard} onChunkClick={mockOnChunkClick} />);
        const trigger = screen.getByText(/참고한 문서/);
        fireEvent.click(trigger);

        const sourceItem = screen.getByText(/doc\.pdf/);
        fireEvent.click(sourceItem.closest('button')!);
        expect(mockOnChunkClick).toHaveBeenCalled();
    });

    it('should render copy button for assistant message and handle click', () => {
        renderWithContext(<ChatMessageItem message={botMessage} isAnimated={true} copyToClipboard={mockCopyToClipboard} onChunkClick={mockOnChunkClick} />);
        const copyBtn = screen.getByLabelText('답변 복사');
        fireEvent.click(copyBtn);
        expect(mockCopyToClipboard).toHaveBeenCalledWith('Hi there', expect.any(String));
    });
});

