import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { ChatDevTools } from '../ChatDevTools';
import { SessionInfo, ApiLog } from '../../../types';
import { TooltipProvider } from '@/components/ui/tooltip';

describe('ChatDevTools', () => {
    const mockSetShowDevTools = vi.fn();
    const mockSetLeftPanelTab = vi.fn();
    const mockToggleLogExpansion = vi.fn();
    const mockSetIsDebugExpanded = vi.fn();
    const mockHandleNewSession = vi.fn();
    const mockCopyToClipboard = vi.fn();

    const mockSessionInfo: SessionInfo = {
        session_id: 'sess-1',
        messageCount: 5,
        tokensUsed: 100,
        processingTime: 1.2,
        timestamp: 'now',
        modelInfo: {
            provider: 'OpenAI',
            model: 'GPT-4',
            generation_time: 0.5
        }
    };

    const mockApiLogs: ApiLog[] = [
        { id: '1', timestamp: '2024-01-01T10:00:00Z', type: 'request', method: 'GET', endpoint: '/api/test', data: {} },
        { id: '2', timestamp: '2024-01-01T10:00:01Z', type: 'response', method: 'GET', endpoint: '/api/test', data: {}, status: 200 }
    ];

    const defaultProps = {
        showDevTools: true,
        setShowDevTools: mockSetShowDevTools,
        leftPanelTab: 0,
        setLeftPanelTab: mockSetLeftPanelTab,
        sessionId: 'sess-1',
        sessionInfo: mockSessionInfo,
        apiLogs: mockApiLogs,
        expandedLogs: new Set<string>(),
        toggleLogExpansion: mockToggleLogExpansion,
        isDebugExpanded: false,
        setIsDebugExpanded: mockSetIsDebugExpanded,
        handleNewSession: mockHandleNewSession,
        copyToClipboard: mockCopyToClipboard,
    };

    const renderWithContext = (element: React.ReactElement) => {
        return render(
            <TooltipProvider>
                {element}
            </TooltipProvider>
        );
    };

    it('should return null if showDevTools is false', () => {
        const { container } = renderWithContext(<ChatDevTools {...defaultProps} showDevTools={false} />);
        expect(container).toBeEmptyDOMElement();
    });

    it('should render session info correctly in tab 0', () => {
        renderWithContext(<ChatDevTools {...defaultProps} leftPanelTab={0} />);
        expect(screen.getByText('현재 세션')).toBeInTheDocument();
        expect(screen.getByText('sess-1')).toBeInTheDocument();
        expect(screen.getByText('GPT-4')).toBeInTheDocument();
    });

    it('should render API logs in tab 1', async () => {
        renderWithContext(<ChatDevTools {...defaultProps} leftPanelTab={1} />);
        expect(await screen.findByText('REQ')).toBeInTheDocument();
        expect(screen.getByText('RES 200')).toBeInTheDocument();
    });

    it('should show empty state for API logs if empty', () => {
        renderWithContext(<ChatDevTools {...defaultProps} leftPanelTab={1} apiLogs={[]} />);
        expect(screen.getByText('API 호출 내역이 없습니다.')).toBeInTheDocument();
    });

    it('should call handleNewSession on button click', () => {
        renderWithContext(<ChatDevTools {...defaultProps} leftPanelTab={0} />);
        const button = screen.getByText('새 세션 시작');
        fireEvent.click(button);
        expect(mockHandleNewSession).toHaveBeenCalled();
    });

    it('should switch tabs', async () => {
        const user = userEvent.setup();
        renderWithContext(<ChatDevTools {...defaultProps} />);
        const logsTab = screen.getByRole('tab', { name: /API 로그/i });
        await user.click(logsTab);
        expect(mockSetLeftPanelTab).toHaveBeenCalledWith(1);
    });

    it('should copy log on click', () => {
        renderWithContext(<ChatDevTools {...defaultProps} leftPanelTab={1} />);
        const copyButton = screen.getAllByLabelText('로그 복사')[0];
        if (!copyButton) throw new Error('로그 복사 버튼을 찾을 수 없습니다');
        fireEvent.click(copyButton);
        expect(mockCopyToClipboard).toHaveBeenCalled();
    });
});


