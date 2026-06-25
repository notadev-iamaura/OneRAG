import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AdminDashboard from '../AdminDashboard';

const mockAdminService = vi.hoisted(() => ({
  getSystemStatus: vi.fn(),
  getMetrics: vi.fn(),
  getKeywordAnalysis: vi.fn(),
  getChunkAnalysis: vi.fn(),
  getCountryAnalysis: vi.fn(),
  getRecentChats: vi.fn(),
  getDocuments: vi.fn(),
  getSessions: vi.fn(),
  getRealtimeMetrics: vi.fn(),
  getAnalyticsSummary: vi.fn(),
  getAnalyticsTimeseries: vi.fn(),
  getAnalyticsModels: vi.fn(),
  getLangfuseStatus: vi.fn(),
  getLangfuseTraces: vi.fn(),
  initWebSocket: vi.fn(),
  on: vi.fn(),
  disconnectWebSocket: vi.fn(),
  testRAG: vi.fn(),
  rebuildIndex: vi.fn(),
  downloadLogs: vi.fn(),
  getSessionDetails: vi.fn(),
  deleteSession: vi.fn(),
  deleteDocument: vi.fn(),
  reprocessDocument: vi.fn(),
}));

vi.mock('../../../services/adminService', () => ({
  adminService: mockAdminService,
}));

vi.mock('../../../utils/logger', () => ({
  logger: {
    debug: vi.fn(),
    error: vi.fn(),
    log: vi.fn(),
    warn: vi.fn(),
  },
}));

vi.mock('recharts', () => ({
  CartesianGrid: () => null,
  Line: () => null,
  LineChart: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="line-chart">{children}</div>
  ),
  ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

describe('AdminDashboard tracking tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAdminService.getSystemStatus.mockResolvedValue({ status: 'healthy' });
    mockAdminService.getMetrics.mockResolvedValue({
      period: '7d',
      totalSessions: 2,
      totalQueries: 2,
      avgResponseTime: 1,
      timeSeries: [],
    });
    mockAdminService.getKeywordAnalysis.mockResolvedValue({ keywords: [] });
    mockAdminService.getChunkAnalysis.mockResolvedValue({ chunks: [] });
    mockAdminService.getCountryAnalysis.mockResolvedValue({ countries: [] });
    mockAdminService.getRecentChats.mockResolvedValue({ chats: [] });
    mockAdminService.getDocuments.mockResolvedValue({ documents: [] });
    mockAdminService.getSessions.mockResolvedValue({ sessions: [] });
    mockAdminService.getRealtimeMetrics.mockResolvedValue({
      activeConnections: 0,
      requestsPerSecond: 0,
      averageResponseTime: 0,
      errorRate: 0,
      memoryUsage: 0,
      cpuUsage: 0,
    });
    mockAdminService.getAnalyticsSummary.mockResolvedValue({
      summary: {
        visitors: 2,
        sessions: 2,
        questions: 2,
        answers: 2,
        totalTokens: 200,
        estimatedCostUsd: 0.0123,
        avgLatencyMs: 1000,
      },
    });
    mockAdminService.getAnalyticsTimeseries.mockResolvedValue({
      series: [
        {
          bucket: '2026-06',
          visitors: 2,
          sessions: 2,
          questions: 2,
          answers: 2,
          totalTokens: 200,
        },
      ],
    });
    mockAdminService.getAnalyticsModels.mockResolvedValue({
      models: [
        {
          provider: 'google',
          model: 'gemini-2.0-flash',
          answers: 1,
          totalTokens: 120,
          estimatedCostUsd: 0.0073,
        },
      ],
    });
    mockAdminService.getLangfuseStatus.mockResolvedValue({ available: true });
    mockAdminService.getLangfuseTraces.mockResolvedValue({
      traces: [
        {
          traceId: 'trace-1',
          name: 'RAG Pipeline',
          timestamp: '2026-06-25T04:00:00Z',
          model: 'gemini-2.0-flash',
          latencyMs: 1250,
          totalTokens: 120,
        },
      ],
    });
  });

  it('renders backend analytics and trace mock data in the tracking tab', async () => {
    const user = userEvent.setup();
    render(<AdminDashboard />);

    await waitFor(() => {
      expect(mockAdminService.getAnalyticsSummary).toHaveBeenCalledWith(365);
    });

    await user.click(screen.getByRole('tab', { name: /Tracking/i }));

    await waitFor(() => {
      expect(screen.getByText('Visitors')).toBeInTheDocument();
    });
    expect(screen.getByText('Questions')).toBeInTheDocument();
    expect(screen.getByText('200')).toBeInTheDocument();
    expect(screen.getByText('$0.0123')).toBeInTheDocument();
    expect(screen.getByText('google')).toBeInTheDocument();
    expect(screen.getAllByText('gemini-2.0-flash').length).toBeGreaterThan(0);
    expect(screen.getByText('RAG Pipeline')).toBeInTheDocument();
    expect(screen.getByText('1250ms')).toBeInTheDocument();
    expect(screen.getByText('connected')).toBeInTheDocument();
  });
});
