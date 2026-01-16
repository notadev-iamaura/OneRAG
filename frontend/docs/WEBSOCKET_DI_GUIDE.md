# WebSocket DI 패턴 가이드

## 개요

WebSocket 서비스에 DI(Dependency Injection) 패턴을 적용하여 테스트 용이성과 유지보수성을 개선했습니다. 이 가이드는 프론트엔드에서 WebSocket을 활용한 실시간 채팅 기능 구현 시 DI 패턴을 적용하는 방법을 설명합니다.

## 아키텍처

### 전체 구조

```
┌─────────────────────────────────────────────────────┐
│               WebSocketProvider                      │
│  ┌─────────────────────────────────────────────┐    │
│  │ factory: WebSocketFactory (주입 가능)        │    │
│  │ config: WebSocketConfig (옵션)               │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
   실제 앱                            테스트
   new WebSocket()                   MockWebSocket
```

### 핵심 컴포넌트

| 컴포넌트 | 역할 |
|---------|------|
| `WebSocketProvider` | DI 컨테이너, WebSocket 팩토리 주입 |
| `WebSocketFactory` | WebSocket 인스턴스 생성 팩토리 타입 |
| `createChatWebSocketService` | 팩토리 함수로 서비스 인스턴스 생성 |
| `useChatStreamingWithDI` | DI 적용된 React 훅 |

## 타입 정의

### 핵심 타입 (`types/websocket.ts`)

```typescript
// WebSocket 팩토리 타입
export type WebSocketFactory = (url: string) => WebSocket;

// WebSocket 설정 타입
export interface WebSocketConfig {
  // 재연결 관련 설정
  maxReconnectAttempts?: number;    // 최대 재연결 시도 횟수 (기본값: 5)
  reconnectInterval?: number;        // 재연결 간격 (ms, 기본값: 3000)

  // 타임아웃 설정
  connectionTimeout?: number;        // 연결 타임아웃 (ms, 기본값: 10000)

  // 디버그 설정
  debug?: boolean;                   // 디버그 로그 활성화
}

// WebSocket 이벤트 타입
export interface WebSocketMessage {
  type: 'chunk' | 'metadata' | 'done' | 'error';
  data?: string;
  chunk_index?: number;
  session_id?: string;
  error_code?: string;
  message?: string;
}

// 스트리밍 콜백 타입
export interface StreamingCallbacks {
  onChunk?: (chunk: string, index: number) => void;
  onMetadata?: (metadata: Record<string, unknown>) => void;
  onComplete?: (fullMessage: string) => void;
  onError?: (error: Error) => void;
}
```

## 사용법

### 1. 실제 앱에서 (기본 사용)

```tsx
// App.tsx - 기본 WebSocket 사용 (팩토리 미지정 시 브라우저 네이티브 사용)
import { WebSocketProvider } from '@/core/WebSocketProvider';

function App() {
  return (
    <WebSocketProvider>
      <ChatComponent />
    </WebSocketProvider>
  );
}
```

### 2. 커스텀 설정 적용

```tsx
// App.tsx - 커스텀 설정 적용
import { WebSocketProvider } from '@/core/WebSocketProvider';

const wsConfig = {
  maxReconnectAttempts: 10,
  reconnectInterval: 5000,
  connectionTimeout: 15000,
  debug: process.env.NODE_ENV === 'development',
};

function App() {
  return (
    <WebSocketProvider config={wsConfig}>
      <ChatComponent />
    </WebSocketProvider>
  );
}
```

### 3. 테스트에서 (Mock 주입)

```tsx
// __tests__/ChatComponent.test.tsx
import { render, screen } from '@testing-library/react';
import { WebSocketProvider } from '@/core/WebSocketProvider';
import { MockWebSocket } from '@/test-utils/MockWebSocket';

// Mock 팩토리 생성
const mockFactory = (url: string) => new MockWebSocket(url) as unknown as WebSocket;

test('채팅 메시지 전송 테스트', () => {
  render(
    <WebSocketProvider factory={mockFactory}>
      <ChatComponent />
    </WebSocketProvider>
  );

  // 테스트 로직...
});
```

### 4. DI 훅 사용

```tsx
// components/ChatBox.tsx
import { useChatStreamingWithDI } from '@/hooks/chat/useChatStreamingWithDI';
import { useState } from 'react';

function ChatBox() {
  const [messages, setMessages] = useState<string[]>([]);
  const [currentMessage, setCurrentMessage] = useState('');

  const {
    connect,
    disconnect,
    sendStreamingMessage,
    isConnected,
    isStreaming
  } = useChatStreamingWithDI({
    sessionId: 'user-session-123',

    onChunk: (chunk, index) => {
      // 실시간 청크 수신 처리
      setCurrentMessage(prev => prev + chunk);
    },

    onMessageComplete: (fullMessage) => {
      // 메시지 완료 처리
      setMessages(prev => [...prev, fullMessage]);
      setCurrentMessage('');
    },

    onError: (error) => {
      // 에러 처리
      console.error('WebSocket 에러:', error);
    },
  });

  const handleSend = async (text: string) => {
    if (!isConnected) {
      await connect();
    }
    await sendStreamingMessage(text);
  };

  return (
    <div>
      {/* 채팅 UI */}
    </div>
  );
}
```

### 5. 기존 싱글톤 사용 (하위 호환성)

```tsx
// 기존 코드도 여전히 동작합니다
import { chatWebSocketService } from '@/services/chatWebSocketService';

// 직접 서비스 사용
chatWebSocketService.connect('session-id');

// 메시지 전송
chatWebSocketService.sendStreamingMessage('안녕하세요', {
  onChunk: (chunk) => console.log(chunk),
  onComplete: (msg) => console.log('완료:', msg),
});
```

## 테스트 가이드

### Mock WebSocket 구현

```typescript
// test-utils/MockWebSocket.ts
export class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState: number = MockWebSocket.CONNECTING;

  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  private messageQueue: string[] = [];

  constructor(url: string) {
    this.url = url;
    // 비동기로 연결 완료 시뮬레이션
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.(new Event('open'));
    }, 0);
  }

  send(data: string): void {
    if (this.readyState !== MockWebSocket.OPEN) {
      throw new Error('WebSocket is not open');
    }
    this.messageQueue.push(data);
  }

  close(code?: number, reason?: string): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close', { code, reason }));
  }

  // 테스트 헬퍼: 서버 응답 시뮬레이션
  simulateMessage(data: object): void {
    const event = new MessageEvent('message', {
      data: JSON.stringify(data),
    });
    this.onmessage?.(event);
  }

  // 테스트 헬퍼: 스트리밍 응답 시뮬레이션
  simulateStreamingResponse(chunks: string[]): void {
    chunks.forEach((chunk, index) => {
      setTimeout(() => {
        this.simulateMessage({
          type: 'chunk',
          data: chunk,
          chunk_index: index,
        });

        if (index === chunks.length - 1) {
          this.simulateMessage({
            type: 'done',
            session_id: 'test-session',
          });
        }
      }, index * 50);
    });
  }
}
```

### 단위 테스트

```tsx
// __tests__/services/chatWebSocketService.test.ts
import { createChatWebSocketService } from '@/services/createChatWebSocketService';
import { MockWebSocket } from '@/test-utils/MockWebSocket';

describe('ChatWebSocketService', () => {
  let service: ReturnType<typeof createChatWebSocketService>;
  let mockWs: MockWebSocket;

  beforeEach(() => {
    // Mock 팩토리로 서비스 생성
    const mockFactory = (url: string) => {
      mockWs = new MockWebSocket(url);
      return mockWs as unknown as WebSocket;
    };

    service = createChatWebSocketService(mockFactory);
  });

  afterEach(() => {
    service.disconnect();
  });

  test('연결 성공', async () => {
    await service.connect('test-session');
    expect(service.isConnected()).toBe(true);
  });

  test('스트리밍 메시지 수신', async () => {
    await service.connect('test-session');

    const chunks: string[] = [];
    const onChunk = jest.fn((chunk: string) => chunks.push(chunk));
    const onComplete = jest.fn();

    service.sendStreamingMessage('안녕하세요', {
      onChunk,
      onComplete,
    });

    // 서버 응답 시뮬레이션
    mockWs.simulateStreamingResponse(['안녕', '하세요', '!']);

    await new Promise(resolve => setTimeout(resolve, 200));

    expect(onChunk).toHaveBeenCalledTimes(3);
    expect(onComplete).toHaveBeenCalledWith('안녕하세요!');
  });

  test('연결 에러 처리', async () => {
    const mockFactory = () => {
      const ws = new MockWebSocket('ws://test');
      setTimeout(() => {
        ws.onerror?.(new Event('error'));
      }, 0);
      return ws as unknown as WebSocket;
    };

    service = createChatWebSocketService(mockFactory);

    await expect(service.connect('test-session')).rejects.toThrow();
  });
});
```

### 통합 테스트

```tsx
// __tests__/integration/ChatComponent.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WebSocketProvider } from '@/core/WebSocketProvider';
import { MockWebSocket } from '@/test-utils/MockWebSocket';
import ChatComponent from '@/components/ChatComponent';

describe('ChatComponent 통합 테스트', () => {
  let mockWs: MockWebSocket;

  const mockFactory = (url: string) => {
    mockWs = new MockWebSocket(url);
    return mockWs as unknown as WebSocket;
  };

  test('메시지 전송 및 응답 표시', async () => {
    render(
      <WebSocketProvider factory={mockFactory}>
        <ChatComponent />
      </WebSocketProvider>
    );

    // 입력 및 전송
    const input = screen.getByTestId('chat-input');
    fireEvent.change(input, { target: { value: '안녕하세요' } });
    fireEvent.click(screen.getByTestId('send-button'));

    // 서버 응답 시뮬레이션
    await waitFor(() => {
      mockWs.simulateStreamingResponse(['안녕', '하세요', '!']);
    });

    // 응답 표시 확인
    await waitFor(() => {
      expect(screen.getByText(/안녕하세요!/)).toBeInTheDocument();
    });
  });
});
```

### E2E 테스트 (Playwright)

```typescript
// e2e/chat.spec.ts
import { test, expect } from '@playwright/test';

test.describe('채팅 기능 E2E 테스트', () => {
  test('실시간 채팅 메시지 송수신', async ({ page }) => {
    // 페이지 이동
    await page.goto('/bot');

    // 채팅 입력
    const input = page.getByTestId('chat-input');
    await input.fill('안녕하세요');

    // 전송 버튼 클릭
    await page.getByTestId('send-button').click();

    // 스트리밍 응답 대기 (실제 WebSocket 사용)
    await expect(page.getByTestId('chat-message').last()).toContainText(
      '안녕하세요',
      { timeout: 10000 }
    );
  });

  test('연결 상태 표시', async ({ page }) => {
    await page.goto('/bot');

    // 연결 상태 확인
    const connectionStatus = page.getByTestId('connection-status');
    await expect(connectionStatus).toHaveAttribute('data-connected', 'true');
  });
});
```

## 주요 파일 구조

```
frontend/src/
├── types/
│   └── websocket.ts              # WebSocket 관련 타입 정의
├── core/
│   └── WebSocketProvider.tsx     # DI Provider 컴포넌트
├── services/
│   ├── createChatWebSocketService.ts  # 팩토리 함수 (DI 지원)
│   └── chatWebSocketService.ts        # 싱글톤 인스턴스 (하위 호환)
├── hooks/
│   └── chat/
│       ├── useChatStreamingWithDI.ts  # DI 적용 훅
│       └── useChatStreaming.ts        # 기존 훅 (하위 호환)
└── test-utils/
    └── MockWebSocket.ts               # 테스트용 Mock
```

## 마이그레이션 가이드

### 기존 코드에서 DI 패턴으로 전환

#### Before (싱글톤 직접 사용)

```tsx
import { chatWebSocketService } from '@/services/chatWebSocketService';

function ChatComponent() {
  useEffect(() => {
    chatWebSocketService.connect('session-id');
    return () => chatWebSocketService.disconnect();
  }, []);

  // ...
}
```

#### After (DI 훅 사용)

```tsx
import { useChatStreamingWithDI } from '@/hooks/chat/useChatStreamingWithDI';

function ChatComponent() {
  const { connect, disconnect } = useChatStreamingWithDI({
    sessionId: 'session-id',
    onMessageComplete: (msg) => { /* ... */ },
  });

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  // ...
}
```

### 점진적 마이그레이션

1. **Phase 1**: `WebSocketProvider`를 앱 루트에 추가 (기존 코드 동작 유지)
2. **Phase 2**: 새 컴포넌트에서 `useChatStreamingWithDI` 훅 사용
3. **Phase 3**: 기존 컴포넌트를 점진적으로 DI 훅으로 전환
4. **Phase 4**: 싱글톤 의존성 제거 (선택적)

## 장점

| 항목 | 기존 방식 | DI 패턴 |
|------|----------|---------|
| 테스트 용이성 | Mock 어려움 | Mock 주입 용이 |
| 의존성 관리 | 하드코딩 | 주입 가능 |
| 설정 유연성 | 고정 설정 | 동적 설정 |
| 코드 재사용성 | 낮음 | 높음 |
| 하위 호환성 | - | 완전 지원 |

## 트러블슈팅

### WebSocket 연결 실패

```typescript
// 디버그 모드 활성화
<WebSocketProvider config={{ debug: true }}>
  ...
</WebSocketProvider>
```

### Mock이 동작하지 않는 경우

```typescript
// Provider가 올바르게 감싸져 있는지 확인
const wrapper = ({ children }) => (
  <WebSocketProvider factory={mockFactory}>
    {children}
  </WebSocketProvider>
);

render(<ChatComponent />, { wrapper });
```

### 재연결 로직 테스트

```typescript
test('재연결 시도', async () => {
  const mockFactory = jest.fn((url) => new MockWebSocket(url));

  service = createChatWebSocketService(mockFactory);
  await service.connect('test-session');

  // 연결 끊김 시뮬레이션
  mockWs.close(1006, 'Connection lost');

  // 재연결 대기
  await new Promise(resolve => setTimeout(resolve, 4000));

  // 재연결 시도 확인
  expect(mockFactory).toHaveBeenCalledTimes(2);
});
```

## 참고 자료

- [RAG Standard Backend - Streaming API Guide](../../docs/streaming-api-guide.md)
- [React Context API](https://react.dev/reference/react/createContext)
- [WebSocket API (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- [Testing Library](https://testing-library.com/docs/react-testing-library/intro/)
