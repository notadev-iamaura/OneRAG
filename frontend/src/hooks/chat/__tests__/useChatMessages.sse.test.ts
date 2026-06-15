/**
 * useChatMessages SSE 폴백/타이프라이터 테스트 (#46, #53)
 *
 * 검증 항목:
 *   #46 - WS 미연결 시 SSE(chatAPI.streamMessage)가 호출되고, SSE 성공 시 통짜 REST는 호출되지 않음
 *   #46 - SSE 실패 시 placeholder 제거 후 REST 폴백
 *   #46 - 중단(abort) 시 REST 폴백을 하지 않고 빈 placeholder를 제거
 *   #53 - chunk 도착 시 타이프라이터로 점진 렌더 + done 후 sources 부착 + RagProgress 전이
 */
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach, Mock } from 'vitest';
import { useChatMessages } from '../useChatMessages';
import { chatAPI } from '../../../services/api';
import type {
  StreamChatClientOptions,
  StreamChunkEvent,
  StreamDoneEvent,
} from '../../../types/chatStreaming';

// Feature Flag: 스트리밍 활성
const mockFeatureState = vi.hoisted(() => ({ streamingEnabled: true }));

// WS 스트리밍 훅 mock — WS 미연결 상태로 둬서 SSE 경로를 강제한다.
// useChatStreamingCore의 실제 시그니처와 동일한 형태로 stub을 만든다.
const mockStreaming = vi.hoisted(() => ({
  connect: vi.fn().mockResolvedValue(undefined),
  disconnect: vi.fn(),
  sendStreamingMessage: vi.fn(),
  isConnected: false,
  streamingState: 'idle' as const,
  streamingMessage: null,
}));

vi.mock('../../../services/api', () => ({
  chatAPI: {
    sendMessage: vi.fn(),
    getSessionInfo: vi.fn(),
    streamMessage: vi.fn(),
  },
}));

vi.mock('../../../core/useFeature', () => ({
  useIsFeatureEnabled: vi.fn(() => mockFeatureState.streamingEnabled),
}));

vi.mock('../../../utils/logger', () => ({
  logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

vi.mock('../useChatStreaming', () => ({
  useChatStreaming: () => mockStreaming,
}));

/**
 * streamMessage 시뮬레이션: metadata → chunk* → done 순으로 콜백을 호출한다.
 */
function makeStreamMessageMock(chunks: string[], sessionId = 'sse-session-123') {
  return async (_message: string, _sid?: string, options?: StreamChatClientOptions) => {
    options?.onEvent?.({
      event: 'metadata',
      session_id: sessionId,
      search_results: 3,
      reranking_applied: true,
    });
    for (let i = 0; i < chunks.length; i++) {
      const chunkEvent: StreamChunkEvent = { event: 'chunk', data: chunks[i], chunk_index: i };
      options?.onEvent?.(chunkEvent);
      options?.onChunk?.(chunkEvent);
    }
    const doneEvent: StreamDoneEvent = {
      event: 'done',
      session_id: sessionId,
      message_id: 'msg-sse-001',
      total_chunks: chunks.length,
      tokens_used: 42,
      processing_time: 0.5,
      sources: [{ id: 1, document: 'doc.pdf', relevance: 0.9, content_preview: 'p' }],
    };
    options?.onEvent?.(doneEvent);
    options?.onDone?.(doneEvent);
    return [];
  };
}

// 안정적인 빈 배열 참조: 매 렌더마다 새 배열을 넘기면 initialMessages 동기화 useEffect가
// 무한 재렌더를 유발하므로(setMessages([]) → 새 [] → 재렌더), 단일 참조를 재사용한다.
const STABLE_EMPTY_MESSAGES: never[] = [];

describe('useChatMessages — SSE 폴백/타이프라이터 (#46, #53)', () => {
  const mockSessionId = 'test-session-id';
  const defaultProps = {
    sessionId: mockSessionId,
    initialMessages: STABLE_EMPTY_MESSAGES,
    showToast: vi.fn(),
    synchronizeSessionId: vi.fn(),
    setApiLogs: vi.fn(),
    setSessionInfo: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockFeatureState.streamingEnabled = true;
    mockStreaming.isConnected = false;
    mockStreaming.streamingMessage = null;
    // clearAllMocks가 호출 기록을 비우므로 connect 구현을 재설정한다(undefined 반환 시 .catch 크래시 방지).
    mockStreaming.connect.mockResolvedValue(undefined);
  });

  afterEach(() => {
    // restoreAllMocks는 hoisted mock 구현을 제거하므로 사용하지 않는다.
    // 보류 중인 타이프라이터 타이머가 다음 테스트로 누수되지 않도록 정리한다.
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  // #46: WS 미연결 → SSE 사용, 통짜 REST 미사용
  it('WS 미연결 시 SSE(streamMessage)를 호출하고 통짜 REST는 호출하지 않는다', async () => {
    (chatAPI.streamMessage as Mock).mockImplementation(makeStreamMessageMock(['안녕', '하세요']));

    const { result } = renderHook(() => useChatMessages(defaultProps));

    // 렌더 커밋 이후에 fake timers를 활성화한다(렌더 전에 켜면 React 스케줄러가 멈춰 커밋이 안 됨).
    vi.useFakeTimers();

    act(() => {
      result.current.setInput('테스트 메시지');
    });

    await act(async () => {
      // handleSend는 visualDrain(타이프라이터 완료)을 기다리므로,
      // await하기 전에 타이머를 함께 진행시켜 데드락을 피한다.
      const sendPromise = result.current.handleSend();
      await vi.advanceTimersByTimeAsync(500);
      await sendPromise;
    });

    expect(chatAPI.streamMessage).toHaveBeenCalledTimes(1);
    expect(chatAPI.streamMessage).toHaveBeenCalledWith(
      '테스트 메시지',
      mockSessionId,
      expect.objectContaining({
        onEvent: expect.any(Function),
        onChunk: expect.any(Function),
        onDone: expect.any(Function),
        onError: expect.any(Function),
        signal: expect.any(AbortSignal),
      })
    );
    expect(chatAPI.sendMessage).not.toHaveBeenCalled();
  });

  // #53: 청크 점진 렌더 + done 후 최종 내용/소스/트레이스 부착
  it('SSE 청크를 누적해 최종 메시지에 내용·소스·트레이스를 부착한다', async () => {
    (chatAPI.streamMessage as Mock).mockImplementation(makeStreamMessageMock(['안녕', '하세요!']));

    const { result } = renderHook(() => useChatMessages(defaultProps));

    vi.useFakeTimers();

    act(() => {
      result.current.setInput('질문');
    });

    await act(async () => {
      const sendPromise = result.current.handleSend();
      await vi.advanceTimersByTimeAsync(1000);
      await sendPromise;
    });

    const messages = result.current.messages;
    // user + assistant(placeholder가 최종 내용으로 채워짐)
    expect(messages).toHaveLength(2);
    const assistant = messages[1];
    expect(assistant.role).toBe('assistant');
    expect(assistant.content).toBe('안녕하세요!');
    expect(assistant.sources).toHaveLength(1);
    expect(assistant.processing_time).toBe(0.5);
    expect(assistant.tokens_used).toBe(42);
    // RagProgress가 완료 단계로 전이
    expect(result.current.ragProgress.phase).toBe('completed');
    expect(result.current.isSseStreaming).toBe(false);
  });

  // #46: SSE 실패 시 placeholder 제거 후 REST 폴백
  it('SSE 실패 시 placeholder를 제거하고 REST로 폴백한다', async () => {
    (chatAPI.streamMessage as Mock).mockRejectedValue(new Error('SSE 연결 실패'));
    (chatAPI.sendMessage as Mock).mockResolvedValue({
      data: {
        session_id: mockSessionId,
        answer: 'REST 응답',
        sources: [],
        tokens_used: 5,
        processing_time: 0.2,
        model_info: { provider: 'test', model: 'm' },
      },
      status: 200,
    });
    (chatAPI.getSessionInfo as Mock).mockResolvedValue({ data: {} });

    const { result } = renderHook(() => useChatMessages(defaultProps));

    act(() => {
      result.current.setInput('실패 케이스');
    });

    await act(async () => {
      await result.current.handleSend();
    });

    expect(chatAPI.streamMessage).toHaveBeenCalledTimes(1);
    expect(chatAPI.sendMessage).toHaveBeenCalledTimes(1);

    const messages = result.current.messages;
    // user + REST 어시스턴트 응답 (SSE placeholder는 제거됨 → 빈 말풍선 없음)
    expect(messages).toHaveLength(2);
    expect(messages[1].content).toBe('REST 응답');
  });

  // #46: 중단(abort) 시 REST 폴백을 하지 않고 빈 placeholder를 제거한다
  it('중단 시 REST 폴백을 하지 않고 빈 placeholder를 제거한다', async () => {
    // streamMessage가 abort 시그널을 받으면 AbortError를 던지도록 시뮬레이션
    (chatAPI.streamMessage as Mock).mockImplementation(
      (_m: string, _s?: string, options?: StreamChatClientOptions) =>
        new Promise((_resolve, reject) => {
          options?.signal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'));
          });
        })
    );

    const { result } = renderHook(() => useChatMessages(defaultProps));

    act(() => {
      result.current.setInput('중단할 메시지');
    });

    // handleSend는 SSE 응답을 기다리며 보류된다.
    let sendPromise: Promise<void> = Promise.resolve();
    act(() => {
      sendPromise = result.current.handleSend();
    });

    // 사용자가 중단
    act(() => {
      result.current.handleStop();
    });

    await act(async () => {
      await sendPromise;
    });

    // REST 폴백이 호출되지 않아야 한다(통짜 재생성 방지)
    expect(chatAPI.sendMessage).not.toHaveBeenCalled();
    // 빈 placeholder는 제거되어 user 메시지만 남는다.
    const contents = result.current.messages.map((m) => m.content);
    expect(contents).toEqual(['중단할 메시지']);
  });
});
