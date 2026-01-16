/**
 * useChatStreaming - 전역 서비스 스트리밍 관리 훅
 *
 * 전역 chatWebSocketService 싱글톤을 사용하여 스트리밍을 관리합니다.
 * 내부적으로 useChatStreamingCore를 사용합니다.
 *
 * @example
 * // 일반적인 사용
 * const { isConnected, connect, sendStreamingMessage, streamingMessage } =
 *   useChatStreaming({
 *     sessionId: 'session-123',
 *     onMessageComplete: (msg) => console.log('완료:', msg),
 *     onError: (err) => console.error('오류:', err),
 *   });
 *
 * // DI 패턴이 필요한 경우 useChatStreamingWithDI 사용 권장
 */

import { chatWebSocketService } from '../../services/chatWebSocketService';
import { useChatStreamingCore } from './useChatStreamingCore';
import type {
  UseChatStreamingCoreProps,
  UseChatStreamingCoreReturn,
} from './useChatStreamingCore';

/**
 * 전역 서비스를 사용하는 채팅 스트리밍 관리 훅
 *
 * @param props - 훅 옵션 (sessionId, onMessageComplete, onError)
 * @returns 스트리밍 관련 상태 및 함수
 */
export function useChatStreaming(
  props: UseChatStreamingCoreProps
): UseChatStreamingCoreReturn {
  // 전역 싱글톤 서비스를 Core 훅에 전달
  return useChatStreamingCore(chatWebSocketService, props);
}

// 타입 재내보내기 (하위 호환성)
export type { UseChatStreamingCoreProps as UseChatStreamingProps };
export type { UseChatStreamingCoreReturn as UseChatStreamingReturn };
