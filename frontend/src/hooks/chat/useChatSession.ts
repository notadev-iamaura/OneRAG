/**
 * useChatSession - DI 패턴 세션 관리 훅
 *
 * ChatAPIProvider에서 주입받은 서비스를 사용하여 세션을 관리합니다.
 * 내부적으로 useChatSessionCore를 사용합니다.
 *
 * @example
 * // 일반적인 사용 (Provider 내에서)
 * const { sessionId, handleNewSession } = useChatSession(options);
 *
 * // 테스트 시에는 ChatAPIProvider로 Mock 서비스 주입
 * <ChatAPIProvider createService={() => mockService} config={config}>
 *   <ComponentUsingHook />
 * </ChatAPIProvider>
 */

import { useChatAPIService } from '../../core/useChatAPI';
import { useChatSessionCore } from './useChatSessionCore';
import type {
  UseChatSessionCoreOptions,
  UseChatSessionCoreReturn,
} from './useChatSessionCore';

/**
 * DI 패턴을 사용하는 채팅 세션 관리 훅
 *
 * @param options - 훅 옵션
 * @returns 세션 관련 상태 및 함수
 */
export function useChatSession(options: UseChatSessionCoreOptions): UseChatSessionCoreReturn {
  // DI Context에서 서비스 주입받기
  const chatAPI = useChatAPIService();

  // Core 훅에 서비스 전달
  return useChatSessionCore(chatAPI, options);
}

// 타입 재내보내기 (하위 호환성)
export type { UseChatSessionCoreOptions as UseChatSessionOptions };
export type { UseChatSessionCoreReturn as UseChatSessionReturn };
