/**
 * useChatSession 훅 테스트
 *
 * DI 패턴을 사용하는 useChatSession 훅의 동작을 검증합니다.
 * ChatAPIProvider를 통해 주입받은 서비스로 세션을 관리합니다.
 *
 * Note: 이 테스트는 useChatSessionCore.test.tsx와 동일한 로직을 검증하지만,
 * Provider 통합 레벨에서 테스트합니다.
 */

import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useChatSession } from '../useChatSession';
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

describe('useChatSession', () => {
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

  it('should initialize a new session if no session ID exists in localStorage', async () => {
    // localStorage 비어있음 확인
    expect(localStorage.getItem('chatSessionId')).toBeNull();

    const mockService = createMockChatAPIService();

    const { result } = renderHook(
      () => useChatSession(defaultOptions),
      { wrapper: createWrapper(mockService) }
    );

    await waitFor(() => {
      expect(result.current.isSessionInitialized).toBe(true);
    });

    expect(mockService.startNewSession).toHaveBeenCalled();
    expect(result.current.sessionId).toBe('new-session-123');
    expect(localStorage.getItem('chatSessionId')).toBe('new-session-123');
  });

  it('should restore an existing session from localStorage', async () => {
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
      () => useChatSession(defaultOptions),
      { wrapper: createWrapper(mockService) }
    );

    await waitFor(() => {
      expect(result.current.isSessionInitialized).toBe(true);
    });

    // 히스토리 로드 검증
    expect(mockGetChatHistory).toHaveBeenCalledWith('existing-session');
    expect(result.current.sessionId).toBe('existing-session');
    expect(mockService.startNewSession).not.toHaveBeenCalled();
  });

  it('should preserve the stored session instead of discarding it when history load fails', async () => {
    // [대화방 소실 방지] 히스토리 로드 실패를 세션 폐기로 승격하지 않는다.
    // 백엔드 PostgreSQL이 진실원본이며, 전송 시 같은 session_id로 복원된다.
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
      () => useChatSession(defaultOptions),
      { wrapper: createWrapper(mockService) }
    );

    await waitFor(() => {
      expect(result.current.isSessionInitialized).toBe(true);
    });

    // 히스토리 로드 실패 후에도 기존 세션을 유지하고 새 세션을 생성하지 않는다.
    expect(mockGetChatHistory).toHaveBeenCalledWith('existing-session');
    expect(mockStartNewSession).not.toHaveBeenCalled();
    expect(result.current.sessionId).toBe('existing-session');
    expect(localStorage.getItem('chatSessionId')).toBe('existing-session');
  });

  it('should start a new session when handleNewSession is called', async () => {
    const mockService = createMockChatAPIService();

    const { result } = renderHook(
      () => useChatSession(defaultOptions),
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

  it('should create a fallback session if backend is down during initialization', async () => {
    const mockService = createMockChatAPIService({
      startNewSession: vi.fn().mockRejectedValue(new Error('Network error')),
    });

    const { result } = renderHook(
      () => useChatSession(defaultOptions),
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
});
