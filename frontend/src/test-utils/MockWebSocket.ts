/**
 * MockWebSocket - 테스트용 WebSocket Mock 클래스
 *
 * DI 패턴으로 주입하여 WebSocket 동작을 시뮬레이션합니다.
 * - 연결/해제 이벤트 시뮬레이션
 * - 메시지 송수신 시뮬레이션
 * - 에러 상황 시뮬레이션
 *
 * @example
 * import { MockWebSocket } from '@/test-utils/MockWebSocket';
 *
 * const mockFactory = (url: string) => new MockWebSocket(url);
 * const service = createChatWebSocketService(mockFactory);
 *
 * // 연결 시뮬레이션
 * MockWebSocket.getLastInstance()?.simulateOpen();
 *
 * // 메시지 수신 시뮬레이션
 * MockWebSocket.getLastInstance()?.simulateMessage({ type: 'stream_token', data: '안녕' });
 */

import { vi } from 'vitest';
import type { IWebSocket } from '../types/websocket';
import { WebSocketReadyState } from '../types/websocket';

/**
 * 테스트용 Mock WebSocket 클래스
 *
 * IWebSocket 인터페이스를 구현하여 실제 WebSocket과 동일한 API 제공
 */
export class MockWebSocket implements IWebSocket {
  /** 생성된 모든 MockWebSocket 인스턴스 추적 */
  static instances: MockWebSocket[] = [];

  /** WebSocket 연결 상태 */
  readyState: number = WebSocketReadyState.CONNECTING;

  /** 연결 성공 이벤트 핸들러 */
  onopen: ((event: Event) => void) | null = null;

  /** 연결 종료 이벤트 핸들러 */
  onclose: ((event: CloseEvent) => void) | null = null;

  /** 메시지 수신 이벤트 핸들러 */
  onmessage: ((event: MessageEvent) => void) | null = null;

  /** 에러 이벤트 핸들러 */
  onerror: ((event: Event) => void) | null = null;

  /** 메시지 전송 Mock 함수 (호출 추적용) */
  send = vi.fn();

  /** 연결 종료 Mock 함수 (호출 추적용) */
  close = vi.fn();

  /**
   * MockWebSocket 생성자
   * @param url - WebSocket 연결 URL
   */
  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  // ============================================================================
  // 테스트 헬퍼 메서드
  // ============================================================================

  /**
   * WebSocket 연결 성공 시뮬레이션
   *
   * readyState를 OPEN으로 변경하고 onopen 이벤트 발생
   */
  simulateOpen(): void {
    this.readyState = WebSocketReadyState.OPEN;
    this.onopen?.(new Event('open'));
  }

  /**
   * WebSocket 메시지 수신 시뮬레이션
   *
   * @param data - 수신할 메시지 데이터 (객체는 JSON 문자열로 자동 변환)
   */
  simulateMessage(data: unknown): void {
    this.onmessage?.(
      new MessageEvent('message', {
        data: typeof data === 'string' ? data : JSON.stringify(data),
      })
    );
  }

  /**
   * WebSocket 연결 종료 시뮬레이션
   *
   * @param code - 종료 코드 (기본값: 1000 정상 종료)
   * @param reason - 종료 사유 (기본값: 빈 문자열)
   */
  simulateClose(code = 1000, reason = ''): void {
    this.readyState = WebSocketReadyState.CLOSED;
    this.onclose?.(new CloseEvent('close', { code, reason }));
  }

  /**
   * WebSocket 에러 발생 시뮬레이션
   */
  simulateError(): void {
    this.onerror?.(new Event('error'));
  }

  // ============================================================================
  // 정적 헬퍼 메서드
  // ============================================================================

  /**
   * 모든 MockWebSocket 인스턴스 초기화
   *
   * 각 테스트 시작 전 beforeEach에서 호출 권장
   */
  static clear(): void {
    MockWebSocket.instances = [];
  }

  /**
   * 마지막으로 생성된 MockWebSocket 인스턴스 반환
   *
   * @returns 마지막 인스턴스 또는 undefined
   */
  static getLastInstance(): MockWebSocket | undefined {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }

  /**
   * 인덱스로 특정 MockWebSocket 인스턴스 반환
   *
   * @param index - 인스턴스 인덱스 (0부터 시작)
   * @returns 해당 인스턴스 또는 undefined
   */
  static getInstance(index: number): MockWebSocket | undefined {
    return MockWebSocket.instances[index];
  }

  /**
   * 생성된 MockWebSocket 인스턴스 개수 반환
   */
  static get instanceCount(): number {
    return MockWebSocket.instances.length;
  }
}

/**
 * MockWebSocket 팩토리 함수 생성 헬퍼
 *
 * @returns WebSocketFactory로 사용 가능한 팩토리 함수
 *
 * @example
 * const mockFactory = createMockWebSocketFactory();
 * const service = createChatWebSocketService(mockFactory);
 */
export function createMockWebSocketFactory() {
  return (url: string) => new MockWebSocket(url);
}
