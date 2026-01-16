/**
 * useChatSessionCore 훅 테스트
 *
 * Core 훅은 IChatAPIService를 직접 주입받아 세션을 관리합니다.
 * DI Context 없이 순수하게 주입받은 서비스로 동작합니다.
 */

import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useChatSessionCore } from '../useChatSessionCore';
import type { IChatAPIService } from '../../../types/chatAPI';

// localStorage mock
function createLocalStorageMock(): Storage {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
    get length() { return Object.keys(store).length; },
    key: (index: number) => Object.keys(store)[index] ?? null,
  };
}

// Mock 서비스 생성 헬퍼
function createMockChatAPIService(overrides?: Partial<IChatAPIService>): IChatAPIService {
  return {
    sendMessage: vi.fn().mockResolvedValue({
      data: { answer: 'mock answer', session_id: 'mock-session', sources: [] },
    }),
    getChatHistory: vi.fn().mockResolvedValue({
      data: { messages: [] },
    }),
    startNewSession: vi.fn().mockResolvedValue({
      data: { session_id: 'new-session-123' },
    }),
    getSessionInfo: vi.fn().mockResolvedValue({
      data: { session_id: 'mock-session', created_at: '2024-01-01', message_count: 0 },
    }),
    streamMessage: vi.fn(),
    ...overrides,
  };
}

describe('useChatSessionCore', () => {
  const defaultOptions = {
    showToast: vi.fn(),
    setMessages: vi.fn(),
    setApiLogs: vi.fn(),
    setSessionInfo: vi.fn(),
  };

  let mockLocalStorage: Storage;
  const originalLocalStorage = window.localStorage;

  beforeAll(() => {
    mockLocalStorage = createLocalStorageMock();
    Object.defineProperty(window, 'localStorage', {
      value: mockLocalStorage,
      writable: true,
      configurable: true,
    });
  });

  afterAll(() => {
    Object.defineProperty(window, 'localStorage', {
      value: originalLocalStorage,
      writable: true,
      configurable: true,
    });
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockLocalStorage.clear();
  });

  describe('서비스 주입', () => {
    it('주입받은 서비스로 새 세션을 생성해야 함', async () => {
      // localStorage 비어있음 확인
      expect(localStorage.getItem('chatSessionId')).toBeNull();

      const mockService = createMockChatAPIService();

      const { result } = renderHook(() =>
        useChatSessionCore(mockService, defaultOptions)
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      expect(mockService.startNewSession).toHaveBeenCalled();
      expect(result.current.sessionId).toBe('new-session-123');
    });

    it('주입받은 서비스로 히스토리를 로드해야 함', async () => {
      // 먼저 localStorage에 세션 ID 설정
      localStorage.setItem('chatSessionId', 'existing-session');
      expect(localStorage.getItem('chatSessionId')).toBe('existing-session');

      const mockGetChatHistory = vi.fn().mockResolvedValue({
        data: {
          messages: [
            { role: 'user', content: '안녕', timestamp: '2024-01-01', session_id: 'existing-session' },
          ],
        },
      });

      const mockService = createMockChatAPIService({
        getChatHistory: mockGetChatHistory,
      });

      const { result } = renderHook(() =>
        useChatSessionCore(mockService, defaultOptions)
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      // 히스토리 로드 검증
      expect(mockGetChatHistory).toHaveBeenCalledWith('existing-session');
      expect(result.current.sessionId).toBe('existing-session');
    });

    it('fallback 세션이 저장되어 있으면 새 세션을 생성해야 함', async () => {
      localStorage.setItem('chatSessionId', 'fallback-12345');
      expect(localStorage.getItem('chatSessionId')).toBe('fallback-12345');

      const mockService = createMockChatAPIService();

      const { result } = renderHook(() =>
        useChatSessionCore(mockService, defaultOptions)
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      expect(mockService.startNewSession).toHaveBeenCalled();
      expect(result.current.sessionId).toBe('new-session-123');
    });
  });

  describe('새 세션 시작', () => {
    it('handleNewSession이 새 세션을 생성해야 함', async () => {
      const mockService = createMockChatAPIService();

      const { result } = renderHook(() =>
        useChatSessionCore(mockService, defaultOptions)
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      // 첫 번째 호출은 초기화
      vi.clearAllMocks();

      await act(async () => {
        await result.current.handleNewSession();
      });

      expect(mockService.startNewSession).toHaveBeenCalled();
      expect(defaultOptions.setMessages).toHaveBeenCalledWith([]);
      expect(defaultOptions.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'success' })
      );
    });

    it('새 세션 생성 실패 시 fallback 세션을 사용해야 함', async () => {
      const mockService = createMockChatAPIService({
        startNewSession: vi.fn()
          .mockResolvedValueOnce({ data: { session_id: 'initial-session' } })
          .mockRejectedValueOnce(new Error('Network error')),
      });

      const { result } = renderHook(() =>
        useChatSessionCore(mockService, defaultOptions)
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      // 초기화 후 새 세션 시도
      vi.clearAllMocks();

      await act(async () => {
        await result.current.handleNewSession();
      });

      expect(result.current.sessionId).toMatch(/^fallback-/);
      expect(defaultOptions.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'warning' })
      );
    });
  });

  describe('에러 처리', () => {
    it('세션 생성 실패 시 fallback 세션을 사용해야 함', async () => {
      const mockService = createMockChatAPIService({
        startNewSession: vi.fn().mockRejectedValue(new Error('Network error')),
      });

      const { result } = renderHook(() =>
        useChatSessionCore(mockService, defaultOptions)
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      expect(result.current.sessionId).toMatch(/^fallback-/);
      expect(defaultOptions.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'warning' })
      );
    });

    it('히스토리 로드 실패 시 새 세션을 생성해야 함', async () => {
      localStorage.setItem('chatSessionId', 'existing-session');
      expect(localStorage.getItem('chatSessionId')).toBe('existing-session');

      const mockGetChatHistory = vi.fn().mockRejectedValue(new Error('History not found'));
      const mockStartNewSession = vi.fn().mockResolvedValue({
        data: { session_id: 'recovered-session' },
        status: 200,
      });

      const mockService = createMockChatAPIService({
        getChatHistory: mockGetChatHistory,
        startNewSession: mockStartNewSession,
      });

      const { result } = renderHook(() =>
        useChatSessionCore(mockService, defaultOptions)
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      // 히스토리 로드 실패 후 새 세션 생성
      expect(mockGetChatHistory).toHaveBeenCalledWith('existing-session');
      expect(mockStartNewSession).toHaveBeenCalled();
      expect(result.current.sessionId).toBe('recovered-session');
    });
  });

  describe('세션 동기화', () => {
    it('synchronizeSessionId가 세션 ID를 동기화해야 함', async () => {
      const mockService = createMockChatAPIService();

      const { result } = renderHook(() =>
        useChatSessionCore(mockService, defaultOptions)
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      // 초기 세션 ID 확인
      expect(result.current.sessionId).toBe('new-session-123');

      // 세션 동기화 실행
      let syncResult: boolean = false;
      act(() => {
        syncResult = result.current.synchronizeSessionId('synced-session', '테스트 동기화');
      });

      expect(syncResult).toBe(true);

      // 상태 업데이트 대기
      await waitFor(() => {
        expect(result.current.sessionId).toBe('synced-session');
      });

      expect(localStorage.getItem('chatSessionId')).toBe('synced-session');
    });

    it('동일한 세션 ID로 동기화 시 false를 반환해야 함', async () => {
      const mockService = createMockChatAPIService();

      const { result } = renderHook(() =>
        useChatSessionCore(mockService, defaultOptions)
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      const currentSessionId = result.current.sessionId;

      let syncResult: boolean = true;
      act(() => {
        syncResult = result.current.synchronizeSessionId(currentSessionId, '동일 세션');
      });

      expect(syncResult).toBe(false);
    });
  });

  describe('반환 타입 호환성', () => {
    it('기존 useChatSession과 동일한 반환 타입을 가져야 함', async () => {
      const mockService = createMockChatAPIService();

      const { result } = renderHook(() =>
        useChatSessionCore(mockService, defaultOptions)
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      // 반환 타입 검증
      expect(result.current).toHaveProperty('sessionId');
      expect(result.current).toHaveProperty('isSessionInitialized');
      expect(result.current).toHaveProperty('synchronizeSessionId');
      expect(result.current).toHaveProperty('handleNewSession');

      expect(typeof result.current.sessionId).toBe('string');
      expect(typeof result.current.isSessionInitialized).toBe('boolean');
      expect(typeof result.current.synchronizeSessionId).toBe('function');
      expect(typeof result.current.handleNewSession).toBe('function');
    });
  });
});
