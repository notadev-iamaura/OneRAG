import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useChatInteraction } from '../useChatInteraction';
import { useMediaQuery } from '../../useMediaQuery';
import { logger } from '../../../utils/logger';
import { chatAPI } from '../../../services/api';
import { ChatMessage, Source } from '../../../types';

// Mock dependencies
vi.mock('../../useMediaQuery', () => ({
    useMediaQuery: vi.fn(),
}));

vi.mock('../../../utils/logger', () => ({
    logger: {
        error: vi.fn(),
        warn: vi.fn(),
        log: vi.fn(),
    },
}));

// chatAPI.getSourceDetail mock (청크 상세 lazy 조회)
vi.mock('../../../services/api', () => ({
    chatAPI: {
        getSourceDetail: vi.fn(),
    },
}));

describe('useChatInteraction', () => {
    const mockShowToast = vi.fn();
    const mockMessages: ChatMessage[] = [{ id: '1', content: 'hello', role: 'user', timestamp: 'now' }];

    // Mock clipboard
    const mockWriteText = vi.fn();
    Object.defineProperty(navigator, 'clipboard', {
        value: {
            writeText: mockWriteText,
        },
        writable: true,
    });

    // Mock scrollIntoView
    const scrollIntoViewMock = vi.fn();

    beforeEach(() => {
        vi.clearAllMocks();
        // Reset window innerWidth for consistent tests
        Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1200 });

        // Mock matches to false by default
        vi.mocked(useMediaQuery).mockReturnValue(false);
    });

    it('should initialize with default states', () => {
        const { result } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));

        expect(result.current.modalOpen).toBe(false);
        expect(result.current.selectedChunk).toBeNull();
        expect(result.current.leftPanelTab).toBe(0);
        expect(result.current.isDebugExpanded).toBe(false);
        expect(result.current.showDevTools).toBe(true); // Window width 1200 >= 1024
    });

    it('should toggle dev tools based on screen size', () => {
        // Initial render with large screen
        const { result, rerender } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));
        expect(result.current.showDevTools).toBe(true);

        // Simulate medium screen
        vi.mocked(useMediaQuery).mockReturnValue(true);
        rerender();

        expect(result.current.showDevTools).toBe(false);
    });

    it('should handle chunk modal open/close', () => {
        const { result } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));
        const mockChunk = { id: 1, content_preview: 'test' } as unknown as Source;

        act(() => {
            result.current.handleChunkClick(mockChunk);
        });

        expect(result.current.modalOpen).toBe(true);
        expect(result.current.selectedChunk).toEqual(mockChunk);

        act(() => {
            result.current.handleCloseModal();
        });

        expect(result.current.modalOpen).toBe(false);
        expect(result.current.selectedChunk).toBeNull();
    });

    // #56: source_id/document_id가 있으면 전체 원문을 lazy 조회한다
    it('should lazy-fetch source detail when source has ids', async () => {
        const getSourceDetail = chatAPI.getSourceDetail as ReturnType<typeof vi.fn>;
        getSourceDetail.mockResolvedValue({
            data: { source_id: 's1', document_id: 'd1', full_content: '전체 원문 텍스트' },
        });

        const { result } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));
        const chunk = { id: 1, source_id: 's1', document_id: 'd1', content_preview: 'preview' } as unknown as Source;

        await act(async () => {
            await result.current.handleChunkClick(chunk);
        });

        expect(getSourceDetail).toHaveBeenCalledWith(chunk);
        expect(result.current.sourceDetail?.full_content).toBe('전체 원문 텍스트');
        expect(result.current.sourceDetailError).toBeNull();
        expect(result.current.sourceDetailLoading).toBe(false);
    });

    // #56: source_id/document_id가 없으면 API를 호출하지 않고 미리보기로 graceful 처리
    it('should skip lazy fetch when ids are missing', async () => {
        const getSourceDetail = chatAPI.getSourceDetail as ReturnType<typeof vi.fn>;
        const { result } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));
        const chunk = { id: 1, content_preview: 'preview-only' } as unknown as Source;

        await act(async () => {
            await result.current.handleChunkClick(chunk);
        });

        expect(getSourceDetail).not.toHaveBeenCalled();
        expect(result.current.sourceDetail).toBeNull();
        expect(result.current.sourceDetailLoading).toBe(false);
    });

    // #56: 상세 조회 실패 시 에러 메시지를 설정하되 모달은 유지(graceful degradation)
    it('should gracefully degrade when source detail fetch fails', async () => {
        const getSourceDetail = chatAPI.getSourceDetail as ReturnType<typeof vi.fn>;
        getSourceDetail.mockRejectedValue(new Error('404 not found'));

        const { result } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));
        const chunk = { id: 1, source_id: 's1', document_id: 'd1', content_preview: 'preview' } as unknown as Source;

        await act(async () => {
            await result.current.handleChunkClick(chunk);
        });

        expect(result.current.sourceDetail).toBeNull();
        expect(result.current.sourceDetailError).not.toBeNull();
        expect(result.current.modalOpen).toBe(true);
        expect(result.current.sourceDetailLoading).toBe(false);
    });

    // #56: 연속 클릭 시 늦게 도착한 이전 응답이 최신 청크 상세를 덮어쓰지 않아야 한다 (stale 가드)
    it('should ignore stale source detail responses on rapid clicks', async () => {
        const getSourceDetail = chatAPI.getSourceDetail as ReturnType<typeof vi.fn>;

        // 첫 클릭: 느린 응답, 두 번째 클릭: 빠른 응답
        let resolveSlow!: (value: { data: unknown }) => void;
        const slowPromise = new Promise<{ data: unknown }>((resolve) => { resolveSlow = resolve; });
        getSourceDetail
            .mockReturnValueOnce(slowPromise)
            .mockResolvedValueOnce({ data: { source_id: 's2', document_id: 'd2', full_content: '두 번째 청크 원문' } });

        const { result } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));
        const chunk1 = { id: 1, source_id: 's1', document_id: 'd1', content_preview: 'p1' } as unknown as Source;
        const chunk2 = { id: 2, source_id: 's2', document_id: 'd2', content_preview: 'p2' } as unknown as Source;

        // 첫 클릭(느린 응답 대기) → 두 번째 클릭(빠른 응답 완료)
        act(() => { void result.current.handleChunkClick(chunk1); });
        await act(async () => { await result.current.handleChunkClick(chunk2); });

        // 두 번째 응답이 반영되어야 한다.
        await waitFor(() => {
            expect(result.current.sourceDetail?.full_content).toBe('두 번째 청크 원문');
        });

        // 이제 첫 번째(느린) 응답이 늦게 도착해도 무시되어야 한다.
        await act(async () => {
            resolveSlow({ data: { source_id: 's1', document_id: 'd1', full_content: '첫 번째 청크 원문(stale)' } });
            await slowPromise;
        });

        expect(result.current.sourceDetail?.full_content).toBe('두 번째 청크 원문');
        expect(result.current.selectedChunk?.id).toBe(2);
    });

    it('should toggle log expansion', () => {
        const { result } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));
        const logId = 'log-1';

        act(() => {
            result.current.toggleLogExpansion(logId);
        });
        expect(result.current.expandedLogs.has(logId)).toBe(true);

        act(() => {
            result.current.toggleLogExpansion(logId);
        });
        expect(result.current.expandedLogs.has(logId)).toBe(false);
    });

    it('should copy text to clipboard successfully', async () => {
        const { result } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));
        mockWriteText.mockResolvedValue(undefined);

        await act(async () => {
            await result.current.copyToClipboard('text to copy');
        });

        expect(mockWriteText).toHaveBeenCalledWith('text to copy');
        expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }));
    });

    it('should handle clipboard error', async () => {
        const { result } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));
        mockWriteText.mockRejectedValue(new Error('Copy failed'));

        await act(async () => {
            await result.current.copyToClipboard('fail text');
        });

        expect(logger.error).toHaveBeenCalled();
        expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }));
    });

    it('should trigger scroll to bottom when messages change', () => {
        const { result } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));

        const mockDiv = document.createElement('div');
        mockDiv.scrollIntoView = scrollIntoViewMock;

        // Assign ref
        (result.current.messagesEndRef as React.MutableRefObject<HTMLDivElement | null>).current = mockDiv;

        act(() => {
            result.current.scrollToBottom();
        });

        expect(scrollIntoViewMock).toHaveBeenCalledWith({ behavior: 'smooth', block: 'end' });
    });

    it('should set initial devtools state based on window width', () => {
        Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 800 });
        const { result } = renderHook(() => useChatInteraction({ messages: mockMessages, showToast: mockShowToast }));
        expect(result.current.showDevTools).toBe(false);
    });
});
