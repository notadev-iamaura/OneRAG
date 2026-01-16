/**
 * Chat 훅 모듈 내보내기
 *
 * 채팅 기능 관련 모든 훅을 중앙에서 관리합니다.
 *
 * @example
 * import {
 *   // 세션 관리
 *   useChatSession,           // 기본 (DI 패턴)
 *   useChatSessionCore,       // 테스트용 직접 서비스 주입
 *   useChatSessionWithDI,     // deprecated - useChatSession 사용 권장
 *
 *   // 스트리밍 관리
 *   useChatStreaming,         // 기본 (전역 서비스)
 *   useChatStreamingCore,     // 테스트용 직접 서비스 주입
 *   useChatStreamingWithDI,   // DI 패턴 (WebSocketProvider 필요)
 *
 *   // 기타
 *   useChatMessages,
 *   useChatInteraction,
 *   useChatDevTools,
 * } from '@/hooks/chat';
 */

// ============================================================
// 세션 관리 훅
// ============================================================

// 세션 관리 - Core 훅 (직접 서비스 주입)
export { useChatSessionCore } from './useChatSessionCore';
export type {
  UseChatSessionCoreOptions,
  UseChatSessionCoreReturn,
} from './useChatSessionCore';

// 세션 관리 - DI 패턴 (기본, 권장)
export { useChatSession } from './useChatSession';
export type {
  UseChatSessionOptions,
  UseChatSessionReturn,
} from './useChatSession';

// 세션 관리 - 하위 호환성 별칭
/** @deprecated useChatSession을 직접 사용하세요. */
export { useChatSessionWithDI } from './useChatSessionWithDI';

// ============================================================
// 스트리밍 관리 훅
// ============================================================

// 스트리밍 - Core 훅 (직접 서비스 주입)
export { useChatStreamingCore } from './useChatStreamingCore';
export type {
  UseChatStreamingCoreProps,
  UseChatStreamingCoreReturn,
  WebSocketEventHandler,
} from './useChatStreamingCore';

// 스트리밍 - 전역 서비스 (기본)
export { useChatStreaming } from './useChatStreaming';
export type {
  UseChatStreamingProps,
  UseChatStreamingReturn,
} from './useChatStreaming';

// 스트리밍 - DI 패턴 (WebSocketProvider 필요)
export { useChatStreamingWithDI } from './useChatStreamingWithDI';
export type {
  UseChatStreamingWithDIProps,
  UseChatStreamingWithDIReturn,
} from './useChatStreamingWithDI';

// ============================================================
// 기타 훅
// ============================================================

// 메시지 관리
export { useChatMessages } from './useChatMessages';

// 사용자 인터랙션
export { useChatInteraction } from './useChatInteraction';

// 개발자 도구
export { useChatDevTools } from './useChatDevTools';
