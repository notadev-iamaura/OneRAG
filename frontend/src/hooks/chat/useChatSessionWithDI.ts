/**
 * useChatSessionWithDI - 하위 호환성 별칭
 *
 * useChatSession이 이제 기본적으로 DI 패턴을 사용합니다.
 * 이 파일은 기존 코드와의 하위 호환성을 위해 유지됩니다.
 *
 * @deprecated useChatSession을 직접 사용하세요.
 */

export { useChatSession as useChatSessionWithDI } from './useChatSession';
export type { UseChatSessionOptions, UseChatSessionReturn } from './useChatSession';
