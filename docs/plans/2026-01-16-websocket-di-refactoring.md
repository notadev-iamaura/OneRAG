# WebSocket 서비스 DI 패턴 리팩토링 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** WebSocket 서비스에 DI(Dependency Injection) 패턴을 적용하여 단위 테스트와 E2E 테스트 모두에서 진짜/가짜 WebSocket을 쉽게 교체할 수 있도록 구조 개선

**Architecture:**
- 기존 프론트엔드의 Context/Provider 패턴과 동일한 방식 적용
- `WebSocketProvider`를 통해 WebSocket 팩토리를 전역 주입
- 테스트 시 `overrideFactory` prop으로 Mock WebSocket 주입 가능

**Tech Stack:** React 19, TypeScript, Vitest, React Testing Library

---

## 현재 문제점

```typescript
// 현재: WebSocket이 클래스 내부에 하드코딩
class ChatWebSocketService {
  connect() {
    this.ws = new WebSocket(url);  // ❌ 교체 불가능
  }
}
```

## 목표 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    WebSocketProvider                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ createWebSocket: (url: string) => WebSocket         │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                          │
          ┌───────────────┴───────────────┐
          ▼                               ▼
    실제 앱 / E2E                      단위 테스트
    ┌──────────────┐                ┌──────────────┐
    │ new WebSocket│                │ MockWebSocket │
    └──────────────┘                └──────────────┘
```

---

## Task 1: WebSocket 타입 정의

**Files:**
- Create: `frontend/src/types/websocket.ts`
- Test: `frontend/src/types/__tests__/websocket.test.ts`

**Step 1: 테스트 파일 생성**

```typescript
// frontend/src/types/__tests__/websocket.test.ts
import { describe, it, expect } from 'vitest';
import type { IWebSocket, WebSocketFactory, WebSocketConfig } from '../websocket';

describe('WebSocket 타입 정의', () => {
  it('IWebSocket 인터페이스는 표준 WebSocket API를 따라야 함', () => {
    // 타입 체크 테스트 - 컴파일 타임에 검증됨
    const mockWebSocket: IWebSocket = {
      readyState: 0,
      send: () => {},
      close: () => {},
      onopen: null,
      onclose: null,
      onmessage: null,
      onerror: null,
    };

    expect(mockWebSocket.readyState).toBe(0);
    expect(typeof mockWebSocket.send).toBe('function');
    expect(typeof mockWebSocket.close).toBe('function');
  });

  it('WebSocketFactory는 URL을 받아 IWebSocket을 반환해야 함', () => {
    const factory: WebSocketFactory = (url: string) => {
      return {
        readyState: 0,
        send: () => {},
        close: () => {},
        onopen: null,
        onclose: null,
        onmessage: null,
        onerror: null,
      };
    };

    const ws = factory('ws://localhost:8080');
    expect(ws).toBeDefined();
    expect(ws.readyState).toBe(0);
  });

  it('WebSocketConfig는 재연결 설정을 포함해야 함', () => {
    const config: WebSocketConfig = {
      maxReconnectAttempts: 5,
      reconnectInterval: 3000,
    };

    expect(config.maxReconnectAttempts).toBe(5);
    expect(config.reconnectInterval).toBe(3000);
  });
});
```

**Step 2: 테스트 실행하여 실패 확인**

Run: `cd frontend && npm test -- src/types/__tests__/websocket.test.ts`
Expected: FAIL - `../websocket` 모듈을 찾을 수 없음

**Step 3: 타입 정의 구현**

```typescript
// frontend/src/types/websocket.ts
/**
 * WebSocket DI 패턴을 위한 타입 정의
 *
 * 기존 FeatureProvider, ConfigProvider와 동일한 패턴 적용
 * - 인터페이스 기반 추상화
 * - 팩토리 함수 타입
 * - 설정 타입
 */

/**
 * WebSocket 인터페이스
 * 표준 WebSocket API의 핵심 메서드만 추출
 */
export interface IWebSocket {
  /** 연결 상태 (0: CONNECTING, 1: OPEN, 2: CLOSING, 3: CLOSED) */
  readonly readyState: number;

  /** 데이터 전송 */
  send(data: string | ArrayBuffer | Blob | ArrayBufferView): void;

  /** 연결 종료 */
  close(code?: number, reason?: string): void;

  /** 이벤트 핸들러 */
  onopen: ((event: Event) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
}

/**
 * WebSocket 상태 상수
 */
export const WebSocketReadyState = {
  CONNECTING: 0,
  OPEN: 1,
  CLOSING: 2,
  CLOSED: 3,
} as const;

/**
 * WebSocket 팩토리 함수 타입
 * DI 컨테이너에서 주입하는 핵심 타입
 */
export type WebSocketFactory = (url: string) => IWebSocket;

/**
 * WebSocket 설정
 */
export interface WebSocketConfig {
  /** 최대 재연결 시도 횟수 (기본값: 5) */
  maxReconnectAttempts?: number;

  /** 재연결 기본 간격 (ms, 기본값: 3000) */
  reconnectInterval?: number;

  /** 연결 타임아웃 (ms, 기본값: 10000) */
  connectionTimeout?: number;
}

/**
 * 기본 WebSocket 팩토리
 * 실제 브라우저 WebSocket 생성
 */
export const defaultWebSocketFactory: WebSocketFactory = (url: string): IWebSocket => {
  return new WebSocket(url) as IWebSocket;
};

/**
 * 기본 WebSocket 설정
 */
export const defaultWebSocketConfig: Required<WebSocketConfig> = {
  maxReconnectAttempts: 5,
  reconnectInterval: 3000,
  connectionTimeout: 10000,
};
```

**Step 4: 테스트 실행하여 통과 확인**

Run: `cd frontend && npm test -- src/types/__tests__/websocket.test.ts`
Expected: PASS - 3개 테스트 통과

**Step 5: 타입 인덱스 파일 업데이트**

```typescript
// frontend/src/types/index.ts 에 추가
export type {
  IWebSocket,
  WebSocketFactory,
  WebSocketConfig,
} from './websocket';
export {
  WebSocketReadyState,
  defaultWebSocketFactory,
  defaultWebSocketConfig,
} from './websocket';
```

**Step 6: 커밋**

```bash
git add frontend/src/types/websocket.ts frontend/src/types/__tests__/websocket.test.ts frontend/src/types/index.ts
git commit -m "$(cat <<'EOF'
기능: WebSocket DI 패턴을 위한 타입 정의 추가

- IWebSocket 인터페이스 정의 (표준 WebSocket API 추상화)
- WebSocketFactory 타입 정의 (DI 핵심)
- WebSocketConfig 설정 타입 정의
- defaultWebSocketFactory 기본 구현

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: WebSocket Context 및 Provider 생성

**Files:**
- Create: `frontend/src/core/WebSocketContext.ts`
- Create: `frontend/src/core/WebSocketProvider.tsx`
- Test: `frontend/src/core/__tests__/WebSocketProvider.test.tsx`

**Step 1: Context 테스트 작성**

```typescript
// frontend/src/core/__tests__/WebSocketProvider.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { WebSocketProvider, useWebSocket } from '../WebSocketProvider';
import type { IWebSocket, WebSocketFactory } from '../../types/websocket';

/**
 * Mock WebSocket 구현
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
 */
function TestComponent() {
  const { createWebSocket, config } = useWebSocket();
  const ws = createWebSocket('ws://test.com');

  return (
    <div>
      <span data-testid="ws-url">{(ws as MockWebSocket).url}</span>
      <span data-testid="max-reconnect">{config.maxReconnectAttempts}</span>
    </div>
  );
}

describe('WebSocketProvider', () => {
  it('기본 WebSocket 팩토리를 제공해야 함', () => {
    // 브라우저 WebSocket을 Mock으로 대체
    const originalWebSocket = globalThis.WebSocket;
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;

    render(
      <WebSocketProvider>
        <TestComponent />
      </WebSocketProvider>
    );

    expect(screen.getByTestId('ws-url').textContent).toBe('ws://test.com');
    expect(screen.getByTestId('max-reconnect').textContent).toBe('5');

    globalThis.WebSocket = originalWebSocket;
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
        config={{ maxReconnectAttempts: 10 }}
      >
        <TestComponent />
      </WebSocketProvider>
    );

    expect(screen.getByTestId('max-reconnect').textContent).toBe('10');
  });

  it('Provider 없이 useWebSocket 호출 시 에러가 발생해야 함', () => {
    // 에러 바운더리 없이 렌더링하면 에러 발생
    expect(() => {
      render(<TestComponent />);
    }).toThrow('useWebSocket must be used within WebSocketProvider');
  });
});
```

**Step 2: 테스트 실행하여 실패 확인**

Run: `cd frontend && npm test -- src/core/__tests__/WebSocketProvider.test.tsx`
Expected: FAIL - `../WebSocketProvider` 모듈을 찾을 수 없음

**Step 3: WebSocket Context 구현**

```typescript
// frontend/src/core/WebSocketContext.ts
/**
 * WebSocket Context 정의
 *
 * FeatureContext, ConfigContext와 동일한 패턴
 */
import { createContext } from 'react';
import type { WebSocketFactory, WebSocketConfig } from '../types/websocket';
import { defaultWebSocketConfig } from '../types/websocket';

/**
 * WebSocket Context 값 타입
 */
export interface WebSocketContextValue {
  /** WebSocket 생성 팩토리 */
  createWebSocket: WebSocketFactory;

  /** WebSocket 설정 */
  config: Required<WebSocketConfig>;
}

/**
 * WebSocket Context
 * undefined 기본값 - Provider 없이 사용 시 에러 발생
 */
export const WebSocketContext = createContext<WebSocketContextValue | undefined>(
  undefined
);

WebSocketContext.displayName = 'WebSocketContext';
```

**Step 4: WebSocket Provider 구현**

```typescript
// frontend/src/core/WebSocketProvider.tsx
/**
 * WebSocket Provider
 *
 * FeatureProvider, ConfigProvider와 동일한 패턴
 * - 기본 팩토리 제공 (실제 WebSocket)
 * - 테스트 시 커스텀 팩토리 주입 가능
 */
import React, { useMemo, useContext } from 'react';
import { WebSocketContext, WebSocketContextValue } from './WebSocketContext';
import type { WebSocketFactory, WebSocketConfig } from '../types/websocket';
import {
  defaultWebSocketFactory,
  defaultWebSocketConfig,
} from '../types/websocket';

interface WebSocketProviderProps {
  children: React.ReactNode;

  /** 커스텀 WebSocket 팩토리 (테스트용) */
  factory?: WebSocketFactory;

  /** 커스텀 설정 */
  config?: Partial<WebSocketConfig>;
}

/**
 * WebSocket Provider 컴포넌트
 *
 * @example
 * // 실제 앱
 * <WebSocketProvider>
 *   <App />
 * </WebSocketProvider>
 *
 * @example
 * // 테스트
 * <WebSocketProvider factory={mockFactory}>
 *   <TestComponent />
 * </WebSocketProvider>
 */
export function WebSocketProvider({
  children,
  factory,
  config,
}: WebSocketProviderProps) {
  const value = useMemo<WebSocketContextValue>(() => ({
    createWebSocket: factory ?? defaultWebSocketFactory,
    config: {
      ...defaultWebSocketConfig,
      ...config,
    },
  }), [factory, config]);

  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
}

/**
 * WebSocket Context 사용 훅
 *
 * @throws Provider 없이 사용 시 에러
 */
export function useWebSocket(): WebSocketContextValue {
  const context = useContext(WebSocketContext);

  if (!context) {
    throw new Error('useWebSocket must be used within WebSocketProvider');
  }

  return context;
}

/**
 * WebSocket 팩토리만 사용하는 훅
 */
export function useWebSocketFactory(): WebSocketFactory {
  return useWebSocket().createWebSocket;
}

/**
 * WebSocket 설정만 사용하는 훅
 */
export function useWebSocketConfig(): Required<WebSocketConfig> {
  return useWebSocket().config;
}
```

**Step 5: 테스트 실행하여 통과 확인**

Run: `cd frontend && npm test -- src/core/__tests__/WebSocketProvider.test.tsx`
Expected: PASS - 4개 테스트 통과

**Step 6: core/index.ts 내보내기 추가**

```typescript
// frontend/src/core/index.ts 에 추가
export { WebSocketContext } from './WebSocketContext';
export type { WebSocketContextValue } from './WebSocketContext';
export {
  WebSocketProvider,
  useWebSocket,
  useWebSocketFactory,
  useWebSocketConfig,
} from './WebSocketProvider';
```

**Step 7: 커밋**

```bash
git add frontend/src/core/WebSocketContext.ts frontend/src/core/WebSocketProvider.tsx frontend/src/core/__tests__/WebSocketProvider.test.tsx frontend/src/core/index.ts
git commit -m "$(cat <<'EOF'
기능: WebSocket DI를 위한 Context 및 Provider 추가

- WebSocketContext 생성 (FeatureContext 패턴)
- WebSocketProvider 컴포넌트 구현
- useWebSocket, useWebSocketFactory, useWebSocketConfig 훅
- 테스트 시 factory prop으로 Mock 주입 가능

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: ChatWebSocketService DI 적용

**Files:**
- Modify: `frontend/src/services/chatWebSocketService.ts`
- Create: `frontend/src/services/createChatWebSocketService.ts`
- Test: `frontend/src/services/__tests__/chatWebSocketService.di.test.ts`

**Step 1: DI 적용 서비스 테스트 작성**

```typescript
// frontend/src/services/__tests__/chatWebSocketService.di.test.ts
/**
 * ChatWebSocketService DI 패턴 테스트
 *
 * 진짜/가짜 WebSocket 교체 가능 여부 검증
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createChatWebSocketService } from '../createChatWebSocketService';
import type { IWebSocket, WebSocketFactory } from '../../types/websocket';
import { WebSocketReadyState } from '../../types/websocket';

/**
 * 테스트용 Mock WebSocket
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

  // 테스트 헬퍼
  simulateOpen() {
    this.readyState = WebSocketReadyState.OPEN;
    this.onopen?.(new Event('open'));
  }

  simulateMessage(data: unknown) {
    this.onmessage?.(
      new MessageEvent('message', {
        data: typeof data === 'string' ? data : JSON.stringify(data),
      })
    );
  }

  simulateClose(code = 1000, reason = '') {
    this.readyState = WebSocketReadyState.CLOSED;
    this.onclose?.(new CloseEvent('close', { code, reason }));
  }

  simulateError() {
    this.onerror?.(new Event('error'));
  }

  static clear() {
    MockWebSocket.instances = [];
  }

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

      // 비정상 종료 시뮬레이션
      MockWebSocket.getLastInstance()?.simulateClose(1006, 'abnormal');

      // 재연결 타이머 확인
      expect(MockWebSocket.instances.length).toBe(1);

      // 타이머 진행 (1초 후 재연결 시도)
      await vi.advanceTimersByTimeAsync(1000);

      expect(MockWebSocket.instances.length).toBe(2);

      vi.useRealTimers();
    });
  });

  describe('테스트 격리', () => {
    it('각 테스트마다 독립적인 서비스 인스턴스를 사용해야 함', () => {
      const service1 = createChatWebSocketService(mockFactory);
      const service2 = createChatWebSocketService(mockFactory);

      expect(service1).not.toBe(service2);
    });
  });
});
```

**Step 2: 테스트 실행하여 실패 확인**

Run: `cd frontend && npm test -- src/services/__tests__/chatWebSocketService.di.test.ts`
Expected: FAIL - `../createChatWebSocketService` 모듈을 찾을 수 없음

**Step 3: createChatWebSocketService 팩토리 함수 구현**

```typescript
// frontend/src/services/createChatWebSocketService.ts
/**
 * ChatWebSocketService 팩토리 함수
 *
 * DI 패턴 적용 - WebSocket 팩토리를 외부에서 주입받음
 *
 * @example
 * // 실제 앱에서
 * const service = createChatWebSocketService(defaultWebSocketFactory);
 *
 * @example
 * // 테스트에서
 * const service = createChatWebSocketService(mockFactory);
 */

import { logger } from '../utils/logger';
import type {
  ChatWebSocketRequest,
  ChatWebSocketResponse,
  StreamingState,
  EventCallback,
} from '../types/chatStreaming';
import type { IWebSocket, WebSocketFactory, WebSocketConfig } from '../types/websocket';
import { WebSocketReadyState, defaultWebSocketConfig } from '../types/websocket';

/**
 * WebSocket 기본 URL 가져오기
 */
const getWSBaseURL = (): string => {
  // 개발 모드: 환경변수 우선
  if (import.meta.env.DEV) {
    const devWsUrl = import.meta.env.VITE_DEV_WS_BASE_URL;
    if (devWsUrl) {
      return devWsUrl;
    }
    const devApiUrl =
      import.meta.env.VITE_DEV_API_BASE_URL ||
      'https://your-backend.railway.app';
    return devApiUrl.replace('https://', 'wss://').replace('http://', 'ws://');
  }

  // 런타임 설정 우선
  if (typeof window !== 'undefined' && window.RUNTIME_CONFIG?.WS_BASE_URL) {
    return window.RUNTIME_CONFIG.WS_BASE_URL;
  }

  // 빌드 타임 환경 변수
  if (import.meta.env.VITE_WS_BASE_URL) {
    return import.meta.env.VITE_WS_BASE_URL;
  }

  // API URL에서 WS URL 유추
  if (import.meta.env.VITE_API_BASE_URL) {
    const apiUrl = import.meta.env.VITE_API_BASE_URL;
    return apiUrl.replace('https://', 'wss://').replace('http://', 'ws://');
  }

  // Railway 환경 자동 감지
  if (typeof window !== 'undefined') {
    const currentHost = window.location.host;
    if (currentHost.includes('railway.app') || currentHost.includes('-production')) {
      return `wss://${currentHost}`;
    }
  }

  // 기본값
  return 'wss://your-backend.railway.app';
};

/**
 * ChatWebSocketService 인터페이스
 */
export interface IChatWebSocketService {
  readonly isConnected: boolean;
  readonly currentState: StreamingState;
  connect(sessionId: string): Promise<void>;
  disconnect(): void;
  sendMessage(content: string): string;
  on(event: string, callback: EventCallback): void;
  off(event: string, callback: EventCallback): void;
  resetReconnectAttempts(): void;
}

/**
 * ChatWebSocketService 팩토리 함수
 *
 * @param createWebSocket - WebSocket 생성 팩토리 (DI 핵심)
 * @param config - WebSocket 설정
 * @returns ChatWebSocketService 인스턴스
 */
export function createChatWebSocketService(
  createWebSocket: WebSocketFactory,
  config?: Partial<WebSocketConfig>
): IChatWebSocketService {
  // 설정 병합
  const mergedConfig: Required<WebSocketConfig> = {
    ...defaultWebSocketConfig,
    ...config,
  };

  // 내부 상태
  let ws: IWebSocket | null = null;
  let reconnectAttempts = 0;
  let state: StreamingState = 'idle';
  let sessionId: string | null = null;
  let reconnectTimeoutId: number | null = null;
  const eventListeners: Map<string, EventCallback[]> = new Map();

  // 이벤트 발생 (내부용)
  const emit = (event: string, data: unknown): void => {
    const listeners = eventListeners.get(event);
    if (listeners) {
      listeners.forEach((callback) => {
        try {
          callback(data);
        } catch (error) {
          logger.error(`이벤트 핸들러 오류 [${event}]:`, error);
        }
      });
    }
  };

  // 재연결 스케줄링
  const scheduleReconnect = (): void => {
    if (reconnectAttempts >= mergedConfig.maxReconnectAttempts) {
      logger.error('❌ Chat WebSocket 재연결 최대 시도 횟수 초과');
      emit('reconnect_failed', {
        attempts: reconnectAttempts,
        maxAttempts: mergedConfig.maxReconnectAttempts,
      });
      return;
    }

    reconnectAttempts++;
    const delay = mergedConfig.reconnectInterval * Math.pow(2, reconnectAttempts - 1);

    logger.log(
      `🔄 Chat WebSocket 재연결 시도 ${reconnectAttempts}/${mergedConfig.maxReconnectAttempts} (${delay}ms 후)`
    );

    reconnectTimeoutId = window.setTimeout(() => {
      if (sessionId) {
        service.connect(sessionId).catch((error) => {
          logger.error('재연결 실패:', error);
        });
      }
    }, delay);
  };

  // 메시지 처리
  const handleMessage = (event: MessageEvent): void => {
    try {
      const data: ChatWebSocketResponse = JSON.parse(event.data as string);
      logger.log('📨 Chat WebSocket 메시지:', data.type, data.message_id);

      if (data.type === 'stream_end' || data.type === 'stream_error') {
        state = 'idle';
      }

      emit(data.type, data);
      emit('message', data);
    } catch (error) {
      logger.error('❌ Chat WebSocket 메시지 파싱 오류:', error, event.data);
      emit('parse_error', { error, rawData: event.data });
    }
  };

  // 서비스 객체
  const service: IChatWebSocketService = {
    get isConnected(): boolean {
      return ws?.readyState === WebSocketReadyState.OPEN;
    },

    get currentState(): StreamingState {
      return state;
    },

    connect(newSessionId: string): Promise<void> {
      return new Promise((resolve, reject) => {
        // 이미 같은 세션으로 연결된 경우
        if (service.isConnected && sessionId === newSessionId) {
          logger.log('✅ Chat WebSocket 이미 연결됨');
          resolve();
          return;
        }

        // 기존 연결 정리
        if (ws) {
          ws.close(1000, '새 세션 연결');
          ws = null;
        }

        // 재연결 타이머 취소
        if (reconnectTimeoutId) {
          clearTimeout(reconnectTimeoutId);
          reconnectTimeoutId = null;
        }

        sessionId = newSessionId;
        state = 'connecting';

        const wsBaseUrl = getWSBaseURL();
        const wsUrl = `${wsBaseUrl}/chat-ws?session_id=${encodeURIComponent(newSessionId)}`;
        logger.log('🔗 Chat WebSocket 연결 시도:', wsUrl);

        try {
          // 👇 DI 핵심: 주입된 팩토리로 WebSocket 생성
          ws = createWebSocket(wsUrl);

          ws.onopen = () => {
            logger.log('✅ Chat WebSocket 연결됨');
            reconnectAttempts = 0;
            state = 'idle';
            emit('connection', { connected: true });
            resolve();
          };

          ws.onmessage = handleMessage;

          ws.onclose = (event: CloseEvent) => {
            logger.log('🔌 Chat WebSocket 연결 해제:', event.code, event.reason);
            state = 'idle';
            emit('connection', { connected: false });

            if (event.code !== 1000 && sessionId) {
              scheduleReconnect();
            }
          };

          ws.onerror = () => {
            logger.error('❌ Chat WebSocket 오류');
            state = 'error';
            emit('error', { error: new Error('WebSocket 연결 실패') });
            reject(new Error('WebSocket 연결 실패'));
          };
        } catch (error) {
          logger.error('❌ Chat WebSocket 연결 실패:', error);
          state = 'error';
          reject(error);
        }
      });
    },

    disconnect(): void {
      if (reconnectTimeoutId) {
        clearTimeout(reconnectTimeoutId);
        reconnectTimeoutId = null;
      }

      if (ws) {
        logger.log('🔌 Chat WebSocket 연결 해제');
        ws.close(1000, '클라이언트 연결 해제');
        ws = null;
      }

      sessionId = null;
      state = 'idle';
      reconnectAttempts = 0;
      eventListeners.clear();
    },

    sendMessage(content: string): string {
      if (!service.isConnected) {
        throw new Error('WebSocket이 연결되지 않았습니다.');
      }

      if (!sessionId) {
        throw new Error('세션 ID가 설정되지 않았습니다.');
      }

      const messageId = `msg_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;

      const request: ChatWebSocketRequest = {
        type: 'message',
        message_id: messageId,
        content,
        session_id: sessionId,
      };

      state = 'streaming';
      ws!.send(JSON.stringify(request));

      logger.log('📤 Chat 메시지 전송:', {
        messageId,
        content: content.length > 50 ? content.substring(0, 50) + '...' : content,
      });

      return messageId;
    },

    on(event: string, callback: EventCallback): void {
      if (!eventListeners.has(event)) {
        eventListeners.set(event, []);
      }
      eventListeners.get(event)!.push(callback);
    },

    off(event: string, callback: EventCallback): void {
      const listeners = eventListeners.get(event);
      if (listeners) {
        const index = listeners.indexOf(callback);
        if (index > -1) {
          listeners.splice(index, 1);
        }
      }
    },

    resetReconnectAttempts(): void {
      reconnectAttempts = 0;
    },
  };

  logger.log('🚀 ChatWebSocketService 생성됨 (DI 패턴)');
  return service;
}
```

**Step 4: 테스트 실행하여 통과 확인**

Run: `cd frontend && npm test -- src/services/__tests__/chatWebSocketService.di.test.ts`
Expected: PASS - 6개 테스트 통과

**Step 5: 커밋**

```bash
git add frontend/src/services/createChatWebSocketService.ts frontend/src/services/__tests__/chatWebSocketService.di.test.ts
git commit -m "$(cat <<'EOF'
기능: ChatWebSocketService DI 팩토리 함수 구현

- createChatWebSocketService() 팩토리 함수 추가
- WebSocketFactory를 외부에서 주입받아 WebSocket 생성
- IChatWebSocketService 인터페이스 정의
- 기존 기능 100% 유지 (연결, 메시지, 이벤트, 재연결)
- 테스트 시 MockWebSocket 주입 가능

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 기존 싱글톤 서비스 마이그레이션

**Files:**
- Modify: `frontend/src/services/chatWebSocketService.ts`
- Test: 기존 테스트가 여전히 통과하는지 확인

**Step 1: 싱글톤 서비스 마이그레이션**

```typescript
// frontend/src/services/chatWebSocketService.ts
/**
 * 채팅 스트리밍 WebSocket 서비스
 *
 * DI 패턴 적용 버전
 * - 내부적으로 createChatWebSocketService() 사용
 * - 기존 싱글톤 인터페이스 유지 (하위 호환성)
 */

import {
  createChatWebSocketService,
  IChatWebSocketService,
} from './createChatWebSocketService';
import { defaultWebSocketFactory } from '../types/websocket';

/**
 * 싱글톤 인스턴스
 *
 * 기본 WebSocket 팩토리 사용 (실제 브라우저 WebSocket)
 * 테스트에서는 createChatWebSocketService()를 직접 사용하여
 * Mock WebSocket 주입 가능
 */
export const chatWebSocketService: IChatWebSocketService =
  createChatWebSocketService(defaultWebSocketFactory);

export default chatWebSocketService;

// 타입 재내보내기
export type { IChatWebSocketService } from './createChatWebSocketService';
```

**Step 2: 기존 테스트 실행하여 호환성 확인**

Run: `cd frontend && npm test -- src/services/__tests__/chatWebSocketService.test.ts`
Expected: PASS - 기존 18개 테스트 모두 통과

**Step 3: 전체 테스트 실행**

Run: `cd frontend && npm test`
Expected: PASS - 모든 테스트 통과

**Step 4: 커밋**

```bash
git add frontend/src/services/chatWebSocketService.ts
git commit -m "$(cat <<'EOF'
리팩터: 기존 싱글톤 서비스를 DI 기반으로 마이그레이션

- chatWebSocketService 싱글톤이 내부적으로 createChatWebSocketService() 사용
- 기존 API 100% 하위 호환성 유지
- 실제 앱에서는 defaultWebSocketFactory 사용
- 테스트에서는 createChatWebSocketService()로 Mock 주입 가능

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: useChatStreaming 훅 DI 적용

**Files:**
- Create: `frontend/src/hooks/chat/useChatStreamingWithDI.ts`
- Test: `frontend/src/hooks/chat/__tests__/useChatStreamingWithDI.test.ts`

**Step 1: DI 적용 훅 테스트 작성**

```typescript
// frontend/src/hooks/chat/__tests__/useChatStreamingWithDI.test.ts
/**
 * useChatStreamingWithDI 훅 테스트
 *
 * WebSocketProvider와 통합된 훅 테스트
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import React from 'react';
import { WebSocketProvider } from '../../../core/WebSocketProvider';
import { useChatStreamingWithDI } from '../useChatStreamingWithDI';
import type { IWebSocket, WebSocketFactory } from '../../../types/websocket';
import { WebSocketReadyState } from '../../../types/websocket';

/**
 * Mock WebSocket
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

  simulateOpen() {
    this.readyState = WebSocketReadyState.OPEN;
    this.onopen?.(new Event('open'));
  }

  simulateMessage(data: unknown) {
    this.onmessage?.(
      new MessageEvent('message', {
        data: typeof data === 'string' ? data : JSON.stringify(data),
      })
    );
  }

  simulateClose(code = 1000, reason = '') {
    this.readyState = WebSocketReadyState.CLOSED;
    this.onclose?.(new CloseEvent('close', { code, reason }));
  }

  static clear() {
    MockWebSocket.instances = [];
  }

  static getLastInstance(): MockWebSocket | undefined {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }
}

describe('useChatStreamingWithDI', () => {
  const mockOnMessageComplete = vi.fn();
  const mockOnError = vi.fn();
  let mockFactory: WebSocketFactory;

  beforeEach(() => {
    vi.clearAllMocks();
    MockWebSocket.clear();
    mockFactory = (url) => new MockWebSocket(url);
  });

  // Wrapper 컴포넌트
  const createWrapper = (factory: WebSocketFactory) => {
    return function Wrapper({ children }: { children: React.ReactNode }) {
      return (
        <WebSocketProvider factory={factory}>
          {children}
        </WebSocketProvider>
      );
    };
  };

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
      await result.current.connect();
    });

    // Mock WebSocket이 생성되었는지 확인
    expect(MockWebSocket.instances.length).toBe(1);
    expect(MockWebSocket.getLastInstance()?.url).toContain('test-session');
  });

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
    const connectPromise = act(async () => {
      const promise = result.current.connect();
      MockWebSocket.getLastInstance()?.simulateOpen();
      return promise;
    });
    await connectPromise;

    await waitFor(() => {
      expect(result.current.isConnected).toBe(true);
    });

    // 메시지 전송
    act(() => {
      result.current.sendStreamingMessage('안녕하세요');
    });

    expect(MockWebSocket.getLastInstance()?.send).toHaveBeenCalled();
  });

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
      const promise = result.current.connect();
      MockWebSocket.getLastInstance()?.simulateOpen();
      await promise;
    });

    // 토큰 수신
    act(() => {
      MockWebSocket.getLastInstance()?.simulateMessage({
        type: 'stream_token',
        message_id: 'msg-001',
        token: '안녕',
      });
    });

    expect(result.current.streamingMessage?.content).toBe('안녕');

    act(() => {
      MockWebSocket.getLastInstance()?.simulateMessage({
        type: 'stream_token',
        message_id: 'msg-001',
        token: '하세요',
      });
    });

    expect(result.current.streamingMessage?.content).toBe('안녕하세요');
  });

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

    // 연결
    await act(async () => {
      const promise = result.current.connect();
      MockWebSocket.getLastInstance()?.simulateOpen();
      await promise;
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
      vi.runAllTimers();
    });

    expect(mockOnMessageComplete).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'msg-001',
        content: '완료된 응답',
      })
    );

    vi.useRealTimers();
  });
});
```

**Step 2: 테스트 실행하여 실패 확인**

Run: `cd frontend && npm test -- src/hooks/chat/__tests__/useChatStreamingWithDI.test.ts`
Expected: FAIL - `../useChatStreamingWithDI` 모듈을 찾을 수 없음

**Step 3: DI 적용 훅 구현**

```typescript
// frontend/src/hooks/chat/useChatStreamingWithDI.ts
/**
 * DI 패턴이 적용된 채팅 스트리밍 훅
 *
 * WebSocketProvider에서 팩토리를 주입받아 사용
 */
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useWebSocket } from '../../core/WebSocketProvider';
import { createChatWebSocketService, IChatWebSocketService } from '../../services/createChatWebSocketService';
import type {
  StreamingMessage,
  StreamingState,
  StreamTokenMessage,
  StreamSourcesMessage,
  StreamEndMessage,
  StreamErrorMessage,
  ConnectionEventData,
  ReconnectFailedEventData,
} from '../../types/chatStreaming';
import type { ChatMessage } from '../../types';
import { logger } from '../../utils/logger';

interface UseChatStreamingWithDIProps {
  sessionId: string;
  onMessageComplete: (message: ChatMessage) => void;
  onError: (error: string) => void;
}

interface UseChatStreamingWithDIReturn {
  isConnected: boolean;
  streamingState: StreamingState;
  streamingMessage: StreamingMessage | null;
  connect: () => Promise<void>;
  disconnect: () => void;
  sendStreamingMessage: (content: string) => string | null;
}

/**
 * DI 패턴이 적용된 채팅 스트리밍 훅
 *
 * @example
 * // WebSocketProvider 내에서 사용
 * <WebSocketProvider factory={customFactory}>
 *   <ChatComponent />
 * </WebSocketProvider>
 *
 * function ChatComponent() {
 *   const { connect, sendStreamingMessage } = useChatStreamingWithDI({...});
 * }
 */
export function useChatStreamingWithDI({
  sessionId,
  onMessageComplete,
  onError,
}: UseChatStreamingWithDIProps): UseChatStreamingWithDIReturn {
  const { createWebSocket, config } = useWebSocket();

  // DI로 주입된 팩토리를 사용하여 서비스 생성
  const service = useMemo<IChatWebSocketService>(
    () => createChatWebSocketService(createWebSocket, config),
    [createWebSocket, config]
  );

  const [isConnected, setIsConnected] = useState(false);
  const [streamingState, setStreamingState] = useState<StreamingState>('idle');
  const [streamingMessage, setStreamingMessage] = useState<StreamingMessage | null>(null);

  // 콜백 참조 유지
  const onMessageCompleteRef = useRef(onMessageComplete);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onMessageCompleteRef.current = onMessageComplete;
    onErrorRef.current = onError;
  }, [onMessageComplete, onError]);

  // 연결
  const connect = useCallback(async () => {
    if (!sessionId) {
      logger.warn('세션 ID 없이 WebSocket 연결 시도');
      return;
    }

    if (sessionId.startsWith('fallback-')) {
      logger.warn('Fallback 세션은 WebSocket 연결을 지원하지 않습니다.');
      return;
    }

    try {
      await service.connect(sessionId);
      setIsConnected(true);
    } catch (error) {
      logger.error('WebSocket 연결 실패:', error);
      setIsConnected(false);
    }
  }, [sessionId, service]);

  // 연결 해제
  const disconnect = useCallback(() => {
    service.disconnect();
    setIsConnected(false);
    setStreamingState('idle');
    setStreamingMessage(null);
  }, [service]);

  // 메시지 전송
  const sendStreamingMessage = useCallback(
    (content: string): string | null => {
      if (!isConnected) {
        logger.error('WebSocket이 연결되지 않은 상태에서 메시지 전송 시도');
        return null;
      }

      try {
        const messageId = service.sendMessage(content);
        setStreamingMessage({
          id: messageId,
          content: '',
          state: 'streaming',
        });
        setStreamingState('streaming');
        return messageId;
      } catch (error) {
        logger.error('메시지 전송 실패:', error);
        onErrorRef.current('메시지 전송에 실패했습니다.');
        return null;
      }
    },
    [isConnected, service]
  );

  // 이벤트 리스너 설정
  useEffect(() => {
    const handleConnection = (data: unknown) => {
      const { connected } = data as ConnectionEventData;
      setIsConnected(connected);
      if (!connected) {
        setStreamingState('idle');
      }
    };

    const handleStreamStart = () => {
      setStreamingState('streaming');
    };

    const handleStreamToken = (data: unknown) => {
      const { message_id, token } = data as StreamTokenMessage;
      setStreamingMessage((prev) => {
        if (!prev || prev.id !== message_id) {
          return { id: message_id, content: token, state: 'streaming' };
        }
        return { ...prev, content: prev.content + token };
      });
    };

    const handleStreamSources = (data: unknown) => {
      const { message_id, sources } = data as StreamSourcesMessage;
      setStreamingMessage((prev) => {
        if (!prev || prev.id !== message_id) return prev;
        return { ...prev, sources };
      });
    };

    const handleStreamEnd = (data: unknown) => {
      const { message_id } = data as StreamEndMessage;
      setStreamingMessage((prev) => {
        if (!prev || prev.id !== message_id) return prev;

        const completedMessage: ChatMessage = {
          id: prev.id,
          role: 'assistant',
          content: prev.content,
          timestamp: new Date().toISOString(),
          sources: prev.sources,
        };

        setTimeout(() => {
          onMessageCompleteRef.current(completedMessage);
        }, 0);

        return null;
      });
      setStreamingState('idle');
    };

    const handleStreamError = (data: unknown) => {
      const { message_id, message, solutions } = data as StreamErrorMessage;
      const errorMessage = solutions?.length
        ? `${message}\n해결 방법: ${solutions.join(', ')}`
        : message;

      setStreamingMessage((prev) => {
        if (!prev || prev.id !== message_id) return prev;
        return { ...prev, state: 'error', error: errorMessage };
      });

      setStreamingState('error');
      onErrorRef.current(errorMessage);
    };

    const handleReconnectFailed = () => {
      onErrorRef.current('서버 연결이 끊어졌습니다. 페이지를 새로고침해주세요.');
    };

    // 이벤트 등록
    service.on('connection', handleConnection);
    service.on('stream_start', handleStreamStart);
    service.on('stream_token', handleStreamToken);
    service.on('stream_sources', handleStreamSources);
    service.on('stream_end', handleStreamEnd);
    service.on('stream_error', handleStreamError);
    service.on('reconnect_failed', handleReconnectFailed);

    // 클린업
    return () => {
      service.off('connection', handleConnection);
      service.off('stream_start', handleStreamStart);
      service.off('stream_token', handleStreamToken);
      service.off('stream_sources', handleStreamSources);
      service.off('stream_end', handleStreamEnd);
      service.off('stream_error', handleStreamError);
      service.off('reconnect_failed', handleReconnectFailed);
    };
  }, [service]);

  return {
    isConnected,
    streamingState,
    streamingMessage,
    connect,
    disconnect,
    sendStreamingMessage,
  };
}
```

**Step 4: 테스트 실행하여 통과 확인**

Run: `cd frontend && npm test -- src/hooks/chat/__tests__/useChatStreamingWithDI.test.ts`
Expected: PASS - 4개 테스트 통과

**Step 5: hooks/chat/index.ts 내보내기 추가**

```typescript
// frontend/src/hooks/chat/index.ts 에 추가
export { useChatStreamingWithDI } from './useChatStreamingWithDI';
```

**Step 6: 커밋**

```bash
git add frontend/src/hooks/chat/useChatStreamingWithDI.ts frontend/src/hooks/chat/__tests__/useChatStreamingWithDI.test.ts frontend/src/hooks/chat/index.ts
git commit -m "$(cat <<'EOF'
기능: DI 패턴이 적용된 useChatStreamingWithDI 훅 추가

- WebSocketProvider에서 팩토리와 설정을 주입받아 사용
- createChatWebSocketService()로 독립적인 서비스 인스턴스 생성
- 테스트 시 Provider에 Mock 팩토리 주입 가능
- 기존 useChatStreaming과 동일한 API 유지

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: App.tsx에 WebSocketProvider 통합

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.tsx` (있다면 확인)

**Step 1: App.tsx에 Provider 추가**

```typescript
// frontend/src/App.tsx 에서
// 기존 import에 추가
import { WebSocketProvider } from './core/WebSocketProvider';

// Provider 계층 구조 수정
function App() {
  return (
    <ConfigProvider>
      <FeatureProvider>
        <WebSocketProvider>  {/* 추가 */}
          <Router>
            <AppRoutes />
          </Router>
        </WebSocketProvider>  {/* 추가 */}
      </FeatureProvider>
    </ConfigProvider>
  );
}
```

**Step 2: 전체 테스트 실행**

Run: `cd frontend && npm test`
Expected: PASS - 모든 테스트 통과

**Step 3: 개발 서버 실행하여 정상 동작 확인**

Run: `cd frontend && npm run dev`
Expected: 앱이 정상적으로 로드되고 채팅 기능 동작

**Step 4: 커밋**

```bash
git add frontend/src/App.tsx
git commit -m "$(cat <<'EOF'
기능: App.tsx에 WebSocketProvider 통합

- Provider 계층: ConfigProvider > FeatureProvider > WebSocketProvider > Router
- 기존 FeatureProvider 패턴과 동일한 구조
- 전체 앱에서 WebSocket DI 사용 가능

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: E2E 테스트 (Playwright)

**Files:**
- Create: `frontend/e2e/websocket-chat.spec.ts`

**Step 1: Playwright E2E 테스트 작성**

```typescript
// frontend/e2e/websocket-chat.spec.ts
import { test, expect } from '@playwright/test';

test.describe('WebSocket 채팅 E2E 테스트', () => {
  test.beforeEach(async ({ page }) => {
    // 앱 로드
    await page.goto('/bot');

    // 앱 로드 대기
    await page.waitForSelector('[data-testid="chat-input"]', { timeout: 10000 });
  });

  test('채팅 메시지를 전송하면 스트리밍 응답을 받아야 함', async ({ page }) => {
    // 입력
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('안녕하세요');

    // 전송
    await page.click('[data-testid="send-button"]');

    // 스트리밍 응답 대기 (10초)
    const assistantMessage = page.locator('[data-testid="assistant-message"]').last();
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // 응답 내용 확인
    const content = await assistantMessage.textContent();
    expect(content).toBeTruthy();
    expect(content!.length).toBeGreaterThan(0);
  });

  test('WebSocket 연결 상태가 표시되어야 함', async ({ page }) => {
    // 연결 상태 표시 확인 (있다면)
    const connectionStatus = page.locator('[data-testid="connection-status"]');

    if (await connectionStatus.isVisible()) {
      await expect(connectionStatus).toHaveText(/연결|connected/i);
    }
  });

  test('여러 메시지를 연속으로 전송할 수 있어야 함', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    const sendButton = page.locator('[data-testid="send-button"]');

    // 첫 번째 메시지
    await input.fill('첫 번째 질문입니다');
    await sendButton.click();

    // 응답 대기
    await page.waitForSelector('[data-testid="assistant-message"]', { timeout: 10000 });

    // 두 번째 메시지
    await input.fill('두 번째 질문입니다');
    await sendButton.click();

    // 두 번째 응답 대기
    const messages = page.locator('[data-testid="assistant-message"]');
    await expect(messages).toHaveCount(2, { timeout: 15000 });
  });
});
```

**Step 2: Playwright 설정 확인**

Run: `cd frontend && npx playwright install` (필요시)

**Step 3: E2E 테스트 실행**

Run: `cd frontend && npx playwright test e2e/websocket-chat.spec.ts`
Expected: 테스트 통과 (실제 서버 연결 필요)

**Step 4: 커밋**

```bash
git add frontend/e2e/websocket-chat.spec.ts
git commit -m "$(cat <<'EOF'
테스트: WebSocket 채팅 Playwright E2E 테스트 추가

- 실제 브라우저에서 실제 WebSocket으로 테스트
- 스트리밍 응답 수신 검증
- 연속 메시지 전송 검증

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 문서화

**Files:**
- Create: `frontend/docs/WEBSOCKET_DI_GUIDE.md`

**Step 1: 가이드 문서 작성**

```markdown
<!-- frontend/docs/WEBSOCKET_DI_GUIDE.md -->
# WebSocket DI 패턴 가이드

## 개요

WebSocket 서비스에 DI(Dependency Injection) 패턴을 적용하여 테스트 용이성을 개선했습니다.

## 아키텍처

```
┌─────────────────────────────────────────┐
│            WebSocketProvider             │
│  ┌─────────────────────────────────┐    │
│  │ factory: WebSocketFactory       │    │
│  │ config: WebSocketConfig         │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
                    │
    ┌───────────────┴───────────────┐
    ▼                               ▼
실제 앱                          테스트
new WebSocket()                 MockWebSocket
```

## 사용법

### 1. 실제 앱에서 (기본)

```tsx
// App.tsx - 기본 WebSocket 사용
<WebSocketProvider>
  <ChatComponent />
</WebSocketProvider>
```

### 2. 테스트에서 (Mock 주입)

```tsx
// 테스트 파일
const mockFactory = (url) => new MockWebSocket(url);

<WebSocketProvider factory={mockFactory}>
  <ChatComponent />
</WebSocketProvider>
```

### 3. 훅 사용

```tsx
// DI 적용 훅 사용
import { useChatStreamingWithDI } from '@/hooks/chat';

function ChatComponent() {
  const { connect, sendStreamingMessage } = useChatStreamingWithDI({
    sessionId: 'xxx',
    onMessageComplete: (msg) => console.log(msg),
    onError: (err) => console.error(err),
  });
}
```

### 4. 기존 싱글톤 사용 (하위 호환)

```tsx
// 기존 코드도 여전히 동작
import { chatWebSocketService } from '@/services/chatWebSocketService';

chatWebSocketService.connect('session-id');
```

## 테스트 가이드

### 단위 테스트

```tsx
import { createChatWebSocketService } from '@/services/createChatWebSocketService';

// Mock 팩토리로 서비스 생성
const service = createChatWebSocketService(mockFactory);
```

### 통합 테스트

```tsx
import { WebSocketProvider } from '@/core/WebSocketProvider';

// Provider로 감싸서 테스트
render(
  <WebSocketProvider factory={mockFactory}>
    <ComponentUnderTest />
  </WebSocketProvider>
);
```

### E2E 테스트 (Playwright)

```typescript
// 실제 WebSocket 사용
await page.goto('/bot');
await page.fill('[data-testid="chat-input"]', '안녕하세요');
await page.click('[data-testid="send-button"]');
```

## 주요 파일

| 파일 | 설명 |
|------|------|
| `types/websocket.ts` | WebSocket 관련 타입 정의 |
| `core/WebSocketProvider.tsx` | DI Provider |
| `services/createChatWebSocketService.ts` | 팩토리 함수 |
| `hooks/chat/useChatStreamingWithDI.ts` | DI 적용 훅 |
```

**Step 2: 커밋**

```bash
git add frontend/docs/WEBSOCKET_DI_GUIDE.md
git commit -m "$(cat <<'EOF'
문서: WebSocket DI 패턴 가이드 추가

- 아키텍처 설명
- 사용법 예시 (실제 앱, 테스트, 훅)
- 테스트 가이드 (단위, 통합, E2E)
- 주요 파일 목록

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## 최종 검증

**Step 1: 전체 테스트 실행**

```bash
cd frontend && npm test
```

Expected: 모든 테스트 통과

**Step 2: 린트 검사**

```bash
cd frontend && npm run lint
```

Expected: 오류 없음

**Step 3: 빌드 검사**

```bash
cd frontend && npm run build
```

Expected: 빌드 성공

**Step 4: 최종 커밋 (필요시)**

```bash
git add -A
git commit -m "$(cat <<'EOF'
정리: WebSocket DI 리팩토링 완료

- 8개 Task 완료
- 전체 테스트 통과
- 린트/빌드 검증 완료

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## 요약

| Task | 설명 | 파일 |
|------|------|------|
| 1 | WebSocket 타입 정의 | `types/websocket.ts` |
| 2 | Context/Provider 생성 | `core/WebSocketProvider.tsx` |
| 3 | 팩토리 함수 구현 | `services/createChatWebSocketService.ts` |
| 4 | 싱글톤 마이그레이션 | `services/chatWebSocketService.ts` |
| 5 | DI 적용 훅 | `hooks/chat/useChatStreamingWithDI.ts` |
| 6 | App.tsx 통합 | `App.tsx` |
| 7 | E2E 테스트 | `e2e/websocket-chat.spec.ts` |
| 8 | 문서화 | `docs/WEBSOCKET_DI_GUIDE.md` |

**총 예상 커밋**: 9개
**TDD 사이클**: 각 Task마다 테스트 먼저 작성 → 실패 확인 → 구현 → 통과 확인
