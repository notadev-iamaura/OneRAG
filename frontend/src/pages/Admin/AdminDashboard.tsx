/**
 * 관리자 대시보드 메인 페이지
 * 프로덕션 운영을 위한 모니터링, 통계, 관리 기능 제공
 * 향상된 기능: 실시간 모니터링, 세션 관리, WebSocket 지원
 */

import React, { useState, useEffect, useCallback } from 'react';
import { logger } from '../../utils/logger';
import { COLORS } from '../../config/colors';
import {
  RotateCw,
  Play,
  Trash2,
  Download,
  Wrench,
  Eye,
  Users,
  FileText,
  BarChart3,
  Home,
  Settings,
  Brain,
  Search,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { adminService } from '../../services/adminService';
import PromptManager from '../../components/PromptManager';
import { useToast } from '@/hooks/use-toast';
import { useMenuMessages } from '../../i18n/useMenuLocale';
import { format, formatDate } from '../../i18n/format';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import SettingsPage from './SettingsPage';

interface SystemStatus {
  timestamp: string;
  services: {
    qdrant: { status: string; message: string; responseTime?: string };
    dynamodb: { status: string; message: string; responseTime?: string };
    llm: { status: string; message: string; responseTime?: string };
  };
}

interface Metrics {
  period: string;
  totalSessions: number;
  totalQueries: number;
  avgResponseTime: number;
  timeSeries: Array<{
    date: string;
    sessions: number;
    queries: number;
    avgResponseTime: number;
  }>;
}

interface KeywordData {
  keywords: Array<{
    rank: number;
    keyword: string;
    count: number;
  }>;
}

interface ChunkData {
  chunks: Array<{
    rank: number;
    chunkName: string;
    count: number;
  }>;
}

interface CountryData {
  countries: Array<{
    country: string;
    count: number;
  }>;
}

interface ChatLog {
  id: string;
  chatId: string;
  message: string;
  timestamp: string;
  responseTime: number;
  source: string;
  status: string;
  keywords: string[];
  country: string;
}

interface Document {
  name: string;
  chunkCount: number;
  size: string;
  lastUpdate: string;
  status?: string;
  metadata?: Record<string, unknown>;
}

interface Session {
  id: string;
  status: 'active' | 'idle' | 'expired';
  lastActivity: string;
  messageCount: number;
  created: string;
  userAgent?: string;
  ipAddress?: string;
}

interface RealtimeMetrics {
  activeConnections: number;
  requestsPerSecond: number;
  averageResponseTime: number;
  errorRate: number;
  memoryUsage: number;
  cpuUsage: number;
}

const AdminDashboard: React.FC = () => {
  // 탭 관리
  const [currentTab, setCurrentTab] = useState("overview");

  // 기존 State 관리
  const [loading, setLoading] = useState(true);
  const [, setSystemStatus] = useState<SystemStatus | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [keywords, setKeywords] = useState<KeywordData | null>(null);
  const [chunks, setChunks] = useState<ChunkData | null>(null);
  const [countries, setCountries] = useState<CountryData | null>(null);
  const [recentChats, setRecentChats] = useState<ChatLog[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [period] = useState('7d');

  // 새로운 state 변수들
  const [sessions, setSessions] = useState<Session[]>([]);
  const [realtimeMetrics, setRealtimeMetrics] = useState<RealtimeMetrics | null>(null);

  // 다이얼로그 상태
  const [testDialogOpen, setTestDialogOpen] = useState(false);
  const [testQuery, setTestQuery] = useState('');
  const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null);
  const [testLoading, setTestLoading] = useState(false);

  // 상세 다이얼로그 상태
  const [sessionDetailOpen, setSessionDetailOpen] = useState(false);
  const [documentDetailOpen, setDocumentDetailOpen] = useState(false);
  const [selectedSession, setSelectedSession] = useState<Session | null>(null);
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null);

  // 페이지네이션
  const [sessionsPage, setSessionsPage] = useState(1);
  const [documentsPage, setDocumentsPage] = useState(1);
  const sessionsPerPage = 10;
  const documentsPerPage = 10;

  const { toast } = useToast();
  const { messages, locale } = useMenuMessages();
  // 기존 무인자 toLocale* 기본 출력을 바이트 동일하게 보존하기 위한 옵션
  // - dateTimeOptions: toLocaleString() 기본(날짜 + 시:분:초)
  // - timeOptions: toLocaleTimeString() 기본(시:분:초)
  const dateTimeOptions: Intl.DateTimeFormatOptions = {
    year: 'numeric', month: 'numeric', day: 'numeric',
    hour: 'numeric', minute: 'numeric', second: 'numeric',
  };
  const timeOptions: Intl.DateTimeFormatOptions = { timeStyle: 'medium' };

  // 기능 수정 중 팝업 상태
  const [maintenanceDialogOpen, setMaintenanceDialogOpen] = useState(false);

  // 데이터 로딩 함수들
  const loadDashboardData = useCallback(async () => {
    setLoading(true);
    try {
      const [
        statusData,
        metricsData,
        keywordsData,
        chunksData,
        countriesData,
        chatsData,
        documentsData,
        sessionsData,
        realtimeData
      ] = await Promise.all([
        adminService.getSystemStatus(),
        adminService.getMetrics(period),
        adminService.getKeywordAnalysis(period),
        adminService.getChunkAnalysis(period),
        adminService.getCountryAnalysis(period),
        adminService.getRecentChats(20),
        adminService.getDocuments(),
        adminService.getSessions({ status: 'all', limit: 50, offset: 0 }),
        adminService.getRealtimeMetrics()
      ]);

      setSystemStatus(statusData);
      setMetrics(metricsData);
      setKeywords(keywordsData);
      setChunks(chunksData);
      setCountries(countriesData);
      setRecentChats(chatsData.chats);
      setDocuments(documentsData.documents);
      setSessions(sessionsData.sessions);
      setRealtimeMetrics(realtimeData);
    } catch (error) {
      logger.error('Failed to load dashboard data:', error);
      toast({
        variant: "destructive",
        title: messages.adminDashboard.loadFailedToastTitle,
        description: messages.adminDashboard.loadFailedToastDesc,
      });
    } finally {
      setLoading(false);
    }
  }, [period, toast, messages]);

  // WebSocket 초기화 및 이벤트 리스너
  useEffect(() => {
    adminService.initWebSocket();

    adminService.on('realtime-metrics', (data: RealtimeMetrics) => {
      setRealtimeMetrics(data);
    });

    adminService.on('connection', (data: { connected: boolean }) => {
      if (data.connected) {
        toast({ title: messages.adminDashboard.connectedToastTitle, description: messages.adminDashboard.connectedToastDesc, variant: "default" });
      } else {
        toast({ title: messages.adminDashboard.disconnectedToastTitle, description: messages.adminDashboard.disconnectedToastDesc, variant: "destructive" });
      }
    });

    adminService.on('new-session', (session: Session) => {
      setSessions(prev => [session, ...prev]);
      toast({ title: messages.adminDashboard.newSessionToastTitle, description: format(messages.adminDashboard.newSessionToastDesc, { id: session.id }) });
    });

    adminService.on('session-updated', (session: Session) => {
      setSessions(prev => prev.map(s => s.id === session.id ? session : s));
    });

    return () => {
      adminService.disconnectWebSocket();
    };
  }, [toast, messages]);

  useEffect(() => {
    loadDashboardData();
  }, [period, loadDashboardData]);

  const handleBackToDeveloperTools = () => {
    setMaintenanceDialogOpen(false);
  };

  const handleTest = async () => {
    if (!testQuery.trim()) return;

    setTestLoading(true);
    try {
      const result = await adminService.testRAG(testQuery);
      setTestResult(result);
    } catch (error) {
      logger.error('Test failed:', error);
      setTestResult({ error: 'Test execution failed' });
    } finally {
      setTestLoading(false);
    }
  };

  const handleRebuildIndex = async () => {
    if (window.confirm(messages.adminDashboard.rebuildIndexConfirm)) {
      try {
        await adminService.rebuildIndex();
        toast({ title: messages.adminDashboard.rebuildIndexToastTitle, description: messages.adminDashboard.rebuildIndexToastDesc });
      } catch {
        toast({ variant: "destructive", title: messages.adminDashboard.rebuildIndexFailToastTitle, description: messages.adminDashboard.rebuildIndexFailToastDesc });
      }
    }
  };

  const handleDownloadLogs = async () => {
    try {
      const blob = await adminService.downloadLogs();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `rag-logs-${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      toast({ title: messages.adminDashboard.logDownloadToastTitle, description: messages.adminDashboard.logDownloadToastDesc });
    } catch {
      toast({ variant: "destructive", title: messages.adminDashboard.downloadFailToastTitle, description: messages.adminDashboard.downloadFailToastDesc });
    }
  };

  const handleSessionView = async (sessionId: string) => {
    try {
      const sessionDetails = await adminService.getSessionDetails(sessionId);
      setSelectedSession(sessionDetails);
      setSessionDetailOpen(true);
    } catch {
      toast({ variant: "destructive", title: messages.adminDashboard.sessionLoadFailToastTitle, description: messages.adminDashboard.sessionLoadFailToastDesc });
    }
  };

  const handleSessionDelete = async (sessionId: string) => {
    if (window.confirm(messages.adminDashboard.sessionDeleteConfirm)) {
      try {
        await adminService.deleteSession(sessionId);
        setSessions(prev => prev.filter(s => s.id !== sessionId));
        toast({ title: messages.adminDashboard.sessionDeleteToastTitle, description: messages.adminDashboard.sessionDeleteToastDesc });
      } catch {
        toast({ variant: "destructive", title: messages.adminDashboard.deleteFailToastTitle, description: messages.adminDashboard.sessionDeleteFailToastDesc });
      }
    }
  };

  const handleDocumentView = (document: Document) => {
    setSelectedDocument(document);
    setDocumentDetailOpen(true);
  };

  const handleDocumentDelete = async (documentName: string) => {
    if (window.confirm(messages.adminDashboard.documentDeleteConfirm)) {
      try {
        await adminService.deleteDocument(documentName);
        setDocuments(prev => prev.filter(d => d.name !== documentName));
        toast({ title: messages.adminDashboard.documentDeleteToastTitle, description: messages.adminDashboard.documentDeleteToastDesc });
      } catch {
        toast({ variant: "destructive", title: messages.adminDashboard.deleteFailToastTitle, description: messages.adminDashboard.documentDeleteFailToastDesc });
      }
    }
  };

  const handleDocumentReprocess = async (documentName: string) => {
    try {
      await adminService.reprocessDocument(documentName);
      toast({ title: messages.adminDashboard.reprocessToastTitle, description: messages.adminDashboard.reprocessToastDesc });
    } catch {
      toast({ variant: "destructive", title: messages.adminDashboard.reprocessFailToastTitle, description: messages.adminDashboard.reprocessFailToastDesc });
    }
  };

  if (loading) {
    return (
      <div className="flex h-[400px] w-full items-center justify-center">
        <RotateCw className="h-10 w-10 animate-spin text-primary opacity-20" />
      </div>
    );
  }

  return (
    <div className="p-4 space-y-6 max-w-[1600px] mx-auto animate-in fade-in duration-500">
      {/* 상태 헤더 */}
      <Card className="rounded-[28px] border-border/60 overflow-hidden shadow-lg bg-gradient-to-br from-background to-muted/20">
        <CardContent className="p-6">
          <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
            <div className="space-y-1">
              <h1 className="text-2xl font-black flex items-center gap-2">
                <Home className="w-6 h-6 text-primary" /> {messages.adminDashboard.headerTitle}
              </h1>
              <p className="text-sm font-medium text-muted-foreground uppercase tracking-widest text-[10px]">{messages.adminDashboard.headerSubtitle}</p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {realtimeMetrics && (
                <>
                  <Badge variant="outline" className="rounded-full px-3 py-1 font-bold bg-primary/5 text-primary border-primary/20">
                    {format(messages.adminDashboard.activeConnections, { count: realtimeMetrics.activeConnections })}
                  </Badge>
                  <Badge variant="outline" className={cn(
                    "rounded-full px-3 py-1 font-bold",
                    realtimeMetrics.averageResponseTime > 1000 ? "bg-amber-500/10 text-amber-600 border-amber-200" : "bg-emerald-500/10 text-emerald-600 border-emerald-200"
                  )}>
                    {format(messages.adminDashboard.responseTime, { ms: realtimeMetrics.averageResponseTime })}
                  </Badge>
                </>
              )}
              <Button variant="ghost" size="icon" onClick={loadDashboardData} className="rounded-xl hover:bg-primary/10 hover:text-primary transition-all">
                <RotateCw className="w-5 h-5" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs value={currentTab} onValueChange={setCurrentTab} className="space-y-6">
        <TabsList className="bg-muted/50 p-1 rounded-[20px] h-12 flex items-stretch gap-1">
          <TabsTrigger value="overview" className="flex-1 rounded-xl data-[state=active]:bg-white data-[state=active]:text-primary font-black text-xs gap-2">
            <Home className="w-4 h-4" /> <span className="hidden sm:inline">{messages.adminDashboard.tabOverview}</span>
          </TabsTrigger>
          <TabsTrigger value="sessions" className="flex-1 rounded-xl data-[state=active]:bg-white data-[state=active]:text-primary font-black text-xs gap-2">
            <Users className="w-4 h-4" /> <span className="hidden sm:inline">{messages.adminDashboard.tabSessions}</span>
          </TabsTrigger>
          <TabsTrigger value="documents" className="flex-1 rounded-xl data-[state=active]:bg-white data-[state=active]:text-primary font-black text-xs gap-2">
            <FileText className="w-4 h-4" /> <span className="hidden sm:inline">{messages.adminDashboard.tabDocuments}</span>
          </TabsTrigger>
          <TabsTrigger value="performance" className="flex-1 rounded-xl data-[state=active]:bg-white data-[state=active]:text-primary font-black text-xs gap-2">
            <BarChart3 className="w-4 h-4" /> <span className="hidden sm:inline">{messages.adminDashboard.tabPerformance}</span>
          </TabsTrigger>
          <TabsTrigger value="prompts" className="flex-1 rounded-xl data-[state=active]:bg-white data-[state=active]:text-primary font-black text-xs gap-2">
            <Brain className="w-4 h-4" /> <span className="hidden sm:inline">{messages.adminDashboard.tabPrompts}</span>
          </TabsTrigger>
          <TabsTrigger value="settings" className="flex-1 rounded-xl data-[state=active]:bg-white data-[state=active]:text-primary font-black text-xs gap-2">
            <Settings className="w-4 h-4" /> <span className="hidden sm:inline">{messages.adminDashboard.tabSettings}</span>
          </TabsTrigger>
        </TabsList>

        {/* 탭 0: 개요 */}
        <TabsContent value="overview" className="space-y-6 animate-in slide-in-from-bottom-2 duration-400">
          {/* 요약 메트릭 */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label={messages.adminDashboard.metricTotalSessions}
              value={metrics?.totalSessions || 0}
              chartData={metrics?.timeSeries || []}
              dataKey="sessions"
              color={COLORS.chart.blue}
            />
            <MetricCard
              label={messages.adminDashboard.metricTotalQueries}
              value={metrics?.totalQueries || 0}
              chartData={metrics?.timeSeries || []}
              dataKey="queries"
              color={COLORS.chart.green}
            />
            <MetricCard
              label={messages.adminDashboard.metricAvgResponseTime}
              value={`${metrics?.avgResponseTime?.toFixed(1) || 0}s`}
              chartData={metrics?.timeSeries || []}
              dataKey="avgResponseTime"
              color={COLORS.chart.orange}
            />
            <MetricCard
              label={messages.adminDashboard.metricRealtimeConnections}
              value={realtimeMetrics?.activeConnections || 0}
              isStatic
            />
          </div>

          {/* 인사이트 분석 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <InsightList
              title={messages.adminDashboard.insightKeywordsTitle}
              items={keywords?.keywords.map(k => ({ label: k.keyword, value: format(messages.adminDashboard.insightCountUnit, { count: k.count }), rank: k.rank })) || []}
            />
            <InsightList
              title={messages.adminDashboard.insightChunksTitle}
              items={chunks?.chunks.map(c => ({ label: c.chunkName, value: format(messages.adminDashboard.insightCountUnit, { count: c.count }), rank: c.rank })) || []}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* 최근 대화 */}
            <div className="lg:col-span-8 space-y-4">
              <Card className="rounded-[28px] border-border/60">
                <CardHeader className="flex flex-row items-center justify-between">
                  <CardTitle className="text-lg font-black">{messages.adminDashboard.recentChatsTitle}</CardTitle>
                  <Button variant="ghost" size="sm" className="font-bold text-xs">{messages.adminDashboard.viewAll}</Button>
                </CardHeader>
                <CardContent className="space-y-3">
                  {recentChats.slice(0, 5).map((chat) => (
                    <div key={chat.id} className="p-4 rounded-2xl bg-muted/20 border border-border/40 hover:bg-muted/40 transition-colors">
                      <p className="font-bold text-sm mb-2 opacity-90">"{chat.message}"</p>
                      <div className="flex flex-wrap items-center gap-3 text-[10px] font-black uppercase text-muted-foreground">
                        <span>{formatDate(chat.timestamp, locale, timeOptions)}</span>
                        <Separator orientation="vertical" className="h-3" />
                        <span>{chat.responseTime}ms</span>
                        <Separator orientation="vertical" className="h-3" />
                        <Badge variant="outline" className={cn(
                          "h-4 text-[8px] font-black uppercase",
                          chat.status === 'success' ? "bg-emerald-500/10 text-emerald-600 border-emerald-200" : "bg-destructive/10 text-destructive border-destructive/20"
                        )}>
                          {chat.status}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>

            {/* 시스템 도구 */}
            <div className="lg:col-span-4 space-y-4">
              <Card className="rounded-[28px] border-border/60">
                <CardHeader><CardTitle className="text-lg font-black">{messages.adminDashboard.systemToolsTitle}</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  <Button variant="outline" className="w-full justify-start rounded-xl font-bold h-11" onClick={() => setTestDialogOpen(true)}>
                    <Play className="w-4 h-4 mr-3 text-primary" /> {messages.adminDashboard.quickTestRag}
                  </Button>
                  <Button variant="outline" className="w-full justify-start rounded-xl font-bold h-11" onClick={handleRebuildIndex}>
                    <Wrench className="w-4 h-4 mr-3 text-primary" /> {messages.adminDashboard.rebuildIndexAction}
                  </Button>
                  <Button variant="outline" className="w-full justify-start rounded-xl font-bold h-11" onClick={handleDownloadLogs}>
                    <Download className="w-4 h-4 mr-3 text-primary" /> {messages.adminDashboard.exportLogs}
                  </Button>
                </CardContent>
              </Card>

              <Card className="rounded-[28px] border-border/60 bg-primary/5 border-primary/20">
                <CardHeader><CardTitle className="text-lg font-black">{messages.adminDashboard.globalMetricsTitle}</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  {countries?.countries.slice(0, 5).map((c, idx) => (
                    <div key={idx} className="flex justify-between items-center text-sm font-bold">
                      <span className="text-muted-foreground">{c.country}</span>
                      <span>{c.count}</span>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        {/* 탭 1: 세션 */}
        <TabsContent value="sessions" className="animate-in slide-in-from-bottom-2 duration-400">
          <Card className="rounded-[28px] border-border/60 overflow-hidden">
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle className="text-xl font-black">{messages.adminDashboard.sessionsTitle}</CardTitle>
                <CardDescription className="text-xs font-medium">{messages.adminDashboard.sessionsDescription}</CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Select defaultValue="all">
                  <SelectTrigger className="w-32 rounded-xl h-9 text-xs font-bold">
                    <SelectValue placeholder={messages.adminDashboard.statusFilterPlaceholder} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{messages.adminDashboard.statusAll}</SelectItem>
                    <SelectItem value="active">{messages.adminDashboard.statusActive}</SelectItem>
                    <SelectItem value="idle">{messages.adminDashboard.statusIdle}</SelectItem>
                    <SelectItem value="expired">{messages.adminDashboard.statusExpired}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader className="bg-muted/30">
                  <TableRow>
                    <TableHead className="font-black text-xs uppercase px-6">{messages.adminDashboard.columnSessionId}</TableHead>
                    <TableHead className="font-black text-xs uppercase px-6">{messages.adminDashboard.columnStatus}</TableHead>
                    <TableHead className="font-black text-xs uppercase px-6">{messages.adminDashboard.columnMessages}</TableHead>
                    <TableHead className="font-black text-xs uppercase px-6">{messages.adminDashboard.columnCreatedAt}</TableHead>
                    <TableHead className="font-black text-xs uppercase px-6">{messages.adminDashboard.columnLastActivity}</TableHead>
                    <TableHead className="font-black text-xs uppercase px-6 text-right">{messages.adminDashboard.columnManage}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sessions.slice((sessionsPage - 1) * sessionsPerPage, sessionsPage * sessionsPerPage).map((session) => (
                    <TableRow key={session.id} className="hover:bg-muted/10 transition-colors">
                      <TableCell className="px-6 font-bold text-sm font-mono opacity-70">{session.id}</TableCell>
                      <TableCell className="px-6">
                        <Badge variant="outline" className={cn(
                          "font-black uppercase text-[10px] px-2",
                          session.status === 'active' && "bg-emerald-500/10 text-emerald-600 border-emerald-200",
                          session.status === 'idle' && "bg-amber-500/10 text-amber-600 border-amber-200",
                          session.status === 'expired' && "bg-muted text-muted-foreground border-border"
                        )}>
                          {session.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="px-6 font-black text-sm">{session.messageCount}</TableCell>
                      <TableCell className="px-6 text-xs font-medium text-muted-foreground">{formatDate(session.created, locale, dateTimeOptions)}</TableCell>
                      <TableCell className="px-6 text-xs font-medium text-muted-foreground">{formatDate(session.lastActivity, locale, dateTimeOptions)}</TableCell>
                      <TableCell className="px-6 text-right space-x-1">
                        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg" onClick={() => handleSessionView(session.id)}>
                          <Eye className="w-4 h-4" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg text-destructive hover:bg-destructive/10" onClick={() => handleSessionDelete(session.id)}>
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
            <div className="p-6 border-t border-border/40 flex justify-center">
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" disabled={sessionsPage === 1} onClick={() => setSessionsPage(p => p - 1)} className="rounded-lg h-9 w-9">
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <div className="text-sm font-black px-4">{sessionsPage} / {Math.ceil(sessions.length / sessionsPerPage) || 1}</div>
                <Button variant="ghost" size="icon" disabled={sessionsPage >= Math.ceil(sessions.length / sessionsPerPage)} onClick={() => setSessionsPage(p => p + 1)} className="rounded-lg h-9 w-9">
                  <ChevronRight className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </Card>
        </TabsContent>

        {/* 탭 2: 문서 */}
        <TabsContent value="documents" className="animate-in slide-in-from-bottom-2 duration-400">
          <Card className="rounded-[28px] border-border/60 overflow-hidden">
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle className="text-xl font-black">{messages.adminDashboard.documentsTitle}</CardTitle>
                <CardDescription className="text-xs font-medium">{messages.adminDashboard.documentsDescription}</CardDescription>
              </div>
              <Button size="sm" className="rounded-xl font-black shadow-lg shadow-primary/20">
                <FileText className="w-4 h-4 mr-2" /> {messages.adminDashboard.registerDocument}
              </Button>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader className="bg-muted/30">
                  <TableRow>
                    <TableHead className="font-black text-xs uppercase px-6">{messages.adminDashboard.columnDocumentName}</TableHead>
                    <TableHead className="font-black text-xs uppercase px-6">{messages.adminDashboard.columnChunks}</TableHead>
                    <TableHead className="font-black text-xs uppercase px-6">{messages.adminDashboard.columnSize}</TableHead>
                    <TableHead className="font-black text-xs uppercase px-6">{messages.adminDashboard.columnDocStatus}</TableHead>
                    <TableHead className="font-black text-xs uppercase px-6">{messages.adminDashboard.columnLastUpdate}</TableHead>
                    <TableHead className="font-black text-xs uppercase px-6 text-right">{messages.adminDashboard.columnAction}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {documents.slice((documentsPage - 1) * documentsPerPage, documentsPage * documentsPerPage).map((doc) => (
                    <TableRow key={doc.name} className="hover:bg-muted/10 transition-colors">
                      <TableCell className="px-6 font-black text-sm">{doc.name}</TableCell>
                      <TableCell className="px-6 font-black text-sm opacity-70">{doc.chunkCount}</TableCell>
                      <TableCell className="px-6 font-black text-sm opacity-70">{doc.size}</TableCell>
                      <TableCell className="px-6">
                        <Badge variant="outline" className={cn(
                          "font-black uppercase text-[10px] px-2",
                          doc.status === 'processing' ? "bg-amber-500/10 text-amber-600 border-amber-200" : "bg-emerald-500/10 text-emerald-600 border-emerald-200"
                        )}>
                          {doc.status || 'active'}
                        </Badge>
                      </TableCell>
                      <TableCell className="px-6 text-xs font-medium text-muted-foreground">{doc.lastUpdate}</TableCell>
                      <TableCell className="px-6 text-right space-x-1">
                        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg" onClick={() => handleDocumentView(doc)}>
                          <Eye className="w-4 h-4" />
                        </Button>
                        <Button variant="outline" size="sm" className="h-8 px-3 rounded-lg text-xs font-black" onClick={() => handleDocumentReprocess(doc.name)}>
                          {messages.adminDashboard.reprocessButton}
                        </Button>
                        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg text-destructive hover:bg-destructive/10" onClick={() => handleDocumentDelete(doc.name)}>
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
            <div className="p-6 border-t border-border/40 flex justify-center">
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" disabled={documentsPage === 1} onClick={() => setDocumentsPage(p => p - 1)} className="rounded-lg h-9 w-9">
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <div className="text-sm font-black px-4">{documentsPage} / {Math.ceil(documents.length / documentsPerPage) || 1}</div>
                <Button variant="ghost" size="icon" disabled={documentsPage >= Math.ceil(documents.length / documentsPerPage)} onClick={() => setDocumentsPage(p => p + 1)} className="rounded-lg h-9 w-9">
                  <ChevronRight className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </Card>
        </TabsContent>

        {/* 탭 3: 성능 */}
        <TabsContent value="performance" className="animate-in slide-in-from-bottom-2 duration-400 space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-5 space-y-6">
              <Card className="rounded-[28px] border-border/60 overflow-hidden">
                <CardHeader><CardTitle className="text-lg font-black">{messages.adminDashboard.deviceLoadTitle}</CardTitle></CardHeader>
                <CardContent className="pt-0 space-y-8">
                  {realtimeMetrics && (
                    <div className="grid grid-cols-2 gap-8">
                      <StatCircle label="Requests/s" value={realtimeMetrics.requestsPerSecond} />
                      <StatCircle label="Error Rate" value={`${realtimeMetrics.errorRate}%`} isBad={realtimeMetrics.errorRate > 5} />
                      <StatCircle label="Memory" value={`${realtimeMetrics.memoryUsage}%`} />
                      <StatCircle label="CPU Load" value={`${realtimeMetrics.cpuUsage}%`} />
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
            <div className="lg:col-span-7">
              <Card className="rounded-[28px] border-border/60 h-full">
                <CardHeader><CardTitle className="text-lg font-black">{messages.adminDashboard.latencyTitle}</CardTitle></CardHeader>
                <CardContent className="h-[400px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={metrics?.timeSeries || []}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={COLORS.border.default.light} />
                      <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 10, fontWeight: 700 }} dy={10} />
                      <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fontWeight: 700 }} dx={-10} />
                      <Tooltip contentStyle={{ borderRadius: '16px', border: 'none', boxShadow: COLORS.shadow.md.light }} />
                      <Line type="monotone" dataKey="avgResponseTime" stroke={COLORS.chart.purple} strokeWidth={4} dot={{ r: 4, strokeWidth: 2, fill: COLORS.background.primary.light }} activeDot={{ r: 6 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        {/* 탭 4: 프롬프트 관리 */}
        <TabsContent value="prompts" className="animate-in slide-in-from-bottom-2 duration-400">
          <PromptManager />
        </TabsContent>

        {/* 탭 5: 설정 */}
        <TabsContent value="settings" className="animate-in slide-in-from-bottom-2 duration-400">
          <SettingsPage />
        </TabsContent>
      </Tabs>

      {/* 테스트 다이얼로그 */}
      <Dialog open={testDialogOpen} onOpenChange={setTestDialogOpen}>
        <DialogContent className="max-w-2xl rounded-[32px] p-8 border-none shadow-2xl">
          <DialogHeader>
            <DialogTitle className="text-2xl font-black">{messages.adminDashboard.testDialogTitle}</DialogTitle>
            <DialogDescription className="font-medium text-muted-foreground">{messages.adminDashboard.testDialogDescription}</DialogDescription>
          </DialogHeader>
          <div className="space-y-6 my-4">
            <div className="space-y-2">
              <Label className="text-xs font-black uppercase text-primary ml-1">{messages.adminDashboard.testQueryLabel}</Label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  value={testQuery}
                  onChange={(e) => setTestQuery(e.target.value)}
                  placeholder={messages.adminDashboard.testQueryPlaceholder}
                  className="pl-10 h-12 rounded-2xl border-border/60 focus:ring-primary/20 transition-all font-bold"
                />
              </div>
            </div>

            {testResult && (
              <div className="space-y-4 animate-in fade-in zoom-in-95 duration-300">
                <Separator />
                <div className="space-y-4">
                  <div className="space-y-2 font-bold">
                    <Label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">{messages.adminDashboard.retrievedChunksLabel}</Label>
                    <ScrollArea className="h-32 rounded-2xl bg-muted/30 border border-border/40 p-4">
                      {testResult.retrievedChunks?.map((chunk: Record<string, unknown>, i: number) => (
                        <div key={i} className="text-sm mb-3 last:mb-0 pb-3 border-b border-border/20 last:border-0">
                          <p className="opacity-80 leading-relaxed font-medium">"{chunk.content}"</p>
                          <Badge variant="secondary" className="mt-1 h-4 text-[8px] font-black">Score: {chunk.score?.toFixed(3)}</Badge>
                        </div>
                      ))}
                    </ScrollArea>
                  </div>
                  <div className="space-y-2 font-bold">
                    <Label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">{messages.adminDashboard.llmAnswerLabel}</Label>
                    <div className="p-4 rounded-2xl bg-primary/5 border border-primary/10 text-sm leading-relaxed whitespace-pre-wrap font-medium">
                      {testResult.generatedAnswer}
                      {testResult.error && <p className="text-destructive font-black">{testResult.error}</p>}
                    </div>
                  </div>
                  <div className="flex justify-end">
                    <span className="text-[10px] font-black text-muted-foreground uppercase">ENGINE LATENCY: {testResult.responseTime}ms</span>
                  </div>
                </div>
              </div>
            )}
          </div>
          <DialogFooter className="gap-2">
            <Button variant="ghost" onClick={() => setTestDialogOpen(false)} className="rounded-xl font-bold">{messages.adminDashboard.closeButton}</Button>
            <Button onClick={handleTest} disabled={testLoading || !testQuery.trim()} className="rounded-xl font-black bg-primary px-8">
              {testLoading ? <RotateCw className="w-4 h-4 animate-spin mr-2" /> : <Play className="w-4 h-4 mr-2" />} {messages.adminDashboard.testStartButton}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 세션 상세 다이얼로그 */}
      <Dialog open={sessionDetailOpen} onOpenChange={setSessionDetailOpen}>
        <DialogContent className="max-w-xl rounded-[32px] p-8">
          <DialogHeader>
            <DialogTitle className="text-2xl font-black">{messages.adminDashboard.sessionDetailTitle}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 my-2">
            {selectedSession && (
              <div className="grid grid-cols-2 gap-4">
                <InfoItem label="SESSION ID" value={selectedSession.id} fullWidth />
                <InfoItem label="STATUS" value={selectedSession.status.toUpperCase()} />
                <InfoItem label="TOTAL MESSAGES" value={selectedSession.messageCount} />
                <InfoItem label="CREATED AT" value={formatDate(selectedSession.created, locale, dateTimeOptions)} />
                <InfoItem label="LAST ACTIVITY" value={formatDate(selectedSession.lastActivity, locale, dateTimeOptions)} />
                <InfoItem label="IP ADDRESS" value={selectedSession.ipAddress || 'UNKNOWN'} />
                <InfoItem label="USER AGENT" value={selectedSession.userAgent || 'N/A'} fullWidth className="text-[10px] items-start" />
              </div>
            )}
          </div>
          <DialogFooter className="mt-6 gap-2">
            <Button variant="ghost" onClick={() => setSessionDetailOpen(false)} className="rounded-xl font-bold">{messages.adminDashboard.closeButton}</Button>
            <Button variant="destructive" onClick={() => selectedSession && handleSessionDelete(selectedSession.id)} className="rounded-xl font-bold bg-destructive/90">
              {messages.adminDashboard.sessionForceClose}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 문서 상세 다이얼로그 */}
      <Dialog open={documentDetailOpen} onOpenChange={setDocumentDetailOpen}>
        <DialogContent className="max-w-xl rounded-[32px] p-8">
          <DialogHeader>
            <DialogTitle className="text-2xl font-black">{messages.adminDashboard.documentDetailTitle}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 my-2">
            {selectedDocument && (
              <div className="space-y-6">
                <div className="grid grid-cols-2 gap-4 font-bold">
                  <InfoItem label="FILENAME" value={selectedDocument.name} fullWidth />
                  <InfoItem label="CHUNKS" value={selectedDocument.chunkCount} />
                  <InfoItem label="FILE SIZE" value={selectedDocument.size} />
                  <InfoItem label="STATUS" value={(selectedDocument.status || 'Active').toUpperCase()} />
                  <InfoItem label="LAST UPDATED" value={selectedDocument.lastUpdate} />
                </div>
                {selectedDocument.metadata && (
                  <div className="space-y-2">
                    <Label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Metadata JSON</Label>
                    <div className="bg-black/90 p-4 rounded-2xl overflow-hidden shadow-xl border border-zinc-800">
                      <pre className="text-[11px] font-mono text-emerald-400 opacity-80 overflow-x-auto">
                        {JSON.stringify(selectedDocument.metadata, null, 2)}
                      </pre>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
          <DialogFooter className="mt-6 gap-2">
            <Button variant="ghost" onClick={() => setDocumentDetailOpen(false)} className="rounded-xl font-bold">{messages.adminDashboard.closeButton}</Button>
            <Button variant="outline" onClick={() => selectedDocument && handleDocumentReprocess(selectedDocument.name)} className="rounded-xl font-bold">
              {messages.adminDashboard.reprocessButton}
            </Button>
            <Button variant="destructive" onClick={() => selectedDocument && handleDocumentDelete(selectedDocument.name)} className="rounded-xl font-bold bg-destructive/90">
              {messages.adminDashboard.documentPermanentDelete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 유지보수 팝업 */}
      <Dialog open={maintenanceDialogOpen} onOpenChange={setMaintenanceDialogOpen}>
        <DialogContent className="rounded-[32px] p-10 text-center space-y-4 border-none shadow-2xl">
          <div className="w-20 h-20 rounded-[32px] bg-primary/10 flex items-center justify-center mx-auto mb-4">
            <Wrench className="w-10 h-10 text-primary animate-pulse" />
          </div>
          <DialogHeader>
            <DialogTitle className="text-2xl font-black text-center">{messages.adminDashboard.maintenanceTitle}</DialogTitle>
            <DialogDescription className="text-center font-medium leading-relaxed">
              {messages.adminDashboard.maintenanceDescriptionLine1}<br />{messages.adminDashboard.maintenanceDescriptionLine2}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="justify-center mt-6">
            <Button onClick={handleBackToDeveloperTools} className="rounded-2xl font-black px-8 py-6 h-auto text-lg bg-primary shadow-xl shadow-primary/20">
              {messages.adminDashboard.maintenanceBack}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

const MetricCard = ({ label, value, chartData, dataKey, color, isStatic }: { label: string, value: string | number, chartData?: Record<string, unknown>[], dataKey?: string, color?: string, isStatic?: boolean }) => (
  <Card className="rounded-[28px] border-border/60 overflow-hidden group hover:border-primary/40 hover:shadow-xl hover:shadow-primary/5 transition-all duration-300">
    <CardContent className="p-6 space-y-4">
      <div className="space-y-0.5">
        <p className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60">{label}</p>
        <p className="text-3xl font-black tracking-tighter">{value}</p>
      </div>
      {!isStatic && chartData && dataKey && (
        <div className="h-10 w-full opacity-60 group-hover:opacity-100 transition-opacity">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {isStatic && (
        <div className="h-10 flex items-center gap-1.5 overflow-hidden">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-full w-2 bg-primary/10 rounded-full animate-pulse" style={{ animationDelay: `${i * 150}ms`, height: `${30 + Math.random() * 70}%` }} />
          ))}
        </div>
      )}
    </CardContent>
  </Card>
);

const InsightList = ({ title, items }: { title: string, items: { label: string, value: string, rank: number }[] }) => (
  <Card className="rounded-[28px] border-border/60 overflow-hidden">
    <CardHeader className="pb-2"><CardTitle className="text-lg font-black">{title}</CardTitle></CardHeader>
    <CardContent className="p-4 space-y-1">
      {items.map((item, idx) => (
        <div key={idx} className="flex items-center gap-4 p-3 rounded-2xl hover:bg-muted/30 transition-colors">
          <div className="w-8 h-8 rounded-xl bg-muted flex items-center justify-center font-black text-xs text-muted-foreground">{item.rank}</div>
          <span className="flex-1 font-bold text-sm truncate">{item.label}</span>
          <span className="font-black text-xs text-primary">{item.value}</span>
        </div>
      ))}
    </CardContent>
  </Card>
);

const StatCircle = ({ label, value, isBad }: { label: string, value: string | number, isBad?: boolean }) => (
  <div className="space-y-2 text-center">
    <div className={cn(
      "w-20 h-20 mx-auto rounded-full border-[6px] flex flex-col items-center justify-center transition-all duration-1000",
      isBad ? "border-destructive/20 text-destructive" : "border-primary/10 text-primary"
    )}>
      <span className="text-lg font-black tracking-tighter leading-none">{value}</span>
    </div>
    <span className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/60">{label}</span>
  </div>
);

const InfoItem = ({ label, value, fullWidth, className }: { label: string, value: React.ReactNode, fullWidth?: boolean, className?: string }) => (
  <div className={cn("flex flex-col gap-1", fullWidth ? "col-span-2" : "col-span-1", className)}>
    <span className="text-[10px] font-black uppercase text-muted-foreground/40 tracking-widest">{label}</span>
    <span className="text-sm font-bold truncate block">{value}</span>
  </div>
);

export default AdminDashboard;