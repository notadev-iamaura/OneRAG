/**
 * useChatStreamingWithDI - DI 패턴 스트리밍 관리 훅
 *
 * WebSocketProvider에서 주입받은 서비스를 사용하여 스트리밍을 관리합니다.
 * 내부적으로 useChatStreamingCore를 사용합니다.
 *
 * @example
 * // 일반적인 사용 (Provider 내에서)
 * const { isConnected, connect, sendStreamingMessage, streamingMessage } =
 *   useChatStreamingWithDI({
 *     sessionId: 'session-123',
 *     onMessageComplete: (msg) => console.log('완료:', msg),
 *     onError: (err) => console.error('오류:', err),
 *   });
 *
 * // 테스트 시에는 WebSocketProvider로 Mock 팩토리 주입
 * <WebSocketProvider factory={mockFactory}>
 *   <ComponentUsingHook />
 * </WebSocketProvider>
 */

import { useMemo } from 'react';
import { useWebSocket } from '../../core/useWebSocket';
import { createChatWebSocketService } from '../../services/createChatWebSocketService';
import { useChatStreamingCore } from './useChatStreamingCore';
import type {
  UseChatStreamingCoreProps,
  UseChatStreamingCoreReturn,
} from './useChatStreamingCore';

/**
 * DI 패턴을 사용하는 채팅 스트리밍 관리 훅
 *
 * @param props - 훅 옵션 (sessionId, onMessageComplete, onError)
 * @returns 스트리밍 관련 상태 및 함수
 */
export function useChatStreamingWithDI(
  props: UseChatStreamingCoreProps
): UseChatStreamingCoreReturn {
  // WebSocketProvider에서 팩토리와 설정 가져오기
  const { createWebSocket, config } = useWebSocket();

  // 서비스 인스턴스 생성 (메모이제이션)
  const service = useMemo(
    () => createChatWebSocketService(createWebSocket, config),
    [createWebSocket, config]
  );

  // Core 훅에 서비스 전달
  return useChatStreamingCore(service, props);
}

// 타입 재내보내기 (하위 호환성)
export type { UseChatStreamingCoreProps as UseChatStreamingWithDIProps };
export type { UseChatStreamingCoreReturn as UseChatStreamingWithDIReturn };
