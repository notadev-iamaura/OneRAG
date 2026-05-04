import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach, Mock } from 'vitest';
import { useChatMessages } from '../useChatMessages';
import { chatAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
    chatAPI: {
        sendMessage: vi.fn(),
        getSessionInfo: vi.fn(),
    },
}));

vi.mock('../../../core/useFeature', () => ({
    useIsFeatureEnabled: vi.fn(() => false),
}));

vi.mock('../../../utils/logger', () => ({
    logger: {
        log: vi.fn(),
        warn: vi.fn(),
        error: vi.fn(),
    },
}));

describe('useChatMessages', () => {
    const mockSessionId = 'test-session-id';
    const mockShowToast = vi.fn();
    const mockSynchronizeSessionId = vi.fn();
    const mockSetApiLogs = vi.fn();
    const mockSetSessionInfo = vi.fn();

    const defaultProps = {
        sessionId: mockSessionId,
        showToast: mockShowToast,
        synchronizeSessionId: mockSynchronizeSessionId,
        setApiLogs: mockSetApiLogs,
        setSessionInfo: mockSetSessionInfo,
    };

    beforeEach(() => {
        vi.clearAllMocks();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('should initialize with empty messages and input', () => {
        const { result } = renderHook(() => useChatMessages(defaultProps));

        expect(result.current.messages).toEqual([]);
        expect(result.current.input).toBe('');
        expect(result.current.loading).toBe(false);
    });

    it('should update input state', () => {
        const { result } = renderHook(() => useChatMessages(defaultProps));

        act(() => {
            result.current.setInput('Hello');
        });

        expect(result.current.input).toBe('Hello');
    });

    it('should handle sending a message successfully', async () => {
        const mockResponse = {
            data: {
                session_id: mockSessionId,
                answer: 'Hello from AI',
                sources: [],
                tokens_used: 10,
                processing_time: 0.5,
                model_info: { provider: 'test', model: 'test-model' },
            },
            status: 200,
        };
        (chatAPI.sendMessage as Mock).mockResolvedValue(mockResponse);
        (chatAPI.getSessionInfo as Mock).mockResolvedValue({ data: {} });

        const { result } = renderHook(() => useChatMessages(defaultProps));

        act(() => {
            result.current.setInput('Hi there');
        });

        await act(async () => {
            await result.current.handleSend();
        });

        const messages = result.current.messages;
        expect(messages).toHaveLength(2);
        expect(messages[0].role).toBe('user');
        expect(messages[0].content).toBe('Hi there');
        expect(messages[1].role).toBe('assistant');
        expect(messages[1].content).toBe('Hello from AI');

        expect(chatAPI.sendMessage).toHaveBeenCalledWith('Hi there', mockSessionId);
        expect(mockSynchronizeSessionId).toHaveBeenCalledWith(mockSessionId, expect.any(String));
        expect(mockSetApiLogs).toHaveBeenCalledTimes(2); // request + response
        expect(result.current.loading).toBe(false);
        expect(result.current.input).toBe('');
    });

    it('should handle send message failure', async () => {
        const errorMessage = 'API Error';
        (chatAPI.sendMessage as Mock).mockRejectedValue(new Error(errorMessage));

        const { result } = renderHook(() => useChatMessages(defaultProps));

        act(() => {
            result.current.setInput('Fail me');
        });

        await act(async () => {
            await result.current.handleSend();
        });

        expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({
            type: 'error',
            message: '메시지 전송에 실패했습니다.',
        }));

        const messages = result.current.messages;
        expect(messages).toHaveLength(2); // User message + Error message
        expect(messages[1].role).toBe('assistant');
        expect(messages[1].content).toContain('죄송합니다. 오류가 발생했습니다');
        expect(result.current.loading).toBe(false);
    });

    it('should prevent sending empty messages or when loading', async () => {
        const { result } = renderHook(() => useChatMessages(defaultProps));

        // Case 1: Empty input
        await act(async () => {
            await result.current.handleSend();
        });
        expect(chatAPI.sendMessage).not.toHaveBeenCalled();

        // Case 2: Loading state
        act(() => {
            result.current.setLoading(true);
            result.current.setInput('Should not send');
        });

        await act(async () => {
            await result.current.handleSend();
        });
        expect(chatAPI.sendMessage).not.toHaveBeenCalled();
    });
});
