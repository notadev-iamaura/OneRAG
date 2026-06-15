// 외부 웹사이트 임베드(embed) 통신 브리지 훅.
//
// 목적: OneRAG 챗봇을 sandbox iframe으로 외부 사이트에 임베드했을 때
//       부모 윈도우(host)와 안전하게 postMessage로 양방향 통신한다.
//
// 보안 핵심:
//   1) 부모 origin 화이트리스트 검증(RUNTIME_CONFIG.EMBED_ALLOWED_ORIGINS).
//      와일드카드('*')는 절대 사용하지 않고, 'null' origin(sandbox 등)은 명시적으로 거부한다.
//   2) host가 보낸 메시지의 source/type 스키마를 검증한다.
//   3) host가 보낸 send 메시지는 1000자 상한으로 제한한다.
//
// 메시지 프로토콜(버전 1):
//   - embed→host: onerag:ready / onerag:resize / onerag:status / onerag:pong / onerag:accepted / onerag:error
//   - host→embed: onerag:ping / onerag:focus / onerag:send / onerag:stop
import { useCallback, useEffect, useMemo } from 'react';

// 메시지 출처 식별자(스푸핑 방지용 고정 문자열)
const EMBED_MESSAGE_SOURCE = 'onerag-embed';
const HOST_MESSAGE_SOURCE = 'onerag-host';
// 프로토콜 버전(host loader와 호환성 관리)
const EMBED_MESSAGE_VERSION = 1;
// host가 보낼 수 있는 메시지 최대 길이(과도한 페이로드 차단)
const MAX_HOST_MESSAGE_LENGTH = 1000;

// embed(iframe)가 부모로 보내는 메시지 타입
type EmbedOutboundType =
  | 'onerag:ready'
  | 'onerag:resize'
  | 'onerag:status'
  | 'onerag:pong'
  | 'onerag:accepted'
  | 'onerag:error';

// 부모(host)가 iframe으로 보내는 메시지 타입
type HostInboundType =
  | 'onerag:ping'
  | 'onerag:focus'
  | 'onerag:send'
  | 'onerag:stop';

// embed→host 메시지 스키마
interface EmbedOutboundMessage {
  source: typeof EMBED_MESSAGE_SOURCE;
  version: typeof EMBED_MESSAGE_VERSION;
  type: EmbedOutboundType;
  requestId?: string;
  height?: number;
  route?: string;
  loading?: boolean;
  streaming?: boolean;
  messageCount?: number;
  error?: string;
}

// host→embed 메시지 스키마(검증 전이므로 모든 필드 optional)
interface HostInboundMessage {
  source?: string;
  type?: HostInboundType;
  requestId?: string;
  message?: string;
}

// 훅 옵션: embed 모드 활성화 여부 및 챗봇 상태/액션 핸들러
interface UseEmbedBridgeOptions {
  enabled: boolean;
  loading: boolean;
  isStreaming: boolean;
  messageCount: number;
  onSend: (message: string) => Promise<void> | void;
  onStop: () => void;
}

// RUNTIME_CONFIG.EMBED_ALLOWED_ORIGINS 값을 string[]로 정규화한다.
// 배열 또는 콤마 구분 문자열을 모두 허용하되, 빈 값은 제거한다.
function parseOrigins(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .filter((origin): origin is string => typeof origin === 'string')
      .map((origin) => origin.trim())
      .filter(Boolean);
  }
  if (typeof value !== 'string') {
    return [];
  }
  return value
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);
}

// 런타임 설정에서 허용 origin 목록을 읽어온다.
function runtimeAllowedOrigins(): string[] {
  if (typeof window === 'undefined') {
    return [];
  }
  return parseOrigins(window.RUNTIME_CONFIG?.EMBED_ALLOWED_ORIGINS);
}

// 허용 origin이 미설정일 때 폴백으로 사용할 현재 origin.
function defaultAllowedOrigin(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return window.location.origin || null;
}

// origin 화이트리스트 검증.
// 'null' origin(sandbox iframe 등)은 무조건 거부하고, 화이트리스트가 비었으면 현재 origin만 허용한다.
function isAllowedOrigin(origin: string, allowedOrigins: string[]): boolean {
  if (!origin || origin === 'null') {
    return false;
  }
  const allowed = allowedOrigins.length > 0
    ? allowedOrigins
    : [defaultAllowedOrigin()].filter((item): item is string => Boolean(item));
  return allowed.includes(origin);
}

// 현재 문서의 높이를 계산한다(부모 iframe 자동 리사이즈에 사용).
function currentDocumentHeight(): number {
  if (typeof document === 'undefined') {
    return 0;
  }
  return Math.max(
    document.documentElement?.scrollHeight ?? 0,
    document.body?.scrollHeight ?? 0,
    document.documentElement?.clientHeight ?? 0,
    document.body?.clientHeight ?? 0,
  );
}

// 수신 메시지가 host가 보낸 유효한 형태인지 스키마 검증.
function isHostMessage(value: unknown): value is HostInboundMessage {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as HostInboundMessage;
  return candidate.source === HOST_MESSAGE_SOURCE && typeof candidate.type === 'string';
}

/**
 * useEmbedBridge - embed 모드에서 부모 윈도우와 안전하게 통신하는 훅.
 *
 * @param enabled - embed 모드 활성화 여부(false면 모든 리스너 비활성)
 * @param loading - 챗봇 응답 진행 중 여부
 * @param isStreaming - 스트리밍 진행 중 여부
 * @param messageCount - 현재 대화의 메시지 개수
 * @param onSend - host가 보낸 메시지를 챗봇으로 전송하는 콜백
 * @param onStop - host가 중단을 요청했을 때 호출하는 콜백
 */
export function useEmbedBridge({
  enabled,
  loading,
  isStreaming,
  messageCount,
  onSend,
  onStop,
}: UseEmbedBridgeOptions): void {
  // 허용 origin 목록(컴포넌트 수명 동안 고정)
  const allowedOrigins = useMemo(runtimeAllowedOrigins, []);

  // 부모 윈도우로 메시지를 전송한다(허용 origin들에만 명시적으로 전송).
  const postToParent = useCallback((
    message: Omit<EmbedOutboundMessage, 'source' | 'version'>,
    targetOrigin?: string,
  ) => {
    if (typeof window === 'undefined') {
      return;
    }

    const payload: EmbedOutboundMessage = {
      source: EMBED_MESSAGE_SOURCE,
      version: EMBED_MESSAGE_VERSION,
      ...message,
    };
    const fallbackTarget = defaultAllowedOrigin();
    const targets = targetOrigin
      ? [targetOrigin]
      : (allowedOrigins.length > 0
        ? allowedOrigins
        : [fallbackTarget].filter((item): item is string => Boolean(item)));

    for (const target of targets) {
      window.parent.postMessage(payload, target);
    }
  }, [allowedOrigins]);

  // 현재 챗봇 상태를 부모로 통지한다.
  const postStatus = useCallback(() => {
    postToParent({
      type: 'onerag:status',
      loading,
      streaming: isStreaming,
      messageCount,
    });
  }, [isStreaming, loading, messageCount, postToParent]);

  // embed 준비 완료 시 ready/status 이벤트 발송.
  useEffect(() => {
    if (!enabled) {
      return;
    }

    postToParent({
      type: 'onerag:ready',
      route: window.location.pathname,
      height: currentDocumentHeight(),
      loading,
      streaming: isStreaming,
      messageCount,
    });
    postStatus();
  }, [enabled, isStreaming, loading, messageCount, postStatus, postToParent]);

  // 문서 높이 변화를 감지해 부모 iframe 높이를 자동 조정.
  useEffect(() => {
    if (!enabled) {
      return;
    }

    const postResize = () => {
      postToParent({
        type: 'onerag:resize',
        height: currentDocumentHeight(),
      });
    };

    postResize();

    // ResizeObserver 미지원 환경(구형 브라우저)은 resize 이벤트로 폴백.
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', postResize);
      return () => window.removeEventListener('resize', postResize);
    }

    const observer = new ResizeObserver(postResize);
    observer.observe(document.documentElement);
    return () => observer.disconnect();
  }, [enabled, postToParent]);

  // 부모(host)로부터 들어오는 메시지를 처리.
  useEffect(() => {
    if (!enabled) {
      return;
    }

    const handleMessage = (event: MessageEvent) => {
      // origin 화이트리스트 + 스키마 검증을 모두 통과한 메시지만 처리.
      if (!isAllowedOrigin(event.origin, allowedOrigins) || !isHostMessage(event.data)) {
        return;
      }

      const { type, requestId } = event.data;

      // ping → pong 응답(연결 확인용)
      if (type === 'onerag:ping') {
        postToParent({ type: 'onerag:pong', requestId }, event.origin);
        return;
      }

      // 입력창 포커스 요청
      if (type === 'onerag:focus') {
        const input = document.querySelector<HTMLTextAreaElement>('textarea');
        input?.focus();
        postToParent({ type: 'onerag:accepted', requestId }, event.origin);
        return;
      }

      // 응답 중단 요청
      if (type === 'onerag:stop') {
        onStop();
        postToParent({ type: 'onerag:accepted', requestId }, event.origin);
        return;
      }

      // host가 직접 메시지를 전송하는 요청
      if (type === 'onerag:send') {
        const message = typeof event.data.message === 'string'
          ? event.data.message.trim()
          : '';
        // 빈 메시지 또는 길이 초과는 거부
        if (!message || message.length > MAX_HOST_MESSAGE_LENGTH) {
          postToParent({
            type: 'onerag:error',
            requestId,
            error: 'invalid_message',
          }, event.origin);
          return;
        }
        // 이미 응답 진행 중이면 busy 반환
        if (loading) {
          postToParent({
            type: 'onerag:error',
            requestId,
            error: 'busy',
          }, event.origin);
          return;
        }
        void Promise.resolve(onSend(message))
          .then(() => {
            postToParent({ type: 'onerag:accepted', requestId }, event.origin);
          })
          .catch(() => {
            postToParent({
              type: 'onerag:error',
              requestId,
              error: 'send_failed',
            }, event.origin);
          });
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [allowedOrigins, enabled, loading, onSend, onStop, postToParent]);
}
