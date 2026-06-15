/**
 * RagTracePanel 컴포넌트 테스트
 *
 * #47 회귀 보호: 트레이스 메트릭은 "현재 표시 중인 메시지" 값을 우선하고,
 * 전역 API 로그는 보조로만 사용해야 한다. 그래야 방을 전환했을 때 이전 방의
 * 마지막 응답 로그가 새 방 메트릭을 덮어쓰지 않는다.
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { RagTracePanel } from '../RagTracePanel';
import type { ApiLog, ChatMessage } from '../../../types';

const makeStaleLog = (): ApiLog => ({
  id: 'log-stale',
  timestamp: '2026-01-01T10:00:00Z',
  type: 'response',
  method: 'POST',
  endpoint: '/api/chat',
  data: {
    processing_time: 9999,
    tokens_used: 8888,
    model_info: { provider: 'stale', model: 'stale-model' },
  },
  status: 200,
  duration: 7777,
});

describe('RagTracePanel', () => {
  it('메시지에 트레이스가 있으면 전역 로그가 아닌 메시지 값을 우선 표시한다', () => {
    const messages: ChatMessage[] = [
      { id: 'u1', role: 'user', content: '질문', timestamp: '2026-06-15T00:00:00Z' },
      {
        id: 'a1',
        role: 'assistant',
        content: '답변',
        timestamp: '2026-06-15T00:00:01Z',
        processing_time: 1234,
        tokens_used: 42,
        model_info: { provider: 'google', model: 'gemini-2.0' },
      },
    ];

    // 이전 방의 stale 로그가 남아 있어도 메시지 값이 우선되어야 한다.
    render(<RagTracePanel messages={messages} apiLogs={[makeStaleLog()]} />);

    expect(screen.getByText('1234ms')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('gemini-2.0')).toBeInTheDocument();
    // stale 로그 값은 표시되지 않아야 한다.
    expect(screen.queryByText('9999ms')).not.toBeInTheDocument();
    expect(screen.queryByText('8,888')).not.toBeInTheDocument();
    expect(screen.queryByText('stale-model')).not.toBeInTheDocument();
  });

  it('메시지에 트레이스가 없으면 전역 로그를 보조로 사용한다', () => {
    const messages: ChatMessage[] = [
      { id: 'u1', role: 'user', content: '질문', timestamp: '2026-06-15T00:00:00Z' },
      { id: 'a1', role: 'assistant', content: '답변', timestamp: '2026-06-15T00:00:01Z' },
    ];

    const log: ApiLog = {
      id: 'log-1',
      timestamp: '2026-06-15T00:00:02Z',
      type: 'response',
      method: 'POST',
      endpoint: '/api/chat',
      data: { processing_time: 555, tokens_used: 12, model_info: { provider: 'openai', model: 'gpt-4o' } },
      status: 200,
      duration: 600,
    };

    render(<RagTracePanel messages={messages} apiLogs={[log]} />);

    expect(screen.getByText('555ms')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('gpt-4o')).toBeInTheDocument();
  });

  it('apiLogs가 비어 있으면(방 전환 후 로그 초기화) 메시지에 트레이스가 없을 때 N/A로 표시한다', () => {
    const messages: ChatMessage[] = [
      { id: 'u1', role: 'user', content: '질문', timestamp: '2026-06-15T00:00:00Z' },
      { id: 'a1', role: 'assistant', content: '답변', timestamp: '2026-06-15T00:00:01Z' },
    ];

    render(<RagTracePanel messages={messages} apiLogs={[]} />);

    // Latency/Tokens/Model 모두 N/A (stale 로그 잔존 없음)
    expect(screen.getAllByText('N/A').length).toBeGreaterThanOrEqual(2);
  });
});
