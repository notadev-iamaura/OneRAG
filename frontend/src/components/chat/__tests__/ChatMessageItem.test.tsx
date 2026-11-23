import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ChatMessageItem } from '../ChatMessageItem';
import { ChatMessage, Source as SourceType } from '../../../types';
import { TooltipProvider } from '@/components/ui/tooltip';

vi.mock('../../MarkdownRenderer', () => ({
    MarkdownRenderer: ({ content }: { content: string }) => <div data-testid="markdown">{content}</div>
}));

vi.mock('../../../utils/chat/formatters', async (importOriginal) => ({
    ...await importOriginal<typeof import('../../../utils/chat/formatters')>(),
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

    it('displays a normalized RAG score once on the correct badge scale', () => {
        const source = { ...botMessage.sources![0]!, relevance: 33.9, relevance_unit: 'percent' as const };
        renderWithContext(<ChatMessageItem message={{ ...botMessage, sources: [source] }} isAnimated={false} copyToClipboard={mockCopyToClipboard} onChunkClick={mockOnChunkClick} />);
        fireEvent.click(screen.getByText(/참고한 문서/));
        expect(screen.getByText('33.9%')).toHaveClass('text-slate-600');
    });

    it('should call onChunkClick when source is clicked', () => {
        renderWithContext(<ChatMessageItem message={botMessage} isAnimated={true} copyToClipboard={mockCopyToClipboard} onChunkClick={mockOnChunkClick} />);
        const trigger = screen.getByText(/참고한 문서/);
        fireEvent.click(trigger);

        const sourceItem = screen.getByText(/doc\.pdf/);
        fireEvent.click(sourceItem.closest('button')!);
        expect(mockOnChunkClick).toHaveBeenCalled();
    });

    it('shows each supported claim with its original sentence', () => {
        const source = { ...botMessage.sources![0]!, additional_metadata: { citations: [
            { sentence: 2, claim: 'Friday', quote: 'Orders close on Friday.' },
            { sentence: 5, claim: 'Monday', quote: 'Dispatch resumes on Monday.' },
        ] } };
        renderWithContext(<ChatMessageItem message={{ ...botMessage, sources: [source] }} isAnimated={true}
            copyToClipboard={mockCopyToClipboard} onChunkClick={mockOnChunkClick} />);
        fireEvent.click(screen.getByText(/참고한 문서/));
        for (const citation of source.additional_metadata.citations) {
            expect(screen.getByText(citation.claim)).toBeInTheDocument();
            expect(screen.getByText(citation.quote)).toBeInTheDocument();
        }
    });

    it('should render copy button for assistant message and handle click', () => {
        renderWithContext(<ChatMessageItem message={botMessage} isAnimated={true} copyToClipboard={mockCopyToClipboard} onChunkClick={mockOnChunkClick} />);
        const copyBtn = screen.getByLabelText('답변 복사');
        fireEvent.click(copyBtn);
        expect(mockCopyToClipboard).toHaveBeenCalledWith('Hi there', expect.any(String));
    });
});

