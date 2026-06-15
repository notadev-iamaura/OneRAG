// useEmbedBridge 단위 테스트.
// origin 화이트리스트 거부/허용, ping→pong, send 검증(빈/초과/busy), focus 동작을 검증한다.
import { render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useEmbedBridge } from '../useEmbedBridge';

// 훅을 구동하기 위한 테스트 하네스 컴포넌트.
function BridgeHarness({
  enabled = true,
  loading = false,
  isStreaming = false,
  messageCount = 0,
  onSend = vi.fn(),
  onStop = vi.fn(),
}: {
  enabled?: boolean;
  loading?: boolean;
  isStreaming?: boolean;
  messageCount?: number;
  onSend?: (message: string) => Promise<void> | void;
  onStop?: () => void;
}) {
  useEmbedBridge({
    enabled,
    loading,
    isStreaming,
    messageCount,
    onSend,
    onStop,
  });

  return <textarea aria-label="chat input" />;
}

describe('useEmbedBridge', () => {
  const allowedOrigin = 'https://customer.example.com';
  let postMessageSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    window.RUNTIME_CONFIG = {
      ...(window.RUNTIME_CONFIG || {}),
      EMBED_ALLOWED_ORIGINS: [allowedOrigin],
    };
    postMessageSpy = vi.spyOn(window.parent, 'postMessage').mockImplementation(() => undefined);
  });

  afterEach(() => {
    postMessageSpy.mockRestore();
  });

  it('설정된 부모 origin으로 ready/status/resize 이벤트를 전송한다', () => {
    render(<BridgeHarness loading isStreaming messageCount={2} />);

    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        source: 'onerag-embed',
        version: 1,
        type: 'onerag:ready',
        loading: true,
        streaming: true,
        messageCount: 2,
      }),
      allowedOrigin,
    );
    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        source: 'onerag-embed',
        type: 'onerag:status',
      }),
      allowedOrigin,
    );
    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        source: 'onerag-embed',
        type: 'onerag:resize',
      }),
      allowedOrigin,
    );
  });

  it('허용 origin이 미설정이면 현재 origin으로 이벤트를 전송한다', () => {
    window.RUNTIME_CONFIG = {
      ...(window.RUNTIME_CONFIG || {}),
      EMBED_ALLOWED_ORIGINS: [],
    };

    render(<BridgeHarness />);

    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        source: 'onerag-embed',
        type: 'onerag:ready',
      }),
      window.location.origin,
    );
  });

  it('허용되지 않은 origin의 ping/send 명령은 무시하고, 허용 origin만 수락한다', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined);
    render(<BridgeHarness onSend={onSend} />);
    postMessageSpy.mockClear();

    // 화이트리스트 외 origin → 완전 무시
    window.dispatchEvent(new MessageEvent('message', {
      origin: 'https://evil.example.com',
      data: {
        source: 'onerag-host',
        type: 'onerag:send',
        requestId: 'blocked',
        message: 'Do not send',
      },
    }));

    expect(onSend).not.toHaveBeenCalled();
    expect(postMessageSpy).not.toHaveBeenCalled();

    // 허용 origin의 ping → pong 응답
    window.dispatchEvent(new MessageEvent('message', {
      origin: allowedOrigin,
      data: {
        source: 'onerag-host',
        type: 'onerag:ping',
        requestId: 'ping-1',
      },
    }));

    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        source: 'onerag-embed',
        type: 'onerag:pong',
        requestId: 'ping-1',
      }),
      allowedOrigin,
    );

    // 허용 origin의 send → 트림 후 전송 + accepted 응답
    window.dispatchEvent(new MessageEvent('message', {
      origin: allowedOrigin,
      data: {
        source: 'onerag-host',
        type: 'onerag:send',
        requestId: 'send-1',
        message: '  Host initiated question  ',
      },
    }));

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledWith('Host initiated question');
    });
    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        source: 'onerag-embed',
        type: 'onerag:accepted',
        requestId: 'send-1',
      }),
      allowedOrigin,
    );
  });

  it("'null' origin 메시지는 거부한다(sandbox 우회 차단)", () => {
    const onSend = vi.fn();
    render(<BridgeHarness onSend={onSend} />);
    postMessageSpy.mockClear();

    window.dispatchEvent(new MessageEvent('message', {
      origin: 'null',
      data: {
        source: 'onerag-host',
        type: 'onerag:send',
        requestId: 'null-origin',
        message: 'Host initiated question',
      },
    }));

    expect(onSend).not.toHaveBeenCalled();
    expect(postMessageSpy).not.toHaveBeenCalled();
  });

  it('응답 로딩 중에는 host send 명령에 busy를 반환한다', () => {
    const onSend = vi.fn();
    render(<BridgeHarness loading onSend={onSend} />);
    postMessageSpy.mockClear();

    window.dispatchEvent(new MessageEvent('message', {
      origin: allowedOrigin,
      data: {
        source: 'onerag-host',
        type: 'onerag:send',
        requestId: 'send-busy',
        message: 'Host initiated question',
      },
    }));

    expect(onSend).not.toHaveBeenCalled();
    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        source: 'onerag-embed',
        type: 'onerag:error',
        requestId: 'send-busy',
        error: 'busy',
      }),
      allowedOrigin,
    );
  });

  it('빈 메시지 등 잘못된 send 페이로드는 onSend 호출 없이 거부한다', () => {
    const onSend = vi.fn();
    render(<BridgeHarness onSend={onSend} />);
    postMessageSpy.mockClear();

    window.dispatchEvent(new MessageEvent('message', {
      origin: allowedOrigin,
      data: {
        source: 'onerag-host',
        type: 'onerag:send',
        requestId: 'send-empty',
        message: '   ',
      },
    }));

    expect(onSend).not.toHaveBeenCalled();
    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        source: 'onerag-embed',
        type: 'onerag:error',
        requestId: 'send-empty',
        error: 'invalid_message',
      }),
      allowedOrigin,
    );
  });

  it('1000자를 초과하는 send 메시지는 invalid_message로 거부한다', () => {
    const onSend = vi.fn();
    render(<BridgeHarness onSend={onSend} />);
    postMessageSpy.mockClear();

    window.dispatchEvent(new MessageEvent('message', {
      origin: allowedOrigin,
      data: {
        source: 'onerag-host',
        type: 'onerag:send',
        requestId: 'send-too-long',
        message: 'x'.repeat(1001),
      },
    }));

    expect(onSend).not.toHaveBeenCalled();
    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        source: 'onerag-embed',
        type: 'onerag:error',
        requestId: 'send-too-long',
        error: 'invalid_message',
      }),
      allowedOrigin,
    );
  });

  it('허용 origin의 focus 명령에 입력창을 포커스하고 accepted를 반환한다', () => {
    render(<BridgeHarness />);
    postMessageSpy.mockClear();

    window.dispatchEvent(new MessageEvent('message', {
      origin: allowedOrigin,
      data: {
        source: 'onerag-host',
        type: 'onerag:focus',
        requestId: 'focus-1',
      },
    }));

    expect(document.activeElement).toHaveAttribute('aria-label', 'chat input');
    expect(postMessageSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        source: 'onerag-embed',
        type: 'onerag:accepted',
        requestId: 'focus-1',
      }),
      allowedOrigin,
    );
  });
});
