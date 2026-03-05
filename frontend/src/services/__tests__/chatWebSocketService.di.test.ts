/**
 * ChatWebSocketService DI 패턴 테스트
 *
 * 진짜/가짜 WebSocket 교체 가능 여부 검증
 * - 팩토리 함수로 WebSocket 주입
 * - Mock WebSocket으로 단위 테스트 격리
 * - 기존 기능(연결, 메시지, 이벤트, 재연결) 유지 확인
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createChatWebSocketService } from '../createChatWebSocketService';
import type { IWebSocket, WebSocketFactory } from '../../types/websocket';
import { WebSocketReadyState } from '../../types/websocket';

/**
 * 테스트용 Mock WebSocket
 *
 * IWebSocket 인터페이스를 구현하여 실제 WebSocket 동작을 시뮬레이션합니다.
 * 테스트에서 연결, 메시지 수신, 종료 등을 제어할 수 있습니다.
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

  // 테스트 헬퍼: 연결 성공 시뮬레이션
  simulateOpen() {
    this.readyState = WebSocketReadyState.OPEN;
    this.onopen?.(new Event('open'));
  }

  // 테스트 헬퍼: 메시지 수신 시뮬레이션
  simulateMessage(data: unknown) {
    this.onmessage?.(
      new MessageEvent('message', {
        data: typeof data === 'string' ? data : JSON.stringify(data),
      })
    );
  }

  // 테스트 헬퍼: 연결 종료 시뮬레이션
  simulateClose(code = 1000, reason = '') {
    this.readyState = WebSocketReadyState.CLOSED;
    this.onclose?.(new CloseEvent('close', { code, reason }));
  }

  // 테스트 헬퍼: 에러 발생 시뮬레이션
  simulateError() {
    this.onerror?.(new Event('error'));
  }

  // 테스트 간 인스턴스 초기화
  static clear() {
    MockWebSocket.instances = [];
  }

  // 마지막으로 생성된 인스턴스 반환
  static getLastInstance(): MockWebSocket | undefined {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }
}

describe('ChatWebSocketService with DI', () => {
  let mockFactory: WebSocketFactory;

  beforeEach(() => {
    MockWebSocket.clear();
    mockFactory = (url) => new MockWebSocket(url);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('팩토리 주입', () => {
    it('주입된 팩토리로 WebSocket을 생성해야 함', async () => {
      const service = createChatWebSocketService(mockFactory);
      const connectPromise = service.connect('test-session');

      // Mock WebSocket이 생성되었는지 확인
      expect(MockWebSocket.instances.length).toBe(1);
      expect(MockWebSocket.getLastInstance()?.url).toContain('test-session');

      // 연결 완료 시뮬레이션
      MockWebSocket.getLastInstance()?.simulateOpen();
      await connectPromise;

      expect(service.isConnected).toBe(true);
    });

    it('다른 팩토리로 교체할 수 있어야 함', async () => {
      const customFactory: WebSocketFactory = vi.fn((url) => new MockWebSocket(url));
      const service = createChatWebSocketService(customFactory);

      const connectPromise = service.connect('another-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await connectPromise;

      expect(customFactory).toHaveBeenCalledWith(
        expect.stringContaining('another-session')
      );
    });
  });

  describe('기존 기능 유지', () => {
    it('메시지 전송이 정상 동작해야 함', async () => {
      const service = createChatWebSocketService(mockFactory);
      const connectPromise = service.connect('test-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await connectPromise;

      const messageId = service.sendMessage('안녕하세요');

      expect(messageId).toBeDefined();
      expect(MockWebSocket.getLastInstance()?.send).toHaveBeenCalled();
    });

    it('이벤트 리스너가 정상 동작해야 함', async () => {
      const service = createChatWebSocketService(mockFactory);
      const connectPromise = service.connect('test-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await connectPromise;

      const tokenHandler = vi.fn();
      service.on('stream_token', tokenHandler);

      // 토큰 메시지 시뮬레이션
      MockWebSocket.getLastInstance()?.simulateMessage({
        type: 'stream_token',
        message_id: 'msg-001',
        token: '안녕',
      });

      expect(tokenHandler).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'stream_token',
          token: '안녕',
        })
      );
    });

    it('재연결 로직이 정상 동작해야 함', async () => {
      vi.useFakeTimers();

      const service = createChatWebSocketService(mockFactory, {
        maxReconnectAttempts: 3,
        reconnectInterval: 1000,
      });

      const connectPromise = service.connect('test-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await connectPromise;

      // 비정상 종료 시뮬레이션 (코드 1006 = 비정상 종료)
      MockWebSocket.getLastInstance()?.simulateClose(1006, 'abnormal');

      // 현재 인스턴스 수 확인
      expect(MockWebSocket.instances.length).toBe(1);

      // 타이머 진행 (1초 후 재연결 시도)
      await vi.advanceTimersByTimeAsync(1000);

      // 재연결 시도로 새 인스턴스 생성됨
      expect(MockWebSocket.instances.length).toBe(2);
    });

    it('이벤트 리스너 제거가 정상 동작해야 함', async () => {
      const service = createChatWebSocketService(mockFactory);
      const connectPromise = service.connect('test-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await connectPromise;

      const handler = vi.fn();
      service.on('stream_token', handler);
      service.off('stream_token', handler);

      // 메시지 시뮬레이션
      MockWebSocket.getLastInstance()?.simulateMessage({
        type: 'stream_token',
        message_id: 'msg-001',
        token: '테스트',
      });

      // 핸들러가 호출되지 않아야 함
      expect(handler).not.toHaveBeenCalled();
    });

    it('연결 해제가 정상 동작해야 함', async () => {
      const service = createChatWebSocketService(mockFactory);
      const connectPromise = service.connect('test-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await connectPromise;

      service.disconnect();

      expect(MockWebSocket.getLastInstance()?.close).toHaveBeenCalledWith(
        1000,
        '클라이언트 연결 해제'
      );
      expect(service.isConnected).toBe(false);
    });

    it('스트리밍 상태가 올바르게 업데이트되어야 함', async () => {
      const service = createChatWebSocketService(mockFactory);
      const connectPromise = service.connect('test-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await connectPromise;

      // 초기 상태
      expect(service.currentState).toBe('idle');

      // 메시지 전송 후 스트리밍 상태
      service.sendMessage('테스트');
      expect(service.currentState).toBe('streaming');

      // 스트리밍 종료 메시지 수신 후 idle 상태
      MockWebSocket.getLastInstance()?.simulateMessage({
        type: 'stream_end',
        message_id: 'msg-001',
        total_tokens: 10,
        processing_time_ms: 100,
      });
      expect(service.currentState).toBe('idle');
    });
  });

  describe('테스트 격리', () => {
    it('각 테스트마다 독립적인 서비스 인스턴스를 사용해야 함', () => {
      const service1 = createChatWebSocketService(mockFactory);
      const service2 = createChatWebSocketService(mockFactory);

      expect(service1).not.toBe(service2);
    });
  });

  describe('에러 처리', () => {
    it('연결되지 않은 상태에서 메시지 전송 시 에러를 발생시켜야 함', () => {
      const service = createChatWebSocketService(mockFactory);

      expect(() => service.sendMessage('테스트')).toThrow('WebSocket이 연결되지 않았습니다.');
    });

    it('WebSocket 에러 발생 시 에러 상태로 전환되어야 함', async () => {
      const service = createChatWebSocketService(mockFactory);
      const connectPromise = service.connect('test-session');

      // 에러 발생 시뮬레이션
      MockWebSocket.getLastInstance()?.simulateError();

      await expect(connectPromise).rejects.toThrow('WebSocket 연결 실패');
      expect(service.currentState).toBe('error');
    });
  });

  describe('설정 옵션', () => {
    it('커스텀 재연결 설정이 적용되어야 함', async () => {
      vi.useFakeTimers();

      const service = createChatWebSocketService(mockFactory, {
        maxReconnectAttempts: 2,
        reconnectInterval: 500,
      });

      const connectPromise = service.connect('test-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await connectPromise;

      // 비정상 종료
      MockWebSocket.getLastInstance()?.simulateClose(1006, 'abnormal');

      // 500ms 후 첫 번째 재연결 시도
      await vi.advanceTimersByTimeAsync(500);
      expect(MockWebSocket.instances.length).toBe(2);

      // 두 번째 연결도 실패
      MockWebSocket.getLastInstance()?.simulateClose(1006, 'abnormal');

      // 1000ms 후 두 번째 재연결 시도 (지수 백오프: 500 * 2)
      await vi.advanceTimersByTimeAsync(1000);
      expect(MockWebSocket.instances.length).toBe(3);

      // 세 번째 연결도 실패
      MockWebSocket.getLastInstance()?.simulateClose(1006, 'abnormal');

      // 최대 시도 횟수(2) 초과로 더 이상 재연결하지 않음
      await vi.advanceTimersByTimeAsync(10000);
      expect(MockWebSocket.instances.length).toBe(3);
    });
  });

  describe('Issue #11: stop() — 이벤트 리스너 보존 연결 해제', () => {
    it('stop()은 연결을 끊지만 이벤트 리스너는 보존해야 함', async () => {
      const service = createChatWebSocketService(mockFactory);
      const connectPromise = service.connect('test-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await connectPromise;

      // 이벤트 리스너 등록
      const tokenHandler = vi.fn();
      service.on('stream_token', tokenHandler);

      // stop() 호출 — 연결만 끊고 이벤트 리스너 보존
      service.stop();

      expect(service.isConnected).toBe(false);

      // 재연결 후 기존 이벤트 리스너가 동작해야 함
      const reconnectPromise = service.connect('test-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await reconnectPromise;

      // 토큰 메시지 수신 시뮬레이션
      MockWebSocket.getLastInstance()?.simulateMessage({
        type: 'stream_token',
        message_id: 'msg-002',
        token: '복구됨',
      });

      // 이벤트 리스너가 여전히 동작해야 함
      expect(tokenHandler).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'stream_token',
          token: '복구됨',
        })
      );
    });

    it('disconnect()는 이벤트 리스너까지 모두 제거해야 함', async () => {
      const service = createChatWebSocketService(mockFactory);
      const connectPromise = service.connect('test-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await connectPromise;

      const tokenHandler = vi.fn();
      service.on('stream_token', tokenHandler);

      // disconnect() 호출 — 이벤트 리스너 포함 전체 정리
      service.disconnect();

      // 재연결
      const reconnectPromise = service.connect('test-session');
      MockWebSocket.getLastInstance()?.simulateOpen();
      await reconnectPromise;

      // 토큰 메시지 수신 시뮬레이션
      MockWebSocket.getLastInstance()?.simulateMessage({
        type: 'stream_token',
        message_id: 'msg-003',
        token: '이벤트',
      });

      // disconnect() 이후이므로 핸들러 호출되지 않아야 함
      expect(tokenHandler).not.toHaveBeenCalled();
    });
  });
});
