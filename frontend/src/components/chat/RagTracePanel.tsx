import React, { useMemo } from 'react';
import { Activity, Bot, Database, FileSearch, Gauge, History, MessageSquareText, Timer } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { ApiLog, ChatMessage, Source as SourceType } from '../../types';

interface RagTracePanelProps {
  messages: ChatMessage[];
  apiLogs: ApiLog[];
  selectedChunk?: SourceType | null;
  isStreaming?: boolean;
}

interface ChatResponseLogData {
  model_info?: {
    provider?: string;
    model?: string;
  };
  processing_time?: number;
  tokens_used?: number;
}

function asChatResponseLogData(data: unknown): ChatResponseLogData {
  return data && typeof data === 'object' ? data as ChatResponseLogData : {};
}

function formatValue(value: unknown) {
  if (value === undefined || value === null || value === '') return 'N/A';
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : String(value);
  if (typeof value === 'boolean') return value ? '예' : '아니오';
  return String(value);
}

function latestAssistantMessage(messages: ChatMessage[]) {
  return [...messages].reverse().find((message) => message.role === 'assistant');
}

function latestUserMessage(messages: ChatMessage[]) {
  return [...messages].reverse().find((message) => message.role === 'user');
}

export function RagTracePanel({ messages, apiLogs, selectedChunk, isStreaming }: RagTracePanelProps) {
  const assistantMessage = useMemo(() => latestAssistantMessage(messages), [messages]);
  const userMessage = useMemo(() => latestUserMessage(messages), [messages]);
  const sources = assistantMessage?.sources ?? [];
  const latestResponseLog = useMemo(
    () => [...apiLogs].reverse().find((log) => log.type === 'response' && log.endpoint === '/api/chat'),
    [apiLogs]
  );

  const responseData = asChatResponseLogData(latestResponseLog?.data);
  const modelInfo = responseData.model_info;
  const processingTime = responseData.processing_time ?? latestResponseLog?.duration;
  const tokensUsed = responseData.tokens_used;

  return (
    <aside className="hidden xl:flex w-80 shrink-0 flex-col border-l border-border/60 bg-background/85 backdrop-blur-sm">
      <div className="p-4 border-b border-border/60">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-bold tracking-tight flex items-center gap-2">
              <Activity className="w-4 h-4 text-primary" />
              RAG Trace
            </h2>
            <p className="text-xs text-muted-foreground mt-1">검색·재순위·생성 흐름을 확인합니다</p>
          </div>
          <Badge variant={isStreaming ? 'default' : 'secondary'} className="rounded-full">
            {isStreaming ? 'Streaming' : 'Ready'}
          </Badge>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <Card className="rounded-2xl border-border/60 bg-card/60">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <MessageSquareText className="w-4 h-4 text-primary" />
              최근 질문
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground line-clamp-4">
              {userMessage?.content || '아직 질문이 없습니다.'}
            </p>
          </CardContent>
        </Card>

        <div className="grid grid-cols-2 gap-3">
          <TraceMetric icon={FileSearch} label="Sources" value={sources.length} />
          <TraceMetric icon={Timer} label="Latency" value={processingTime ? `${processingTime}ms` : 'N/A'} />
          <TraceMetric icon={Gauge} label="Tokens" value={formatValue(tokensUsed)} />
          <TraceMetric icon={Bot} label="Model" value={formatValue(modelInfo?.model ?? modelInfo?.provider)} />
        </div>

        <Card className="rounded-2xl border-border/60 bg-card/60">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Database className="w-4 h-4 text-primary" />
              검색된 문서 Top-K
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {sources.length === 0 ? (
              <p className="text-sm text-muted-foreground">아직 표시할 출처가 없습니다.</p>
            ) : (
              sources.slice(0, 5).map((source, index) => (
                <div
                  key={`${source.id ?? source.document ?? 'source'}-${index}`}
                  className={cn(
                    'rounded-xl border p-3 text-xs space-y-1',
                    selectedChunk?.id === source.id
                      ? 'border-primary/50 bg-primary/10'
                      : 'border-border/50 bg-background/60'
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-semibold truncate">#{index + 1} {source.document || source.id || 'Unknown'}</p>
                    {typeof source.relevance === 'number' && (
                      <Badge variant="secondary" className="text-[10px] rounded-full">
                        {(source.relevance * 100).toFixed(1)}%
                      </Badge>
                    )}
                  </div>
                  <p className="text-muted-foreground line-clamp-2">
                    {source.content_preview || '본문 미리보기가 없습니다.'}
                  </p>
                  <div className="flex flex-wrap gap-1 pt-1 text-[10px] text-muted-foreground">
                    <span>page: {formatValue(source.page)}</span>
                    <span>chunk: {formatValue(source.chunk)}</span>
                    <span>rerank: {formatValue(source.rerank_method)}</span>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="rounded-2xl border-border/60 bg-card/60">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <History className="w-4 h-4 text-primary" />
              API Timeline
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {apiLogs.slice(-6).map((log) => (
              <div key={log.id} className="flex items-center justify-between gap-2 rounded-xl bg-background/60 border border-border/40 px-3 py-2 text-xs">
                <div className="min-w-0">
                  <p className="font-semibold truncate">{log.method} {log.endpoint}</p>
                  <p className="text-muted-foreground">{new Date(log.timestamp).toLocaleTimeString()}</p>
                </div>
                <Badge variant={log.type === 'request' ? 'outline' : 'secondary'} className="rounded-full">
                  {log.status ?? log.type}
                </Badge>
              </div>
            ))}
            {apiLogs.length === 0 && <p className="text-sm text-muted-foreground">API 로그가 없습니다.</p>}
          </CardContent>
        </Card>
      </div>
    </aside>
  );
}

function TraceMetric({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: React.ReactNode }) {
  return (
    <Card className="rounded-2xl border-border/60 bg-card/60">
      <CardContent className="p-3">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Icon className="w-4 h-4" />
          <span className="text-[11px] font-medium">{label}</span>
        </div>
        <p className="mt-2 text-sm font-bold truncate">{value}</p>
      </CardContent>
    </Card>
  );
}
