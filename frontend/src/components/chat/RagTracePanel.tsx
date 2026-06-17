import React, { useMemo } from 'react';
import { Activity, Bot, Database, FileSearch, Gauge, History, MessageSquareText, Timer } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { ApiLog, ChatMessage, Source as SourceType } from '../../types';
import { formatModelDisplayName } from './formatModelDisplayName';
import { useMenuMessages } from '../../i18n/useMenuLocale';
import type { MenuMessages } from '../../i18n/menuMessages';

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

function formatValue(value: unknown, messages: MenuMessages) {
  if (value === undefined || value === null || value === '') return 'N/A';
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : String(value);
  if (typeof value === 'boolean') return value ? messages.ragTrace.booleanTrue : messages.ragTrace.booleanFalse;
  return String(value);
}

function latestAssistantMessage(messages: ChatMessage[]) {
  return [...messages].reverse().find((message) => message.role === 'assistant');
}

function latestUserMessage(messages: ChatMessage[]) {
  return [...messages].reverse().find((message) => message.role === 'user');
}

export function RagTracePanel({ messages, apiLogs, selectedChunk, isStreaming }: RagTracePanelProps) {
  // i18n: prop의 messages(채팅 메시지 배열)와 이름 충돌을 피하기 위해 별칭(i18n)으로 받는다.
  const { messages: i18n } = useMenuMessages();
  const assistantMessage = useMemo(() => latestAssistantMessage(messages), [messages]);
  const userMessage = useMemo(() => latestUserMessage(messages), [messages]);
  const sources = assistantMessage?.sources ?? [];
  const latestResponseLog = useMemo(
    () => [...apiLogs].reverse().find((log) => log.type === 'response' && log.endpoint === '/api/chat'),
    [apiLogs]
  );

  const responseData = asChatResponseLogData(latestResponseLog?.data);
  // 메트릭은 "현재 표시 중인 메시지" 값을 우선하고, 없으면 전역 로그를 보조로 사용한다.
  // 이렇게 하면 방을 전환했을 때 이전 방의 마지막 응답 로그가 새 방 메트릭을 덮어쓰지 않는다.
  const modelInfo = assistantMessage?.model_info ?? responseData.model_info;
  const processingTime = assistantMessage?.processing_time ?? responseData.processing_time ?? latestResponseLog?.duration;
  const tokensUsed = assistantMessage?.tokens_used ?? responseData.tokens_used;

  return (
    <aside className="hidden xl:flex w-80 shrink-0 flex-col border-l border-border/60 bg-background/85 backdrop-blur-sm">
      <div className="p-4 border-b border-border/60">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-bold tracking-tight flex items-center gap-2">
              <Activity className="w-4 h-4 text-primary" />
              RAG Trace
            </h2>
            <p className="text-xs text-muted-foreground mt-1">{i18n.ragTrace.flowDescription}</p>
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
              {i18n.ragTrace.recentQuestion}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground line-clamp-4">
              {userMessage?.content || i18n.ragTrace.noQuestionYet}
            </p>
          </CardContent>
        </Card>

        <div className="grid grid-cols-2 gap-3">
          <TraceMetric icon={FileSearch} label="Sources" value={sources.length} />
          <TraceMetric icon={Timer} label="Latency" value={processingTime ? `${processingTime}ms` : 'N/A'} />
          <TraceMetric icon={Gauge} label="Tokens" value={formatValue(tokensUsed, i18n)} />
          <TraceMetric icon={Bot} label="Model" value={formatValue(formatModelDisplayName(modelInfo?.model) ?? modelInfo?.provider, i18n)} />
        </div>

        <Card className="rounded-2xl border-border/60 bg-card/60">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Database className="w-4 h-4 text-primary" />
              {i18n.ragTrace.topKDocuments}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {sources.length === 0 ? (
              <p className="text-sm text-muted-foreground">{i18n.ragTrace.noSourcesYet}</p>
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
                    {source.content_preview || i18n.ragTrace.noContentPreview}
                  </p>
                  <div className="flex flex-wrap gap-1 pt-1 text-[10px] text-muted-foreground">
                    <span>page: {formatValue(source.page, i18n)}</span>
                    <span>chunk: {formatValue(source.chunk, i18n)}</span>
                    <span>rerank: {formatValue(source.rerank_method, i18n)}</span>
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
            {apiLogs.length === 0 && <p className="text-sm text-muted-foreground">{i18n.ragTrace.noApiLogs}</p>}
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
