import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatSessionSidebar } from '../ChatSessionSidebar';
import type { ChatMessage } from '../../../types';

const STORAGE_KEY = 'onerag_chat_sessions';

function makeMessage(content: string): ChatMessage {
  return {
    id: 'msg-1',
    role: 'user',
    content,
    timestamp: '2026-06-07T00:00:00.000Z',
  };
}

describe('ChatSessionSidebar', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('delegates session selection without mutating storage directly', async () => {
    const onSelectSession = vi.fn();
    localStorage.setItem('chatSessionId', 'active-session');

    const { rerender } = render(
      <ChatSessionSidebar
        sessionId="previous-session"
        messages={[makeMessage('Previous chat')]}
        onNewSession={vi.fn()}
        onSelectSession={onSelectSession}
      />
    );
    expect(await screen.findByText('Previous chat')).toBeInTheDocument();

    rerender(
      <ChatSessionSidebar
        sessionId="active-session"
        messages={[]}
        onNewSession={vi.fn()}
        onSelectSession={onSelectSession}
      />
    );

    fireEvent.click(await screen.findByText('Previous chat'));

    expect(onSelectSession).toHaveBeenCalledWith('previous-session');
  });

  it('does not resurrect a deleted active session during empty-message sync', () => {
    const onNewSession = vi.fn();
    const initialSessions = [
      {
        id: 'active-session',
        title: 'Active chat',
        updatedAt: '2026-06-07T00:00:00.000Z',
        messageCount: 1,
      },
    ];
    localStorage.setItem(STORAGE_KEY, JSON.stringify(initialSessions));

    const { rerender } = render(
      <ChatSessionSidebar
        sessionId="active-session"
        messages={[makeMessage('hello')]}
        onNewSession={onNewSession}
        onSelectSession={vi.fn()}
      />
    );

    fireEvent.click(screen.getByTitle('삭제'));

    expect(onNewSession).toHaveBeenCalled();
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')).toEqual([]);

    rerender(
      <ChatSessionSidebar
        sessionId="active-session"
        messages={[]}
        onNewSession={onNewSession}
        onSelectSession={vi.fn()}
      />
    );

    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')).toEqual([]);
  });
});
