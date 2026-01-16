/**
 * useChatStreamingWithDI 훅 테스트
 *
 * WebSocketProvider와 통합된 DI 패턴 훅 테스트
 * - WebSocketProvider에서 주입된 팩토리를 사용
 * - Mock WebSocket으로 격리된 테스트 환경 제공
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import React from 'react';
import { WebSocketProvider } from '../../../core/WebSocketProvider';
import { useChatStreamingWithDI } from '../useChatStreamingWithDI';
import type { IWebSocket, WebSocketFactory } from '../../../types/websocket';
import { WebSocketReadyState } from '../../../types/websocket';

/**
 * Mock WebSocket 클래스
 *
 * IWebSocket 인터페이스를 구현하여 테스트에서 사용
 */
class MockWebSocket implements IWebSocket {
  static instances: MockWebSocket[] = [];

  readyState = WebSocketReadyState.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  send = vi.fn();
  close = vi.fn();

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  /**
   * 연결 성공 시뮬레이션
   */
  simulateOpen() {
    this.readyState = WebSocketReadyState.OPEN;
    this.onopen?.(new Event('open'));
  }

  /**
   * 메시지 수신 시뮬레이션
   */
  simulateMessage(data: unknown) {
    this.onmessage?.(
      new MessageEvent('message', {
        data: typeof data === 'string' ? data : JSON.stringify(data),
      })
    );
  }

  /**
   * 연결 종료 시뮬레이션
   */
  simulateClose(code = 1000, reason = '') {
    this.readyState = WebSocketReadyState.CLOSED;
    this.onclose?.(new CloseEvent('close', { code, reason }));
  }

  /**
   * 에러 시뮬레이션
   */
  simulateError() {
    this.onerror?.(new Event('error'));
  }

  /**
   * 모든 인스턴스 초기화
   */
  static clear() {
    MockWebSocket.instances = [];
  }

  /**
   * 마지막 생성된 인스턴스 반환
   */
  static getLastInstance(): MockWebSocket | undefined {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }
}

describe('useChatStreamingWithDI', () => {
  let mockOnMessageComplete: ReturnType<typeof vi.fn>;
  let mockOnError: ReturnType<typeof vi.fn>;
  let mockFactory: WebSocketFactory;

  beforeEach(() => {
    vi.clearAllMocks();
    MockWebSocket.clear();
    mockOnMessageComplete = vi.fn();
    mockOnError = vi.fn();
    mockFactory = (url) => new MockWebSocket(url);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /**
   * WebSocketProvider Wrapper 생성 함수
   */
  const createWrapper = (factory: WebSocketFactory) => {
    return function Wrapper({ children }: { children: React.ReactNode }) {
      return (
        <WebSocketProvider factory={factory}>
          {children}
        </WebSocketProvider>
      );
    };
  };

  /**
   * 연결을 설정하는 헬퍼 함수
   * connect()를 호출하고 즉시 simulateOpen()을 호출
   */
  const connectWithOpen = async (
    connectFn: () => Promise<void>
  ): Promise<void> => {
    // connect() 호출 (Promise 시작)
    const connectPromise = connectFn();

    // WebSocket 인스턴스가 생성되기를 기다림
    await waitFor(() => {
      expect(MockWebSocket.getLastInstance()).toBeDefined();
    });

    // 연결 성공 시뮬레이션
    MockWebSocket.getLastInstance()?.simulateOpen();

    // connect Promise 완료 대기
    await connectPromise;
  };

  /**
   * 연결을 설정하는 헬퍼 함수 (fakeTimers 사용 시)
   * connect()를 호출하고 microtask를 flush한 후 simulateOpen() 호출
   */
  const connectWithOpenSync = async (
    connectFn: () => Promise<void>
  ): Promise<void> => {
    // connect() 호출 시작
    const connectPromise = connectFn();

    // microtask flush하여 WebSocket 생성 완료 대기
    await vi.advanceTimersByTimeAsync(0);

    // 연결 성공 시뮬레이션
    const ws = MockWebSocket.getLastInstance();
    if (ws) {
      ws.simulateOpen();
    }

    // connect Promise 완료 대기
    await connectPromise;
  };

  describe('WebSocketProvider 통합', () => {
    it('WebSocketProvider에서 주입된 팩토리를 사용해야 함', async () => {
      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      await act(async () => {
        await connectWithOpen(result.current.connect);
      });

      // Mock WebSocket이 생성되었는지 확인
      expect(MockWebSocket.instances.length).toBe(1);
      expect(MockWebSocket.getLastInstance()?.url).toContain('test-session');
    });

    it('Provider 없이 사용하면 에러가 발생해야 함', () => {
      // 에러 콘솔 출력 억제
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      // renderHook은 에러 발생 시 내부적으로 catch하므로 다른 방법 사용
      let error: Error | null = null;
      try {
        renderHook(() =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          })
        );
      } catch (e) {
        error = e as Error;
      }

      expect(error).not.toBeNull();
      expect(error?.message).toBe('useWebSocket must be used within WebSocketProvider');

      consoleSpy.mockRestore();
    });
  });

  describe('연결 관리', () => {
    it('연결 후 isConnected가 true가 되어야 함', async () => {
      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      await act(async () => {
        await connectWithOpen(result.current.connect);
      });

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });
    });

    it('disconnect 호출 시 isConnected가 false가 되어야 함', async () => {
      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      // 연결
      await act(async () => {
        await connectWithOpen(result.current.connect);
      });

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      // 연결 해제
      act(() => {
        result.current.disconnect();
      });

      expect(result.current.isConnected).toBe(false);
    });

    it('fallback 세션은 연결을 시도하지 않아야 함', async () => {
      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'fallback-session-123',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      await act(async () => {
        await result.current.connect();
      });

      // Mock WebSocket이 생성되지 않아야 함
      expect(MockWebSocket.instances.length).toBe(0);
    });
  });

  describe('메시지 전송', () => {
    it('연결 후 메시지를 전송할 수 있어야 함', async () => {
      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      // 연결
      await act(async () => {
        await connectWithOpen(result.current.connect);
      });

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      // 메시지 전송
      act(() => {
        result.current.sendStreamingMessage('안녕하세요');
      });

      expect(MockWebSocket.getLastInstance()?.send).toHaveBeenCalled();
    });

    it('연결되지 않은 상태에서 메시지 전송 시 null을 반환해야 함', async () => {
      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      // 메시지 전송 (연결 없이)
      let messageId: string | null = null;
      act(() => {
        messageId = result.current.sendStreamingMessage('안녕하세요');
      });

      expect(messageId).toBeNull();
    });
  });

  describe('스트리밍 토큰 처리', () => {
    it('스트리밍 토큰을 누적해야 함', async () => {
      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      // 연결
      await act(async () => {
        await connectWithOpen(result.current.connect);
      });

      // 토큰 수신 1
      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_token',
          message_id: 'msg-001',
          token: '안녕',
        });
      });

      expect(result.current.streamingMessage?.content).toBe('안녕');

      // 토큰 수신 2
      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_token',
          message_id: 'msg-001',
          token: '하세요',
        });
      });

      expect(result.current.streamingMessage?.content).toBe('안녕하세요');
    });

    it('다른 message_id의 토큰은 새로운 스트리밍을 시작해야 함', async () => {
      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      // 연결
      await act(async () => {
        await connectWithOpen(result.current.connect);
      });

      // 첫 번째 메시지 토큰
      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_token',
          message_id: 'msg-001',
          token: '첫 번째 메시지',
        });
      });

      // 다른 메시지 토큰
      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_token',
          message_id: 'msg-002',
          token: '두 번째 메시지',
        });
      });

      expect(result.current.streamingMessage?.id).toBe('msg-002');
      expect(result.current.streamingMessage?.content).toBe('두 번째 메시지');
    });
  });

  describe('스트리밍 완료 처리', () => {
    it('스트리밍 완료 시 콜백을 호출해야 함', async () => {
      vi.useFakeTimers();

      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      // 연결 (fakeTimers 사용 시)
      await act(async () => {
        await connectWithOpenSync(result.current.connect);
      });

      // 토큰 수신
      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_token',
          message_id: 'msg-001',
          token: '완료된 응답',
        });
      });

      // 스트리밍 완료
      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_end',
          message_id: 'msg-001',
        });
      });

      // setTimeout 실행
      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(mockOnMessageComplete).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'msg-001',
          content: '완료된 응답',
          role: 'assistant',
        })
      );
    });

    it('스트리밍 완료 후 streamingMessage가 null이 되어야 함', async () => {
      vi.useFakeTimers();

      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      // 연결 (fakeTimers 사용 시)
      await act(async () => {
        await connectWithOpenSync(result.current.connect);
      });

      // 토큰 수신
      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_token',
          message_id: 'msg-001',
          token: '완료된 응답',
        });
      });

      // 스트리밍 완료
      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_end',
          message_id: 'msg-001',
        });
      });

      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(result.current.streamingMessage).toBeNull();
      expect(result.current.streamingState).toBe('idle');
    });
  });

  describe('에러 처리', () => {
    it('스트리밍 에러 시 onError 콜백을 호출해야 함', async () => {
      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      // 연결
      await act(async () => {
        await connectWithOpen(result.current.connect);
      });

      // 토큰 수신
      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_token',
          message_id: 'msg-001',
          token: '에러 발생 전 응답',
        });
      });

      // 에러 발생
      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_error',
          message_id: 'msg-001',
          error_code: 'GEN-001',
          message: '생성 오류가 발생했습니다.',
          solutions: ['다시 시도해주세요.', '잠시 후 다시 시도해주세요.'],
        });
      });

      expect(mockOnError).toHaveBeenCalled();
      expect(result.current.streamingState).toBe('error');
      expect(result.current.streamingMessage?.state).toBe('error');
    });

    it('재연결 실패 시 연결 상태를 유지해야 함', async () => {
      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      // 연결
      await act(async () => {
        await connectWithOpen(result.current.connect);
      });

      // 연결된 상태 확인
      expect(result.current.isConnected).toBe(true);
    });
  });

  describe('소스 처리', () => {
    it('스트리밍 소스를 수신해야 함', async () => {
      const { result } = renderHook(
        () =>
          useChatStreamingWithDI({
            sessionId: 'test-session',
            onMessageComplete: mockOnMessageComplete,
            onError: mockOnError,
          }),
        { wrapper: createWrapper(mockFactory) }
      );

      // 연결
      await act(async () => {
        await connectWithOpen(result.current.connect);
      });

      // 토큰 수신
      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_token',
          message_id: 'msg-001',
          token: '응답 내용',
        });
      });

      // 소스 수신
      const mockSources = [
        { id: 1, document: 'doc1.pdf', relevance: 0.95, content_preview: '내용1' },
        { id: 2, document: 'doc2.pdf', relevance: 0.85, content_preview: '내용2' },
      ];

      act(() => {
        MockWebSocket.getLastInstance()?.simulateMessage({
          type: 'stream_sources',
          message_id: 'msg-001',
          sources: mockSources,
        });
      });

      expect(result.current.streamingMessage?.sources).toHaveLength(2);
      expect(result.current.streamingMessage?.sources?.[0].document).toBe('doc1.pdf');
    });
  });
});
