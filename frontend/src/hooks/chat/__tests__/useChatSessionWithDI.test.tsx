/**
 * useChatSessionWithDI 훅 테스트
 *
 * DI 패턴을 사용하는 useChatSessionWithDI 훅의 동작을 검증합니다.
 * useChatAPIService()를 통해 주입받은 서비스로 세션을 관리합니다.
 */

import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useChatSessionWithDI } from '../useChatSessionWithDI';
import { ChatAPIProvider } from '../../../core/ChatAPIProvider';
import type { IChatAPIService } from '../../../types/chatAPI';
import type { ReactNode } from 'react';

// 실제 localStorage 동작을 위한 mock 구현
function createLocalStorageMock(): Storage {
  let store: Record<string, string> = {};

  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
    get length() {
      return Object.keys(store).length;
    },
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

describe('useChatSessionWithDI', () => {
  const defaultOptions = {
    showToast: vi.fn(),
    setMessages: vi.fn(),
    setApiLogs: vi.fn(),
    setSessionInfo: vi.fn(),
  };

  // 실제 동작하는 localStorage mock 설정
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

  const createWrapper = (mockService: IChatAPIService) => {
    return ({ children }: { children: ReactNode }) => (
      <ChatAPIProvider
        createService={() => mockService}
        config={{ baseURL: 'http://test', timeout: 1000 }}
      >
        {children}
      </ChatAPIProvider>
    );
  };

  describe('세션 초기화', () => {
    it('저장된 세션이 없으면 새 세션을 생성해야 함', async () => {
      // localStorage 비어있음 확인
      expect(localStorage.getItem('chatSessionId')).toBeNull();

      const mockService = createMockChatAPIService();

      const { result } = renderHook(
        () => useChatSessionWithDI(defaultOptions),
        { wrapper: createWrapper(mockService) }
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      expect(mockService.startNewSession).toHaveBeenCalled();
      expect(result.current.sessionId).toBe('new-session-123');
    });

    it('저장된 세션이 있으면 히스토리를 로드해야 함', async () => {
      // 복원 가능한 활성 세션(세션 ID + 생성 시각)을 저장해 TTL(30일) 검사를 통과시킨다.
      localStorage.setItem('chatSessionId', 'existing-session');
      localStorage.setItem('chatSessionCreatedAt', String(Date.now()));
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

      const { result } = renderHook(
        () => useChatSessionWithDI(defaultOptions),
        { wrapper: createWrapper(mockService) }
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

      const { result } = renderHook(
        () => useChatSessionWithDI(defaultOptions),
        { wrapper: createWrapper(mockService) }
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

      const { result } = renderHook(
        () => useChatSessionWithDI(defaultOptions),
        { wrapper: createWrapper(mockService) }
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

      const { result } = renderHook(
        () => useChatSessionWithDI(defaultOptions),
        { wrapper: createWrapper(mockService) }
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

      const { result } = renderHook(
        () => useChatSessionWithDI(defaultOptions),
        { wrapper: createWrapper(mockService) }
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      expect(result.current.sessionId).toMatch(/^fallback-/);
      expect(defaultOptions.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'warning' })
      );
    });

    it('히스토리 로드 실패 시에도 저장 세션을 폐기하지 않고 보존해야 함', async () => {
      // [대화방 소실 방지] 일시적 네트워크/5xx 등으로 히스토리 로드가 실패해도,
      // 백엔드 PostgreSQL에 멀쩡한 대화방이 있을 수 있으므로 세션을 유지한다.
      localStorage.setItem('chatSessionId', 'existing-session');
      localStorage.setItem('chatSessionCreatedAt', String(Date.now()));
      expect(localStorage.getItem('chatSessionId')).toBe('existing-session');

      const mockGetChatHistory = vi.fn().mockRejectedValue(new Error('History not found'));
      const mockStartNewSession = vi.fn().mockResolvedValue({
        data: { session_id: 'should-not-be-created' },
        status: 200,
      });

      const mockService = createMockChatAPIService({
        getChatHistory: mockGetChatHistory,
        startNewSession: mockStartNewSession,
      });

      const { result } = renderHook(
        () => useChatSessionWithDI(defaultOptions),
        { wrapper: createWrapper(mockService) }
      );

      await waitFor(() => {
        expect(result.current.isSessionInitialized).toBe(true);
      });

      // 히스토리 로드는 시도하되, 실패해도 새 세션을 생성하지 않고 기존 세션을 유지한다.
      expect(mockGetChatHistory).toHaveBeenCalledWith('existing-session');
      expect(mockStartNewSession).not.toHaveBeenCalled();
      expect(result.current.sessionId).toBe('existing-session');
      expect(localStorage.getItem('chatSessionId')).toBe('existing-session');
    });
  });

  describe('세션 동기화', () => {
    it('synchronizeSessionId가 세션 ID를 동기화해야 함', async () => {
      const mockService = createMockChatAPIService();

      const { result } = renderHook(
        () => useChatSessionWithDI(defaultOptions),
        { wrapper: createWrapper(mockService) }
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

      const { result } = renderHook(
        () => useChatSessionWithDI(defaultOptions),
        { wrapper: createWrapper(mockService) }
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

  describe('반환 타입', () => {
    it('기존 useChatSession과 동일한 반환 타입을 가져야 함', async () => {
      const mockService = createMockChatAPIService();

      const { result } = renderHook(
        () => useChatSessionWithDI(defaultOptions),
        { wrapper: createWrapper(mockService) }
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
