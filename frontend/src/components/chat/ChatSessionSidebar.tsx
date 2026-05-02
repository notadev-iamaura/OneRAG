import React, { useEffect, useMemo, useState } from 'react';
import { MessageSquare, Pencil, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { ChatMessage } from '../../types';

interface StoredChatSession {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
}

interface ChatSessionSidebarProps {
  sessionId: string;
  messages: ChatMessage[];
  onNewSession: () => Promise<void> | void;
}

const STORAGE_KEY = 'onerag_chat_sessions';

function readSessions(): StoredChatSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeSessions(sessions: StoredChatSession[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(0, 50)));
}

function createDefaultTitle(messages: ChatMessage[]) {
  const firstUserMessage = messages.find((message) => message.role === 'user' && message.content?.trim());
  if (!firstUserMessage) return '새 대화';
  const title = firstUserMessage.content.trim().replace(/\s+/g, ' ');
  return title.length > 28 ? `${title.slice(0, 28)}...` : title;
}

export function ChatSessionSidebar({ sessionId, messages, onNewSession }: ChatSessionSidebarProps) {
  const [sessions, setSessions] = useState<StoredChatSession[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');

  useEffect(() => {
    setSessions(readSessions());
  }, []);

  useEffect(() => {
    if (!sessionId) return;

    setSessions((previous) => {
      const now = new Date().toISOString();
      const existing = previous.find((session) => session.id === sessionId);
      const nextSession: StoredChatSession = {
        id: sessionId,
        title: existing?.title && existing.title !== '새 대화'
          ? existing.title
          : createDefaultTitle(messages),
        updatedAt: now,
        messageCount: messages.length,
      };

      const next = [
        nextSession,
        ...previous.filter((session) => session.id !== sessionId),
      ].sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());

      writeSessions(next);
      return next;
    });
  }, [sessionId, messages]);

  const sortedSessions = useMemo(
    () => [...sessions].sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()),
    [sessions]
  );

  const handleSelectSession = (targetSessionId: string) => {
    if (targetSessionId === sessionId) return;
    localStorage.setItem('chatSessionId', targetSessionId);
    window.location.reload();
  };

  const handleDeleteSession = (targetSessionId: string) => {
    const next = sessions.filter((session) => session.id !== targetSessionId);
    setSessions(next);
    writeSessions(next);

    if (targetSessionId === sessionId) {
      localStorage.removeItem('chatSessionId');
      onNewSession();
    }
  };

  const startEditing = (session: StoredChatSession) => {
    setEditingId(session.id);
    setEditingTitle(session.title);
  };

  const saveTitle = () => {
    if (!editingId) return;
    const next = sessions.map((session) =>
      session.id === editingId
        ? { ...session, title: editingTitle.trim() || '새 대화' }
        : session
    );
    setSessions(next);
    writeSessions(next);
    setEditingId(null);
    setEditingTitle('');
  };

  return (
    <aside className="hidden lg:flex w-72 shrink-0 flex-col border-r border-border/60 bg-background/80 backdrop-blur-sm">
      <div className="p-4 border-b border-border/60 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-bold tracking-tight">대화방</h2>
            <p className="text-xs text-muted-foreground">최근 대화를 빠르게 전환합니다</p>
          </div>
          <Button size="icon" variant="outline" className="rounded-xl" onClick={onNewSession} title="새 대화">
            <Plus className="w-4 h-4" />
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {sortedSessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-center text-muted-foreground h-40 gap-2">
            <MessageSquare className="w-8 h-8 opacity-50" />
            <p className="text-sm">저장된 대화가 없습니다</p>
          </div>
        ) : (
          sortedSessions.map((session) => {
            const isActive = session.id === sessionId;
            const isEditing = editingId === session.id;

            return (
              <div
                key={session.id}
                className={cn(
                  'group rounded-2xl border p-3 transition-all cursor-pointer',
                  isActive
                    ? 'border-primary/40 bg-primary/10 shadow-sm'
                    : 'border-border/50 bg-card/40 hover:bg-muted/60'
                )}
                onClick={() => !isEditing && handleSelectSession(session.id)}
              >
                <div className="flex items-start gap-2">
                  <MessageSquare className="w-4 h-4 mt-0.5 text-primary/70 shrink-0" />
                  <div className="min-w-0 flex-1">
                    {isEditing ? (
                      <Input
                        value={editingTitle}
                        onChange={(event) => setEditingTitle(event.target.value)}
                        onBlur={saveTitle}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') saveTitle();
                          if (event.key === 'Escape') setEditingId(null);
                        }}
                        autoFocus
                        className="h-8 text-sm rounded-xl"
                        onClick={(event) => event.stopPropagation()}
                      />
                    ) : (
                      <p className="truncate text-sm font-semibold text-foreground">{session.title}</p>
                    )}
                    <p className="mt-1 text-xs text-muted-foreground">
                      메시지 {session.messageCount}개 · {new Date(session.updatedAt).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 rounded-lg"
                      onClick={(event) => {
                        event.stopPropagation();
                        startEditing(session);
                      }}
                      title="이름 변경"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 rounded-lg hover:text-destructive"
                      onClick={(event) => {
                        event.stopPropagation();
                        handleDeleteSession(session.id);
                      }}
                      title="삭제"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
