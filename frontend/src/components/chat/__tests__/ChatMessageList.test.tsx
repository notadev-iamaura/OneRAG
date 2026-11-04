import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ChatMessageList } from '../ChatMessageList';
import { ChatMessage } from '../../../types';

vi.mock('../ChatMessageItem', () => ({
    ChatMessageItem: ({ message }: { message: ChatMessage }) => <div data-testid="message-item">{message.content}</div>
}));

vi.mock('../../ChatEmptyState', () => ({
    ChatEmptyState: ({ onSuggestionClick }: { onSuggestionClick: (suggestion: string) => void }) => (
        <div data-testid="empty-state">
            <button onClick={() => onSuggestionClick('suggest')}>Suggestion</button>
        </div>
    )
}));

describe('ChatMessageList', () => {
    const mockCopyToClipboard = vi.fn();
    const mockOnChunkClick = vi.fn();
    const mockOnSuggestionClick = vi.fn();
    const mockHandleScroll = vi.fn();
    const mockScrollToBottom = vi.fn();
    const messagesEndRef = { current: null };

    const defaultProps = {
        messages: [] as ChatMessage[],
        loading: false,
        messageAnimations: new Set<string>(),
        copyToClipboard: mockCopyToClipboard,
        onChunkClick: mockOnChunkClick,
        onSuggestionClick: mockOnSuggestionClick,
        messagesEndRef: messagesEndRef as unknown as React.MutableRefObject<HTMLDivElement | null>,
        showScrollButton: false,
        handleScroll: mockHandleScroll,
        scrollToBottom: mockScrollToBottom,
    };

    it('should render empty state when no messages and not loading', () => {
        render(<ChatMessageList {...defaultProps} />);
        expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    });

    it('should handle suggestion click in empty state', () => {
        render(<ChatMessageList {...defaultProps} />);
        fireEvent.click(screen.getByText('Suggestion'));
        expect(mockOnSuggestionClick).toHaveBeenCalledWith('suggest');
    });

    it('should render messages', () => {
        const messages = [{ id: '1', content: 'msg1', role: 'user', timestamp: 'now' }] as ChatMessage[];
        render(<ChatMessageList {...defaultProps} messages={messages} />);
        expect(screen.getByTestId('message-item')).toHaveTextContent('msg1');
        expect(screen.queryByTestId('empty-state')).not.toBeInTheDocument();
    });

    it('should render loading indicator', () => {
        const messages = [{ id: '1', content: 'msg1', role: 'user', timestamp: 'now' }] as ChatMessage[];
        render(<ChatMessageList {...defaultProps} loading={true} messages={messages} />);
        expect(screen.getByText('답변을 생성하고 있습니다...')).toBeInTheDocument();
    });

    it('should show scroll button if showScrollButton is true', () => {
        render(<ChatMessageList {...defaultProps} showScrollButton={true} />);
        const scrollBtn = screen.getByLabelText('맨 아래로 이동');
        expect(scrollBtn).toBeInTheDocument();
        fireEvent.click(scrollBtn);
        expect(mockScrollToBottom).toHaveBeenCalled();
    });
});

