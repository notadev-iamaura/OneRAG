import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ChatTab } from '../../ChatTab';
import * as useChatSessionHook from '../../../hooks/chat/useChatSession';
import * as useChatMessagesHook from '../../../hooks/chat/useChatMessages';
import * as useChatDevToolsHook from '../../../hooks/chat/useChatDevTools';
import { TooltipProvider } from '@/components/ui/tooltip';

// Mock useFeature
vi.mock('../../../core/useFeature', () => ({
    useFeature: vi.fn().mockReturnValue({ maskPhoneNumbers: true }),
}));

// Describe the mock types for better TS support (optional but good)
const mockUseChatSession = {
    sessionId: 'test-session',
    isSessionInitialized: true,
    synchronizeSessionId: vi.fn(),
    switchSession: vi.fn(),
    handleNewSession: vi.fn(),
};

const mockUseChatMessages: ReturnType<typeof useChatMessagesHook.useChatMessages> = {
    messages: [],
    setMessages: vi.fn(),
    input: '',
    setInput: vi.fn(),
    loading: false,
    setLoading: vi.fn(),
    handleSend: vi.fn(),
    handleStop: vi.fn(),
    isStreaming: false,
    streamingMessage: null,
    isStreamingEnabled: false,
    isStreamingConnected: false,
    isSseStreaming: false,
    ragProgress: { phase: 'idle', label: '' },
};

const mockUseChatDevTools = {
    apiLogs: [],
    setApiLogs: vi.fn(),
    leftPanelTab: 0,
    setLeftPanelTab: vi.fn(),
    expandedLogs: new Set(),
    setExpandedLogs: vi.fn(),
    isDebugExpanded: false,
    setIsDebugExpanded: vi.fn(),
    showDevTools: false,
    setShowDevTools: vi.fn(),
    toggleLogExpansion: vi.fn(),
    clearLogs: vi.fn(),
};

describe('ChatTab Integration', () => {
    beforeEach(() => {
        vi.spyOn(useChatSessionHook, 'useChatSession').mockReturnValue(mockUseChatSession as ReturnType<typeof useChatSessionHook.useChatSession>);
        vi.spyOn(useChatMessagesHook, 'useChatMessages').mockReturnValue(mockUseChatMessages);
        vi.spyOn(useChatDevToolsHook, 'useChatDevTools').mockReturnValue(mockUseChatDevTools as ReturnType<typeof useChatDevToolsHook.useChatDevTools>);
    });

    const defaultProps = {
        showToast: vi.fn(),
    };

    const renderWithContext = (element: React.ReactElement) => {
        return render(
            <TooltipProvider>
                {element}
            </TooltipProvider>
        );
    };

    it('renders key child components', () => {
        renderWithContext(<ChatTab {...defaultProps} />);

        // Check for Header text
        expect(screen.getByText('OneRAG Chat')).toBeInTheDocument();

        // Check for Input placeholder
        expect(screen.getByPlaceholderText('메시지를 입력하세요...')).toBeInTheDocument();
    });

    it('passes handlers to child components', () => {
        renderWithContext(<ChatTab {...defaultProps} />);

        // Simulate input change
        const input = screen.getByPlaceholderText('메시지를 입력하세요...');
        fireEvent.change(input, { target: { value: 'Hello' } });

        // Calls setInput from the hook
        expect(mockUseChatMessages.setInput).toHaveBeenCalledWith('Hello');
    });

    it('shows dev tools when enabled', () => {
        vi.spyOn(useChatDevToolsHook, 'useChatDevTools').mockReturnValue({
            ...mockUseChatDevTools,
            showDevTools: true,
        } as ReturnType<typeof useChatDevToolsHook.useChatDevTools>);

        renderWithContext(<ChatTab {...defaultProps} />);

        // Check for DevTools header
        expect(screen.getByText('개발자 도구')).toBeInTheDocument();
    });
});
