import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  RotateCw,
  CheckCircle2,
  AlertTriangle,
  Database,
  Layers,
  Zap,
  Cpu,
  Activity,
  HardDrive,
  Info,
  Server,
  BarChart3,
  Search,
  ArrowUpRight,
  ShieldCheck,
  Clock,
} from 'lucide-react';
import { qdrantService } from '../services/qdrantService';
import {
  QdrantStatusResponse,
  QdrantMetricsResponse,
  QdrantResourceUsageResponse,
  QdrantHealthResponse,
  QdrantCollectionDetailResponse,
  QdrantCollectionsResponse,
  QdrantCollectionSummary,
} from '../types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';

const formatNumber = (value?: number | null, options?: Intl.NumberFormatOptions) => {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return '-';
  }
  return value.toLocaleString(undefined, options);
};

const formatPercent = (value?: number | null) => {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return '-';
  }
  return `${value.toFixed(1)}%`;
};

const formatMbToGb = (value?: number | null) => {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return '-';
  }
  return `${(value / 1024).toFixed(1)} GB`;
};

const clampPercentage = (value?: number | null) => {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return undefined;
  }
  return Math.min(Math.max(value, 0), 100);
};

const toDisplayStatus = (status?: string) => {
  if (!status) {
    return '-';
  }
  return status.toUpperCase();
};

const getStatusColorClass = (status?: string) => {
  const normalized = status?.toLowerCase();
  if (!normalized) return 'text-muted-foreground';
  if (['healthy', 'ready', 'ok', 'online', 'active', 'pass'].includes(normalized)) return 'text-emerald-500';
  if (['warning', 'degraded'].includes(normalized)) return 'text-amber-500';
  if (['unhealthy', 'error', 'offline', 'failed'].includes(normalized)) return 'text-destructive';
  return 'text-muted-foreground';
};

interface FetchCollectionOptions {
  suppressLoading?: boolean;
}

export const StatsTab: React.FC = () => {
  const [statusData, setStatusData] = useState<QdrantStatusResponse | null>(null);
  const [metrics, setMetrics] = useState<QdrantMetricsResponse | null>(null);
  const [resourceUsage, setResourceUsage] = useState<QdrantResourceUsageResponse | null>(null);
  const [health, setHealth] = useState<QdrantHealthResponse | null>(null);
  const [collectionsOverview, setCollectionsOverview] = useState<QdrantCollectionsResponse | null>(null);
  const [collectionDetails, setCollectionDetails] = useState<QdrantCollectionDetailResponse | null>(null);
  const [selectedCollection, setSelectedCollection] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [collectionLoading, setCollectionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveResourceUsage = useMemo(() => {
    if (resourceUsage?.resource_usage) return resourceUsage.resource_usage;
    if (resourceUsage) return resourceUsage;
    return statusData?.resource_usage ?? null;
  }, [resourceUsage, statusData]);

  const collectionSummaries = useMemo<QdrantCollectionSummary[]>(() => {
    const fromStatus = statusData?.collections;
    if (fromStatus?.list && Array.isArray(fromStatus.list)) {
      return fromStatus.list.map((col: QdrantCollectionSummary & { points_count?: number }) => ({
        name: col.name,
        status: col.status,
        is_active: col.is_active,
        vector_count: col.points_count || col.vector_count,
        size_mb: col.size_mb,
      }));
    }
    if (Array.isArray(collectionsOverview?.collections)) {
      return collectionsOverview.collections.map((col: QdrantCollectionSummary & { points_count?: number }) => ({
        name: col.name,
        status: col.status,
        is_active: col.is_active,
        vector_count: col.points_count || col.vector_count,
        size_mb: col.size_mb,
      }));
    }
    return [];
  }, [collectionsOverview, statusData]);

  const fetchCollectionDetails = useCallback(
    async (collectionName: string, options: FetchCollectionOptions = {}) => {
      if (!collectionName) return;
      setError(null);
      if (!options.suppressLoading) setCollectionLoading(true);
      try {
        const response = await qdrantService.getCollectionDetail(collectionName);
        setCollectionDetails(response.data);
        setSelectedCollection(collectionName);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : '컬렉션 정보를 불러오는 중 오류가 발생했습니다.';
        setError(message);
      } finally {
        if (!options.suppressLoading) setCollectionLoading(false);
      }
    },
    [],
  );

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statusResponse, metricsResponse, collectionsResponse, resourceResponse, healthResponse] = await Promise.all([
        qdrantService.getStatus(),
        qdrantService.getMetrics(),
        qdrantService.getCollections(),
        qdrantService.getResourceUsage(),
        qdrantService.getHealth(),
      ]);

      setStatusData(statusResponse.data);
      setMetrics(metricsResponse.data);
      setCollectionsOverview(collectionsResponse.data);
      setResourceUsage(resourceResponse.data);
      setHealth(healthResponse.data);

      const detailFromStatus = statusResponse.data?.active_collection_details;
      if (detailFromStatus) {
        setCollectionDetails(detailFromStatus);
        setSelectedCollection(detailFromStatus.name ?? null);
      } else {
        const activeName = statusResponse.data?.collections?.active_collection ?? collectionsResponse.data?.active_collection ?? null;
        setSelectedCollection(activeName ?? null);
        if (activeName) {
          await fetchCollectionDetails(activeName, { suppressLoading: true });
        } else {
          setCollectionDetails(null);
        }
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Qdrant 상태 정보를 불러오는 중 문제가 발생했습니다.';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [fetchCollectionDetails]);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const totalCollections = statusData?.collections?.total_count ?? collectionsOverview?.total_count;
  const activeCollection = selectedCollection ?? statusData?.collections?.active_collection ?? '-';
  const totalVectors = effectiveResourceUsage?.total_vectors;
  const cpuUsage = useMemo(() => {
    if (metrics?.resources?.cpu_usage_percent !== undefined) return metrics.resources.cpu_usage_percent as number;
    if (typeof effectiveResourceUsage?.cpu_percent === 'number') return effectiveResourceUsage.cpu_percent;
    const raw = metrics?.resources ? (metrics.resources['cpu_percent'] as number | string | null | undefined) : undefined;
    return typeof raw === 'number' ? raw : undefined;
  }, [effectiveResourceUsage, metrics]);

  return (
    <div className="p-6 max-w-[1200px] mx-auto space-y-6">
      {/* 헤더 */}
      <Card className="border-border/60 shadow-lg overflow-hidden bg-gradient-to-br from-background to-muted/20">
        <CardContent className="p-6">
          <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-black flex items-center gap-2">
                <Server className="w-6 h-6 text-primary" />
                DB 상태 모니터링
              </h1>
              <p className="text-sm font-medium text-muted-foreground mt-1">
                백엔드 데이터베이스의 실시간 상태와 리소스 사용량을 관리합니다.
              </p>
            </div>
            <div className="flex items-center gap-3 w-full md:w-auto">
              {health?.status && (
                <Badge variant="outline" className={cn(
                  "py-1 px-3 rounded-full font-bold flex items-center gap-1.5",
                  health.status.toLowerCase() === 'healthy' ? "bg-emerald-500/10 text-emerald-600 border-emerald-200" : "bg-amber-500/10 text-amber-600 border-amber-200"
                )}>
                  <div className={cn("w-2 h-2 rounded-full animate-pulse", health.status.toLowerCase() === 'healthy' ? "bg-emerald-500" : "bg-amber-500")} />
                  연결 상태: {toDisplayStatus(health.status)}
                </Badge>
              )}
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={fetchAll}
                      disabled={loading}
                      className="rounded-xl hover:bg-primary/10 hover:text-primary transition-all duration-300"
                    >
                      <RotateCw className={cn("w-5 h-5", loading && "animate-spin")} />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>새로고침</TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
          </div>
        </CardContent>
      </Card>

      {error && (
        <Alert variant="destructive" className="animate-in fade-in slide-in-from-top-4 duration-300 rounded-[20px]">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle className="font-bold">시스템 오류</AlertTitle>
          <AlertDescription className="text-sm font-medium">{error}</AlertDescription>
        </Alert>
      )}

      {/* 요약 카드 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <SummaryCard
          icon={<Activity className="w-8 h-8" />}
          label="시스템 상태"
          value={toDisplayStatus(statusData?.cluster?.status ?? health?.status)}
          colorClass={getStatusColorClass(statusData?.cluster?.status ?? health?.status)}
        />
        <SummaryCard
          icon={<Database className="w-8 h-8" />}
          label="총 컬렉션 수"
          value={formatNumber(totalCollections)}
        />
        <SummaryCard
          icon={<Layers className="w-8 h-8" />}
          label="활성 컬렉션"
          value={activeCollection === '-' ? 'N/A' : activeCollection}
          className="truncate"
        />
        <SummaryCard
          icon={<Zap className="w-8 h-8" />}
          label="총 벡터 데이터"
          value={formatNumber(totalVectors)}
        />
      </div>

      {/* 리소스 사용 기록 */}
      {effectiveResourceUsage && (
        <Card className="rounded-[28px] border-border/60 overflow-hidden">
          <CardHeader>
            <CardTitle className="text-lg font-black flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-primary" />
              시스템 리소스 점유율
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
              <ResourceProgress
                label="메모리 사용율"
                icon={<Cpu className="w-4 h-4" />}
                current={formatMbToGb(effectiveResourceUsage.total_memory_mb)}
                percent={effectiveResourceUsage.usage_percentage?.memory ?? effectiveResourceUsage.memory_percent ?? (metrics?.resources?.memory_usage_percent as number)}
              />
              <ResourceProgress
                label="디스크 사용율"
                icon={<HardDrive className="w-4 h-4" />}
                current={formatMbToGb(effectiveResourceUsage.total_disk_mb)}
                percent={effectiveResourceUsage.usage_percentage?.disk ?? effectiveResourceUsage.disk_percent}
              />
              <ResourceProgress
                label="CPU 사용율"
                icon={<Activity className="w-4 h-4" />}
                current={formatPercent(cpuUsage)}
                percent={cpuUsage}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* 실시간 지표 */}
      {(metrics?.metrics || metrics) && (
        <Card className="rounded-[28px] border-border/60 overflow-hidden">
          <CardHeader>
            <CardTitle className="text-lg font-black flex items-center gap-2">
              <Activity className="w-5 h-5 text-primary" />
              실시간 작업 지표
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <MetricBox
                title="처리량 (Throughput)"
                data={[
                  { label: '검색 건수', value: `${formatNumber(metrics.metrics?.operations?.searches_per_second ?? metrics.operations?.searches_per_second)}/s` },
                  { label: '업세트 건수', value: `${formatNumber(metrics.metrics?.operations?.upserts_per_second ?? metrics.operations?.upserts_per_second)}/s` },
                  { label: '24H 총 작업', value: formatNumber(metrics.metrics?.operations?.total_operations_24h ?? metrics.operations?.total_operations_24h) },
                ]}
              />
              <MetricBox
                title="지연 시간 (Latency)"
                data={[
                  { label: 'P50 응답 속도', value: `${formatNumber(metrics.metrics?.performance?.p50_latency_ms ?? metrics.performance?.p50_latency_ms)} ms` },
                  { label: 'P95 응답 속도', value: `${formatNumber(metrics.metrics?.performance?.p95_latency_ms ?? metrics.performance?.p95_latency_ms)} ms` },
                  { label: '시스템 에러율', value: formatPercent(((metrics.metrics?.performance?.error_rate ?? metrics.performance?.error_rate ?? 0) as number) * 100), isBad: (metrics.metrics?.performance?.error_rate ?? metrics.performance?.error_rate ?? 0) > 0.05 },
                ]}
              />
              <MetricBox
                title="네트워크 (Network)"
                data={[
                  { label: '데이터 유입 (IN)', value: `${formatNumber(metrics.metrics?.resources?.network_in_mbps ?? metrics.resources?.network_in_mbps)} Mbps` },
                  { label: '데이터 유출 (OUT)', value: `${formatNumber(metrics.metrics?.resources?.network_out_mbps ?? metrics.resources?.network_out_mbps)} Mbps` },
                  { label: '디스크 읽기/쓰기', value: `${formatNumber(metrics.metrics?.resources?.disk_io_read_mbps ?? metrics.resources?.disk_io_read_mbps)} / ${formatNumber(metrics.metrics?.resources?.disk_io_write_mbps ?? metrics.resources?.disk_io_write_mbps)} Mbps` },
                ]}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* 컬렉션 탐색기 */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* 리스트 */}
        <Card className="lg:col-span-5 rounded-[28px] border-border/60 overflow-hidden flex flex-col max-h-[600px]">
          <CardHeader className="p-6 pb-2">
            <CardTitle className="text-lg font-black flex items-center gap-2">
              <Database className="w-5 h-5 text-primary" />
              컬렉션 탐색기
            </CardTitle>
          </CardHeader>
          <CardContent className="p-2 flex-1 overflow-hidden">
            <ScrollArea className="h-full px-4 pb-4">
              {collectionSummaries.length === 0 ? (
                <div className="py-20 text-center space-y-3">
                  <div className="w-16 h-16 rounded-full bg-muted/30 flex items-center justify-center mx-auto">
                    <Database className="w-8 h-8 opacity-20" />
                  </div>
                  <p className="text-sm font-bold text-muted-foreground">감지된 컬렉션이 없습니다</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {collectionSummaries.map((collection) => (
                    <Button
                      key={collection.name}
                      variant="ghost"
                      className={cn(
                        "w-full h-auto justify-start p-4 rounded-2xl border-2 border-transparent transition-all",
                        collection.name === selectedCollection ? "bg-primary/10 border-primary/20 hover:bg-primary/20" : "hover:bg-muted/50"
                      )}
                      onClick={() => fetchCollectionDetails(collection.name)}
                    >
                      <div className="flex flex-col items-start gap-1 w-full text-left">
                        <div className="flex items-center justify-between w-full">
                          <span className="font-black text-sm">{collection.name}</span>
                          <Badge variant="outline" className={cn(
                            "text-[9px] h-4 font-bold uppercase",
                            collection.status === 'green' ? "bg-emerald-500/10 text-emerald-600 border-emerald-200" : "bg-muted text-muted-foreground"
                          )}>
                            {toDisplayStatus(collection.status)}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-3 text-[10px] text-muted-foreground font-bold uppercase tracking-tighter">
                          <span className="flex items-center gap-1"><Zap className="w-3 h-3" /> {formatNumber(collection.vector_count)} VECTORS</span>
                          <span className="flex items-center gap-1"><HardDrive className="w-3 h-3" /> {formatNumber(collection.size_mb)} MB</span>
                        </div>
                      </div>
                    </Button>
                  ))}
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>

        {/* 디테일 */}
        <Card className="lg:col-span-7 rounded-[28px] border-border/60 bg-muted/10 overflow-hidden flex flex-col max-h-[600px]">
          <CardHeader className="p-6 pb-2">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <CardTitle className="text-lg font-black flex items-center gap-2">
                <Info className="w-5 h-5 text-primary" />
                구성 세부 정보
              </CardTitle>
              {selectedCollection && (
                <Badge className="bg-primary text-white hover:bg-primary rounded-lg font-black py-1 px-3">
                  {selectedCollection}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="p-6 pt-2 flex-1 overflow-hidden flex flex-col">
            {collectionLoading && (
              <div className="absolute inset-0 bg-background/50 backdrop-blur-[2px] z-10 flex items-center justify-center">
                <RotateCw className="w-10 h-10 text-primary animate-spin opacity-40" />
              </div>
            )}

            <ScrollArea className="h-full pr-4">
              {collectionDetails ? (
                <div className="space-y-6">
                  {/* 스키마 및 요악 */}
                  <div className="grid grid-cols-2 gap-4">
                    {(() => {
                      const detail = statusData?.active_collection_details || collectionDetails;
                      const stats = [
                        { label: '현재 상태', value: toDisplayStatus(detail.status) },
                        { label: '데이터 벡터 차원', value: detail.vectors?.dense?.dimensions || detail.vectors?.size },
                        { label: '유사도 거리 함수', value: detail.vectors?.dense?.distance_metric || detail.vectors?.distance },
                        { label: '보유 포인트 수', value: detail.storage?.points_count || detail.statistics?.vector_count },
                        { label: '활성 세그먼트', value: detail.storage?.segments_count || detail.statistics?.segments_count },
                        { label: '메모리 점유율', value: detail.storage?.memory_usage_mb ? `${formatNumber(detail.storage.memory_usage_mb)} MB` : undefined },
                        { label: '디스크 점유율', value: detail.storage?.disk_usage_mb ? `${formatNumber(detail.storage.disk_usage_mb)} MB` : undefined },
                        { label: '최적화 상태', value: detail.performance?.optimization_status },
                      ].filter(s => s.value !== undefined && s.value !== null && s.value !== '-');

                      return stats.map((stat) => (
                        <div key={stat.label} className="p-3 bg-white/50 dark:bg-black/20 rounded-2xl border border-border/40">
                          <p className="text-[10px] font-black text-muted-foreground uppercase mb-1">{stat.label}</p>
                          <p className="text-sm font-bold text-foreground">{typeof stat.value === 'number' ? formatNumber(stat.value) : stat.value}</p>
                        </div>
                      ));
                    })()}
                  </div>

                  {/* 페이로드 스키마 */}
                  {collectionDetails.payload_schema && (
                    <div className="space-y-2">
                      <h4 className="text-xs font-black text-muted-foreground uppercase flex items-center gap-1.5 ml-1">
                        <Search className="w-3 h-3" />
                        인덱싱된 페이로드 필드
                      </h4>
                      <div className="flex flex-wrap gap-1.5">
                        {Object.keys(collectionDetails.payload_schema).map((key) => (
                          <Badge key={key} variant="secondary" className="rounded-lg font-bold bg-muted-foreground/10 text-muted-foreground hover:bg-muted-foreground/20 border-none px-2.5 py-1">
                            {key}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* JSON Config */}
                  {collectionDetails.configuration && (
                    <div className="space-y-2">
                      <h4 className="text-xs font-black text-muted-foreground uppercase flex items-center gap-1.5 ml-1">
                        <ArrowUpRight className="w-3 h-3" />
                        시스템 설정 JSON
                      </h4>
                      <div className="bg-black/90 p-4 rounded-[20px] shadow-2xl overflow-hidden border border-zinc-800">
                        <div className="flex items-center gap-1.5 mb-3">
                          <div className="w-2.5 h-2.5 rounded-full bg-red-500/50" />
                          <div className="w-2.5 h-2.5 rounded-full bg-amber-500/50" />
                          <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/50" />
                        </div>
                        <pre className="text-[11px] font-mono text-emerald-400/80 leading-relaxed overflow-x-auto">
                          {JSON.stringify(collectionDetails.configuration, null, 2)}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center py-20 text-center gap-4">
                  <div className="w-20 h-20 rounded-[32px] bg-primary/5 flex items-center justify-center">
                    <Info className="w-10 h-10 text-primary opacity-20" />
                  </div>
                  <div>
                    <h3 className="font-black text-foreground">데이터 로드 대기 중</h3>
                    <p className="text-sm font-medium text-muted-foreground">탐색기에서 컬렉션을 선택하여 세부 정보를 확인하세요</p>
                  </div>
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      {/* 헬스 체크 */}
      {(() => {
        const healthChecks = statusData?.health_checks;
        if (!healthChecks) return null;
        const checksArray = healthChecks.checks
          ? Object.entries(healthChecks.checks).map(([key, value]) => ({
            name: key.replace(/_/g, ' '),
            status: value,
            message: value === 'pass' ? '정상 수행됨' : value
          }))
          : Array.isArray(healthChecks) ? healthChecks : [];

        if (checksArray.length === 0) return null;

        return (
          <Card className="rounded-[28px] border-border/60 overflow-hidden bg-emerald-500/5 border-emerald-500/20">
            <CardHeader>
              <CardTitle className="text-lg font-black flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-emerald-600" />
                통합 상태 진단 결과 (Health Checks)
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {checksArray.map((check: { name: string; status: string; message: string; latency_ms?: number }, idx: number) => (
                  <div key={idx} className="flex items-center gap-3 p-4 rounded-2xl bg-white/60 dark:bg-black/20 border border-emerald-500/10 hover:shadow-md hover:shadow-emerald-500/5 transition-all group">
                    <div className={cn(
                      "w-10 h-10 rounded-xl flex items-center justify-center transition-transform group-hover:scale-110 duration-500",
                      check.status === 'pass' ? "bg-emerald-500/20 text-emerald-600" : "bg-destructive/10 text-destructive"
                    )}>
                      {check.status === 'pass' ? <CheckCircle2 className="w-5 h-5" /> : <AlertTriangle className="w-5 h-5" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-black uppercase text-muted-foreground/60 leading-none mb-1">{check.name}</p>
                      <p className="text-sm font-bold truncate">{check.message}</p>
                      {check.latency_ms !== undefined && (
                        <div className="flex items-center gap-1 mt-1 text-[10px] font-bold text-emerald-600/80">
                          <Clock className="w-3 h-3" />
                          {formatNumber(check.latency_ms)} MS
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        );
      })()}
    </div>
  );
};

const SummaryCard = ({ icon, label, value, colorClass, className }: { icon: React.ReactNode, label: string, value: string | number | null | undefined, colorClass?: string, className?: string }) => (
  <Card className={cn("rounded-[28px] border-border/60 group hover:border-primary/40 hover:shadow-xl hover:shadow-primary/5 transition-all duration-300", className)}>
    <CardContent className="p-6">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-[20px] bg-primary/10 flex items-center justify-center text-primary group-hover:bg-primary group-hover:text-white transition-all duration-500">
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-black uppercase text-muted-foreground/60 tracking-wider mb-0.5">{label}</p>
          <p className={cn("text-xl font-black truncate", colorClass || "text-foreground")}>{value || '-'}</p>
        </div>
      </div>
    </CardContent>
  </Card>
);

const ResourceProgress = ({ label, icon, current, percent }: { label: string, icon: React.ReactNode, current: string, percent?: number | null }) => {
  const percentage = clampPercentage(percent);
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-primary/5 flex items-center justify-center text-primary">
            {icon}
          </div>
          <span className="text-sm font-bold">{label}</span>
        </div>
        <span className="text-xs font-black text-muted-foreground">{current}</span>
      </div>
      {percentage !== undefined && (
        <div className="space-y-1.5">
          <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-1000 ease-out",
                percentage > 80 ? "bg-destructive shadow-lg shadow-destructive/50" :
                  percentage > 60 ? "bg-amber-500 shadow-lg shadow-amber-500/50" :
                    "bg-primary shadow-lg shadow-primary/50"
              )}
              style={{ width: `${percentage}%` }}
            />
          </div>
          <div className="flex justify-between items-center text-[10px] font-black uppercase tracking-widest text-muted-foreground/40">
            <span>Utilization</span>
            <span className={cn(percentage > 80 && "text-destructive/80")}>{formatPercent(percent)}</span>
          </div>
        </div>
      )}
    </div>
  );
};

const MetricBox = ({ title, data }: { title: string, data: { label: string, value: string | number, isBad?: boolean }[] }) => (
  <div className="p-4 rounded-[24px] bg-muted/30 border border-border/40 hover:bg-muted/50 transition-colors">
    <h4 className="text-xs font-black text-muted-foreground/60 uppercase mb-4 tracking-widest ml-1">{title}</h4>
    <div className="space-y-3">
      {data.map((item, idx) => (
        <div key={idx} className="flex flex-col">
          <span className="text-[10px] font-black text-muted-foreground/40 uppercase mb-0.5">{item.label}</span>
          <span className={cn("text-base font-black tracking-tight", item.isBad ? "text-destructive" : "text-foreground")}>{item.value}</span>
        </div>
      ))}
    </div>
  </div>
);

export default StatsTab;
