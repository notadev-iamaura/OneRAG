/**
 * useChatStreamingCore 훅 테스트
 *
 * Core 훅: IChatWebSocketService를 직접 주입받아 스트리밍을 관리
 * - Context/Provider 없이 서비스를 직접 전달
 * - 격리된 단위 테스트 가능
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useChatStreamingCore } from '../useChatStreamingCore';
import type { IChatWebSocketService, WebSocketEventHandler } from '../../../services/createChatWebSocketService';

/**
 * Mock WebSocket 서비스 생성
 *
 * IChatWebSocketService 인터페이스를 구현하여 테스트에서 사용
 */
function createMockService(): IChatWebSocketService & {
  // 이벤트 시뮬레이션 헬퍼
  simulateEvent: (event: string, data: unknown) => void;
  // 연결 성공 시뮬레이션
  simulateConnect: () => void;
} {
  const listeners: Map<string, Set<WebSocketEventHandler>> = new Map();

  const service: IChatWebSocketService & {
    simulateEvent: (event: string, data: unknown) => void;
    simulateConnect: () => void;
  } = {
    connect: vi.fn().mockResolvedValue(undefined),
    disconnect: vi.fn(),
    sendMessage: vi.fn().mockReturnValue('generated-msg-id'),
    on: vi.fn((event: string, handler: WebSocketEventHandler) => {
      if (!listeners.has(event)) {
        listeners.set(event, new Set());
      }
      listeners.get(event)!.add(handler);
    }),
    off: vi.fn((event: string, handler: WebSocketEventHandler) => {
      listeners.get(event)?.delete(handler);
    }),
    // 이벤트 시뮬레이션 헬퍼
    simulateEvent: (event: string, data: unknown) => {
      listeners.get(event)?.forEach((handler) => handler(data));
    },
    // 연결 성공 시뮬레이션
    simulateConnect: () => {
      service.simulateEvent('connection', { connected: true });
    },
  };

  return service;
}

describe('useChatStreamingCore', () => {
  let mockService: ReturnType<typeof createMockService>;
  let mockOnMessageComplete: ReturnType<typeof vi.fn>;
  let mockOnError: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockService = createMockService();
    mockOnMessageComplete = vi.fn();
    mockOnError = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('초기 상태', () => {
    it('초기 상태가 올바르게 설정되어야 함', () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      expect(result.current.isConnected).toBe(false);
      expect(result.current.streamingState).toBe('idle');
      expect(result.current.streamingMessage).toBeNull();
    });

    it('서비스 이벤트 리스너가 등록되어야 함', () => {
      renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      // 이벤트 리스너 등록 확인
      expect(mockService.on).toHaveBeenCalledWith('connection', expect.any(Function));
      expect(mockService.on).toHaveBeenCalledWith('stream_start', expect.any(Function));
      expect(mockService.on).toHaveBeenCalledWith('stream_token', expect.any(Function));
      expect(mockService.on).toHaveBeenCalledWith('stream_sources', expect.any(Function));
      expect(mockService.on).toHaveBeenCalledWith('stream_end', expect.any(Function));
      expect(mockService.on).toHaveBeenCalledWith('stream_error', expect.any(Function));
      expect(mockService.on).toHaveBeenCalledWith('reconnect_failed', expect.any(Function));
    });
  });

  describe('연결 관리', () => {
    it('connect() 호출 시 서비스 connect()가 호출되어야 함', async () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      await act(async () => {
        await result.current.connect();
      });

      expect(mockService.connect).toHaveBeenCalledWith('test-session');
    });

    it('연결 성공 시 isConnected가 true가 되어야 함', async () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      await act(async () => {
        await result.current.connect();
        mockService.simulateConnect();
      });

      expect(result.current.isConnected).toBe(true);
    });

    it('disconnect() 호출 시 서비스 disconnect()가 호출되어야 함', async () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      // 연결
      await act(async () => {
        await result.current.connect();
        mockService.simulateConnect();
      });

      // 연결 해제
      act(() => {
        result.current.disconnect();
      });

      expect(mockService.disconnect).toHaveBeenCalled();
      expect(result.current.isConnected).toBe(false);
      expect(result.current.streamingState).toBe('idle');
      expect(result.current.streamingMessage).toBeNull();
    });

    it('세션 ID가 없으면 연결을 시도하지 않아야 함', async () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: '',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      await act(async () => {
        await result.current.connect();
      });

      expect(mockService.connect).not.toHaveBeenCalled();
    });

    it('fallback 세션은 연결을 시도하지 않아야 함', async () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'fallback-session-123',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      await act(async () => {
        await result.current.connect();
      });

      expect(mockService.connect).not.toHaveBeenCalled();
    });
  });

  describe('메시지 전송', () => {
    it('연결된 상태에서 메시지를 전송할 수 있어야 함', async () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      // 연결
      await act(async () => {
        await result.current.connect();
        mockService.simulateConnect();
      });

      // 메시지 전송
      let messageId: string | null = null;
      act(() => {
        messageId = result.current.sendStreamingMessage('안녕하세요');
      });

      expect(mockService.sendMessage).toHaveBeenCalledWith('안녕하세요');
      expect(messageId).toBe('generated-msg-id');
      expect(result.current.streamingState).toBe('streaming');
      expect(result.current.streamingMessage).toEqual({
        id: 'generated-msg-id',
        content: '',
        state: 'streaming',
      });
    });

    it('연결되지 않은 상태에서 메시지 전송 시 null을 반환해야 함', async () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      let messageId: string | null = null;
      act(() => {
        messageId = result.current.sendStreamingMessage('안녕하세요');
      });

      expect(messageId).toBeNull();
      expect(mockService.sendMessage).not.toHaveBeenCalled();
    });
  });

  describe('스트리밍 토큰 처리', () => {
    it('스트리밍 토큰을 누적해야 함', async () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      // 연결
      await act(async () => {
        await result.current.connect();
        mockService.simulateConnect();
      });

      // 토큰 수신 1
      act(() => {
        mockService.simulateEvent('stream_token', {
          message_id: 'msg-001',
          token: '안녕',
        });
      });

      expect(result.current.streamingMessage?.content).toBe('안녕');

      // 토큰 수신 2
      act(() => {
        mockService.simulateEvent('stream_token', {
          message_id: 'msg-001',
          token: '하세요',
        });
      });

      expect(result.current.streamingMessage?.content).toBe('안녕하세요');
    });

    it('다른 message_id의 토큰은 새로운 스트리밍을 시작해야 함', async () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      // 연결
      await act(async () => {
        await result.current.connect();
        mockService.simulateConnect();
      });

      // 첫 번째 메시지 토큰
      act(() => {
        mockService.simulateEvent('stream_token', {
          message_id: 'msg-001',
          token: '첫 번째 메시지',
        });
      });

      // 다른 메시지 토큰
      act(() => {
        mockService.simulateEvent('stream_token', {
          message_id: 'msg-002',
          token: '두 번째 메시지',
        });
      });

      expect(result.current.streamingMessage?.id).toBe('msg-002');
      expect(result.current.streamingMessage?.content).toBe('두 번째 메시지');
    });
  });

  describe('스트리밍 완료 처리', () => {
    it('스트리밍 완료 시 onMessageComplete 콜백을 호출해야 함', async () => {
      vi.useFakeTimers();

      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      // 연결
      await act(async () => {
        await result.current.connect();
        mockService.simulateConnect();
      });

      // 토큰 수신
      act(() => {
        mockService.simulateEvent('stream_token', {
          message_id: 'msg-001',
          token: '완료된 응답',
        });
      });

      // 스트리밍 완료
      act(() => {
        mockService.simulateEvent('stream_end', {
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

      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      // 연결
      await act(async () => {
        await result.current.connect();
        mockService.simulateConnect();
      });

      // 토큰 수신
      act(() => {
        mockService.simulateEvent('stream_token', {
          message_id: 'msg-001',
          token: '완료된 응답',
        });
      });

      // 스트리밍 완료
      act(() => {
        mockService.simulateEvent('stream_end', {
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
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      // 연결
      await act(async () => {
        await result.current.connect();
        mockService.simulateConnect();
      });

      // 토큰 수신
      act(() => {
        mockService.simulateEvent('stream_token', {
          message_id: 'msg-001',
          token: '에러 발생 전 응답',
        });
      });

      // 에러 발생
      act(() => {
        mockService.simulateEvent('stream_error', {
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

    it('재연결 실패 시 onError 콜백을 호출해야 함', async () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      // 연결
      await act(async () => {
        await result.current.connect();
        mockService.simulateConnect();
      });

      // 재연결 실패
      act(() => {
        mockService.simulateEvent('reconnect_failed', {
          attempts: 3,
          maxAttempts: 3,
        });
      });

      expect(mockOnError).toHaveBeenCalledWith(
        '서버 연결이 끊어졌습니다. 페이지를 새로고침해주세요.'
      );
    });
  });

  describe('소스 처리', () => {
    it('스트리밍 소스를 수신해야 함', async () => {
      const { result } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      // 연결
      await act(async () => {
        await result.current.connect();
        mockService.simulateConnect();
      });

      // 토큰 수신
      act(() => {
        mockService.simulateEvent('stream_token', {
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
        mockService.simulateEvent('stream_sources', {
          message_id: 'msg-001',
          sources: mockSources,
        });
      });

      expect(result.current.streamingMessage?.sources).toHaveLength(2);
      expect(result.current.streamingMessage?.sources?.[0].document).toBe('doc1.pdf');
    });
  });

  describe('클린업', () => {
    it('언마운트 시 이벤트 리스너가 제거되어야 함', () => {
      const { unmount } = renderHook(() =>
        useChatStreamingCore(mockService, {
          sessionId: 'test-session',
          onMessageComplete: mockOnMessageComplete,
          onError: mockOnError,
        })
      );

      unmount();

      // 이벤트 리스너 제거 확인
      expect(mockService.off).toHaveBeenCalledWith('connection', expect.any(Function));
      expect(mockService.off).toHaveBeenCalledWith('stream_start', expect.any(Function));
      expect(mockService.off).toHaveBeenCalledWith('stream_token', expect.any(Function));
      expect(mockService.off).toHaveBeenCalledWith('stream_sources', expect.any(Function));
      expect(mockService.off).toHaveBeenCalledWith('stream_end', expect.any(Function));
      expect(mockService.off).toHaveBeenCalledWith('stream_error', expect.any(Function));
      expect(mockService.off).toHaveBeenCalledWith('reconnect_failed', expect.any(Function));
    });
  });
});
