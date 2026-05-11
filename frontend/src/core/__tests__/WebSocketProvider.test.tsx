/**
 * WebSocket Provider 테스트
 *
 * FeatureProvider, ConfigProvider와 동일한 패턴을 검증합니다.
 * - 기본 팩토리 제공
 * - 커스텀 팩토리 주입
 * - 커스텀 설정 주입
 * - Provider 없이 사용 시 에러
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { WebSocketProvider } from '../WebSocketProvider';
import { useWebSocket } from '../useWebSocket';
import type { IWebSocket, WebSocketFactory } from '../../types/websocket';

/**
 * Mock WebSocket 구현
 *
 * IWebSocket 인터페이스를 완전히 구현합니다.
 */
class MockWebSocket implements IWebSocket {
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(public url: string) {}

  send = vi.fn();
  close = vi.fn();
}

/**
 * 테스트용 컴포넌트
 *
 * useWebSocket 훅의 반환값을 화면에 표시합니다.
 */
function TestComponent() {
  const { createWebSocket, config } = useWebSocket();
  const ws = createWebSocket('ws://test.com');

  return (
    <div>
      <span data-testid="ws-url">{(ws as MockWebSocket).url}</span>
      <span data-testid="max-reconnect">{config.maxReconnectAttempts}</span>
      <span data-testid="reconnect-interval">{config.reconnectInterval}</span>
      <span data-testid="connection-timeout">{config.connectionTimeout}</span>
    </div>
  );
}

describe('WebSocketProvider', () => {
  it('기본 WebSocket 팩토리를 제공해야 함', () => {
    // 브라우저 WebSocket을 Mock으로 대체
    const originalWebSocket = globalThis.WebSocket;
    Object.defineProperty(globalThis, 'WebSocket', {
      value: MockWebSocket as unknown as typeof WebSocket,
      writable: true,
      configurable: true,
    });

    try {
      render(
        <WebSocketProvider>
          <TestComponent />
        </WebSocketProvider>
      );

      // 기본 설정값 검증
      expect(screen.getByTestId('ws-url').textContent).toBe('ws://test.com');
      expect(screen.getByTestId('max-reconnect').textContent).toBe('5');
      expect(screen.getByTestId('reconnect-interval').textContent).toBe('3000');
      expect(screen.getByTestId('connection-timeout').textContent).toBe('10000');
    } finally {
      // 원래 WebSocket 복원
      Object.defineProperty(globalThis, 'WebSocket', {
        value: originalWebSocket,
        writable: true,
        configurable: true,
      });
    }
  });

  it('커스텀 WebSocket 팩토리를 주입할 수 있어야 함', () => {
    const customFactory: WebSocketFactory = (url) => new MockWebSocket(url);

    render(
      <WebSocketProvider factory={customFactory}>
        <TestComponent />
      </WebSocketProvider>
    );

    expect(screen.getByTestId('ws-url').textContent).toBe('ws://test.com');
  });

  it('커스텀 설정을 주입할 수 있어야 함', () => {
    const customFactory: WebSocketFactory = (url) => new MockWebSocket(url);

    render(
      <WebSocketProvider
        factory={customFactory}
        config={{ maxReconnectAttempts: 10, reconnectInterval: 5000 }}
      >
        <TestComponent />
      </WebSocketProvider>
    );

    // 오버라이드된 설정 검증
    expect(screen.getByTestId('max-reconnect').textContent).toBe('10');
    expect(screen.getByTestId('reconnect-interval').textContent).toBe('5000');
    // 기본값 유지 검증
    expect(screen.getByTestId('connection-timeout').textContent).toBe('10000');
  });

  it('Provider 없이 useWebSocket 호출 시 에러가 발생해야 함', () => {
    // console.error를 모킹하여 React 에러 메시지 숨기기
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    expect(() => {
      render(<TestComponent />);
    }).toThrow('useWebSocket must be used within WebSocketProvider');

    consoleSpy.mockRestore();
  });
});
