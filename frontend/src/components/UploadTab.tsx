import React, { useState, useRef, useCallback, useEffect } from 'react';
import {
  UploadCloud,
  FileText,
  CheckCircle2,
  AlertCircle,
  X,
  Play,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Clock,
  Layers,
  Database,
  Cpu,
  Settings,
} from 'lucide-react';
import { ToastMessage } from '../types';
import { documentAPI } from '../services/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import { readOperatorSettings } from '../config/operatorSettings';

// 지원 업로드 확장자 (accept / validation / 안내문구의 단일 출처 — 드리프트 방지)
const SUPPORTED_UPLOAD_EXTENSIONS = [
  '.pdf', '.txt', '.md', '.markdown', '.docx', '.pptx', '.xls', '.xlsx', '.html', '.htm', '.json',
];
const UPLOAD_ACCEPT = SUPPORTED_UPLOAD_EXTENSIONS.join(',');

// 동시 업로드 슬롯 수: 일괄 처리 시 한 번에 N개만 활성화해 서버/브라우저 과부하를 막는다.
const MAX_ACTIVE_UPLOADS = 2;

// 업로드 허용 상한: 분할(chunked) 업로드 도입으로 30MB 임계 초과 파일도 처리 가능해졌으므로
// 기존 50MB 하드리밋을 상향한다. 다만 무제한은 브라우저 메모리/처리 시간 위험이 있어 합리적 상한(1GB)을 둔다.
const MAX_UPLOAD_SIZE_BYTES = 1024 * 1024 * 1024; // 1GB
const MAX_UPLOAD_SIZE_LABEL = '1GB';

// 확장자 → 표시용 로더 라벨 매핑. 백엔드가 loader 타입을 내려주지 않으므로 클라이언트에서 추론한다.
const FILE_LOADER_LABELS: Record<string, string> = {
  pdf: 'PDF',
  txt: 'Text',
  md: 'Markdown',
  markdown: 'Markdown',
  docx: 'DOCX',
  pptx: 'PPTX',
  xls: 'XLS',
  xlsx: 'XLSX',
  html: 'HTML',
  htm: 'HTML',
  json: 'JSON',
  csv: 'CSV',
};

/**
 * 파일 확장자/MIME 타입으로 로더 종류를 추론한다.
 *
 * 기존에는 무엇을 올려도 'Markdown'으로 하드코딩 표기되어 사용자에게 거짓 정보를 노출했다.
 * 백엔드 상태 응답에는 로더 타입 필드가 없으므로 확장자 기반 추론으로 사실에 가깝게 표기한다.
 */
const inferLoaderTypeFromFile = (file: File): string => {
  const extension = file.name.split('.').pop()?.toLowerCase();
  if (extension && FILE_LOADER_LABELS[extension]) {
    return FILE_LOADER_LABELS[extension];
  }
  if (file.type === 'application/pdf') {
    return 'PDF';
  }
  return 'Document';
};

/** 스플리터 내부 값(recursive 등)을 표시용 라벨로 변환한다. */
const SPLITTER_LABELS: Record<UploadSettings['splitterType'], string> = {
  recursive: 'Recursive',
  markdown: 'Markdown',
  semantic: 'Semantic',
};

const formatSplitterLabel = (splitterType?: UploadSettings['splitterType']): string => {
  if (splitterType && SPLITTER_LABELS[splitterType]) {
    return SPLITTER_LABELS[splitterType];
  }
  return 'Recursive';
};

interface UploadTabProps {
  showToast: (message: Omit<ToastMessage, 'id'>) => void;
}

interface UploadSettings {
  splitterType: 'recursive' | 'markdown' | 'semantic';
  chunkSize: number;
  chunkOverlap: number;
}

interface UploadFile {
  id: string;
  file: File;
  originalFileName?: string; // 원본 파일명 보존
  status: 'selected' | 'ready' | 'uploading' | 'processing' | 'completed' | 'failed';
  progress: number;
  error?: string;
  documentId?: string;
  settings?: UploadSettings;
  processingDetails?: {
    processingTime: number;
    chunksCount: number;
    loaderType: string;
    splitterType: string;
    storageLocation: string;
  };
}

// 현재 업로드/처리 중인 파일인지 판별(동시성 슬롯 계산에 사용).
const isActiveUpload = (file: UploadFile): boolean =>
  file.status === 'uploading' || file.status === 'processing';

export const UploadTab: React.FC<UploadTabProps> = ({ showToast }) => {
  const [files, setFiles] = useState<UploadFile[]>([]);

  // 업로드 상태 폴링 interval 추적: 언마운트 시 모두 정리해
  // 유령 폴링(언마운트된 컴포넌트의 setFiles 호출)과 메모리 누수를 방지한다.
  const activeIntervalsRef = useRef<Set<ReturnType<typeof setInterval>>>(new Set());

  useEffect(() => {
    const intervals = activeIntervalsRef.current;
    return () => {
      intervals.forEach((id) => clearInterval(id));
      intervals.clear();
    };
  }, []);
  const [isDragging, setIsDragging] = useState(false);
  // 일괄 처리 진행 상태: true이면 슬롯이 비는 대로 ready 파일을 순차 시작한다.
  const [isBulkProcessing, setIsBulkProcessing] = useState(false);
  // 중복-시작 가드: 동일 파일이 슬롯 드레인/단일 시작에서 동시에 호출되는 경합을 차단한다.
  const startingFileIdsRef = useRef<Set<string>>(new Set());
  const [globalSettings, setGlobalSettings] = useState<UploadSettings>(() => {
    const operatorSettings = readOperatorSettings();

    return {
      splitterType: 'recursive',
      chunkSize: operatorSettings.chunkSize,
      chunkOverlap: operatorSettings.chunkOverlap
    };
  });
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 파일명 단축 함수
  const truncateFileName = useCallback((fileName: string, maxLength: number = 100): string => {
    const extension = fileName.substring(fileName.lastIndexOf('.'));
    const nameWithoutExt = fileName.substring(0, fileName.lastIndexOf('.'));

    if (fileName.length <= maxLength) {
      return fileName;
    }

    const availableLength = maxLength - extension.length;
    const truncatedName = nameWithoutExt.substring(0, availableLength);

    return truncatedName + extension;
  }, []);

  // 파일 유효성 검사
  const validateFile = useCallback((file: File): string | null => {
    const allowedExtensions = SUPPORTED_UPLOAD_EXTENSIONS;
    const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase();

    if (!allowedExtensions.includes(fileExtension)) {
      return '지원되지 않는 형식입니다. PDF, TXT, Markdown, DOCX, PPTX, Excel, HTML, JSON만 가능합니다.';
    }

    // 분할 업로드로 대용량을 처리하되, 합리적 상한(MAX_UPLOAD_SIZE_BYTES)을 넘는 파일은 거부한다.
    if (file.size > MAX_UPLOAD_SIZE_BYTES) {
      return `파일 크기는 ${MAX_UPLOAD_SIZE_LABEL}를 초과할 수 없습니다.`;
    }

    return null;
  }, []);

  // 파일 추가
  const addFiles = useCallback((newFiles: FileList | null) => {
    if (!newFiles) return;

    const validFiles: UploadFile[] = [];
    const errors: string[] = [];

    Array.from(newFiles).forEach((file) => {
      const error = validateFile(file);
      if (error) {
        errors.push(`${file.name}: ${error}`);
      } else {
        const truncatedFileName = truncateFileName(file.name);
        const processedFile = file.name !== truncatedFileName
          ? new File([file], truncatedFileName, { type: file.type, lastModified: file.lastModified })
          : file;

        validFiles.push({
          id: `${Date.now()}_${Math.random()}`,
          file: processedFile,
          originalFileName: file.name,
          status: 'selected',
          progress: 0,
          settings: { ...globalSettings }
        });
      }
    });

    if (errors.length > 0) {
      showToast({ type: 'error', message: errors.join('\n') });
    }

    if (validFiles.length > 0) {
      setFiles((prev) => [...prev, ...validFiles]);
    }
  }, [globalSettings, showToast, validateFile, truncateFileName]);

  const markFileReady = useCallback((fileId: string) => {
    setFiles((prev) => prev.map((f) => f.id === fileId ? { ...f, status: 'ready' } : f));
  }, []);

  const markAllFilesReady = useCallback(() => {
    setFiles((prev) => prev.map((f) => f.status === 'selected' ? { ...f, status: 'ready' } : f));
  }, []);

  // 일괄 처리 시작: 즉시 전부 업로드하지 않고 슬롯 드레인 useEffect가 동시성 한도 내에서 순차 처리한다.
  const startBulkUploads = useCallback(() => {
    // 선택 상태(selected) 파일도 함께 준비(ready) 상태로 전환해 일괄 처리 대상에 포함시킨다.
    setFiles((prev) => prev.map((f) => f.status === 'selected' ? { ...f, status: 'ready' } : f));
    setIsBulkProcessing(true);
  }, []);

  const checkUploadStatus = useCallback((fileId: string, jobId: string) => {
    let checkCount = 0;
    const maxChecks = 360;
    let failureCount = 0;
    const maxFailures = 5;

    const checkInterval = setInterval(async () => {
      try {
        checkCount++;
        const response = await documentAPI.getUploadStatus(jobId);
        const status = response.data;
        failureCount = 0;

        // 백엔드 진행률(0~100)을 클램핑. 값이 없으면 undefined로 두고 기존 진행률을 유지한다.
        const backendProgress = typeof status.progress === 'number'
          ? Math.max(0, Math.min(100, status.progress))
          : undefined;

        if (status.status === 'completed' || status.status === 'completed_with_errors') {
          clearInterval(checkInterval); activeIntervalsRef.current.delete(checkInterval);
          setFiles((prev) => prev.map((f) => f.id === fileId ? {
            ...f,
            status: 'completed',
            progress: backendProgress ?? 100,
            documentId: status.documentId || status.job_id,
            processingDetails: {
              // 백엔드 processing_time은 "초" 단위이므로 1000으로 나누지 않는다(기존 1000배 축소 버그 수정).
              processingTime: status.processing_time || 0,
              chunksCount: status.chunk_count || 0,
              // 백엔드 상태 응답에 로더 타입 필드가 없으므로 파일 확장자로 추론한다(하드코딩 'Markdown' 제거).
              loaderType: inferLoaderTypeFromFile(f.file),
              // 사용자가 선택한 스플리터를 반영한다(하드코딩 'Recursive' 제거).
              splitterType: formatSplitterLabel(f.settings?.splitterType ?? globalSettings.splitterType),
              storageLocation: 'Vector Database'
            }
          } : f));
          showToast({ type: 'success', message: `업로드 완료: ${status.chunk_count || 0}개 청크` });
        } else if (status.status === 'failed') {
          clearInterval(checkInterval); activeIntervalsRef.current.delete(checkInterval);
          setFiles((prev) => prev.map((f) => f.id === fileId ? { ...f, status: 'failed', progress: backendProgress ?? f.progress, error: status.error_message || '처리 오류' } : f));
          showToast({ type: 'error', message: '문서 처리에 실패했습니다.' });
        } else if (checkCount >= maxChecks) {
          clearInterval(checkInterval); activeIntervalsRef.current.delete(checkInterval);
          setFiles((prev) => prev.map((f) => f.id === fileId ? { ...f, status: 'failed', error: '시간 초과' } : f));
        } else if (backendProgress !== undefined) {
          // 처리 중 단계: 백엔드 진행률(10→30→50→70→90)을 진행바에 실시간 반영한다.
          setFiles((prev) => prev.map((f) => f.id === fileId ? { ...f, status: 'processing', progress: backendProgress } : f));
        }
      } catch (error: unknown) {
        void error;
        failureCount++;
        if (failureCount >= maxFailures) {
          clearInterval(checkInterval); activeIntervalsRef.current.delete(checkInterval);
          setFiles((prev) => prev.map((f) => f.id === fileId ? { ...f, status: 'failed', error: '네트워크 상의 문제로 상태 확인 중단' } : f));
        }
      }
    }, 5000);
    activeIntervalsRef.current.add(checkInterval);
  }, [globalSettings.splitterType, showToast]);

  const uploadSingleFile = useCallback(async (uploadFile: UploadFile) => {
    // 중복-시작 가드: 동일 파일이 이미 시작 중이면 무시한다.
    if (startingFileIdsRef.current.has(uploadFile.id)) {
      return;
    }
    startingFileIdsRef.current.add(uploadFile.id);

    try {
      setFiles((prev) => prev.map((f) => f.id === uploadFile.id ? { ...f, status: 'uploading', error: undefined } : f));

      const response = await documentAPI.upload(
        uploadFile.file,
        (progress) => {
          setFiles((prev) => prev.map((f) => f.id === uploadFile.id ? { ...f, progress } : f));
        },
        uploadFile.settings
      );

      const responseData = response.data;
      const jobId = responseData.job_id || responseData.jobId;

      if (jobId) {
        // 처리(processing) 진입 시 진행률을 0으로 리셋해 백엔드 첫 단계(10%)부터 반영되도록 한다(기존 100% 고정 버그 수정).
        setFiles((prev) => prev.map((f) => f.id === uploadFile.id ? { ...f, status: 'processing', progress: 0 } : f));
        checkUploadStatus(uploadFile.id, jobId);
      } else {
        throw new Error(responseData.message || responseData.error || '작업 ID 생성 실패');
      }
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '업로드 중 오류가 발생했습니다.';
      setFiles((prev) => prev.map((f) => f.id === uploadFile.id ? { ...f, status: 'failed', error: errorMessage } : f));
      showToast({ type: 'error', message: `${uploadFile.file.name} 실패: ${errorMessage}` });
    } finally {
      // 가드 해제: 처리(processing) 전환 후에도 슬롯 드레인이 다음 ready 파일을 시작할 수 있게 한다.
      startingFileIdsRef.current.delete(uploadFile.id);
    }
  }, [checkUploadStatus, showToast]);

  const startSingleFileUpload = useCallback((fileId: string) => {
    // 동시성 한도 초과 시 단일 시작을 막는다.
    if (files.filter(isActiveUpload).length >= MAX_ACTIVE_UPLOADS) return;
    const file = files.find(f => f.id === fileId);
    if (file) uploadSingleFile(file);
  }, [files, uploadSingleFile]);

  const retryFailedFile = useCallback((fileId: string) => {
    if (files.filter(isActiveUpload).length >= MAX_ACTIVE_UPLOADS) return;
    // stale closure 방지: setFiles 콜백 내에서 파일을 찾아 retryTarget에 저장
    let retryTarget: UploadFile | undefined;
    setFiles(prev => prev.map(f => {
      if (f.id === fileId && f.status === 'failed') {
        const updated = { ...f, status: 'ready' as const, error: undefined, progress: 0 };
        retryTarget = updated;
        return updated;
      }
      return f;
    }));
    setTimeout(() => {
      if (retryTarget) uploadSingleFile(retryTarget);
    }, 100);
  }, [files, uploadSingleFile]);

  // 슬롯 기반 일괄 처리 드레인: 활성 업로드가 MAX_ACTIVE_UPLOADS 미만이면 빈 슬롯만큼 ready 파일을 시작한다.
  useEffect(() => {
    if (!isBulkProcessing) return;

    const activeCount = files.filter(isActiveUpload).length;
    const availableSlots = MAX_ACTIVE_UPLOADS - activeCount;
    if (availableSlots <= 0) return;

    const readyFiles = files
      .filter((file) => file.status === 'ready')
      .slice(0, availableSlots);

    if (readyFiles.length === 0) {
      // 더 시작할 ready 파일도, 진행 중인 활성 파일도 없으면 일괄 처리를 종료한다.
      if (activeCount === 0) {
        setIsBulkProcessing(false);
      }
      return;
    }

    readyFiles.forEach((file) => uploadSingleFile(file));
  }, [files, isBulkProcessing, uploadSingleFile]);

  const removeFile = useCallback((id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  }, []);

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(false); };
  const handleDrop = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(false); addFiles(e.dataTransfer.files); };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      addFiles(e.target.files);
    }
  };

  const openFilePicker = () => {
    fileInputRef.current?.click();
  };

  const handleUploadAreaKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openFilePicker();
    }
  };

  const formatFileSize = useCallback((bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }, []);

  const getStatusBadge = (status: UploadFile['status']) => {
    switch (status) {
      case 'completed': return <Badge variant="default" className="bg-emerald-500 hover:bg-emerald-600 font-bold">완료</Badge>;
      case 'failed': return <Badge variant="destructive" className="font-bold">실패</Badge>;
      case 'ready': return <Badge variant="secondary" className="font-bold">준비됨</Badge>;
      case 'uploading': return <Badge variant="outline" className="border-primary text-primary animate-pulse font-bold">업로드 중</Badge>;
      case 'processing': return <Badge variant="outline" className="border-amber-500 text-amber-500 animate-pulse font-bold">처리 중</Badge>;
      case 'selected': return <Badge variant="secondary" className="opacity-70 font-bold">선택됨</Badge>;
      default: return null;
    }
  };

  const selectedFilesCount = files.filter(f => f.status === 'selected').length;
  const readyFilesCount = files.filter(f => f.status === 'ready').length;
  const activeFilesCount = files.filter(isActiveUpload).length;
  // 일괄 처리/단일 시작 버튼 비활성 조건: 일괄 처리 중이거나 동시성 한도에 도달했을 때.
  const bulkDisabled = isBulkProcessing || activeFilesCount >= MAX_ACTIVE_UPLOADS;

  return (
    <div className="space-y-6">
      {/* 글로벌 설정 패널 (선택/준비 상태 파일이 있을 때 노출 — 준비만 한 뒤에도 일괄 처리 가능) */}
      {(selectedFilesCount > 0 || readyFilesCount > 0) && (
        <Card className="border-border/60 shadow-sm animate-in fade-in slide-in-from-top-4 duration-300">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <Settings className="w-4 h-4 text-primary" />
              업로드 설정
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-4 items-end">
              <div className="space-y-1.5 flex-1 min-w-[150px]">
                <Label className="text-[10px] uppercase font-bold text-muted-foreground ml-1">스플리터</Label>
                <Select
                  value={globalSettings.splitterType}
                  onValueChange={(value: string) => setGlobalSettings(prev => ({ ...prev, splitterType: value as UploadSettings['splitterType'] }))}
                >
                  <SelectTrigger className="h-9 rounded-xl border-border/60">
                    <SelectValue placeholder="스플리터 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="recursive">Recursive</SelectItem>
                    <SelectItem value="markdown">Markdown</SelectItem>
                    <SelectItem value="semantic">Semantic</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5 w-24">
                <Label className="text-[10px] uppercase font-bold text-muted-foreground ml-1">청크 크기</Label>
                <Input
                  type="number"
                  value={globalSettings.chunkSize}
                  onChange={(e) => setGlobalSettings(prev => ({ ...prev, chunkSize: parseInt(e.target.value) || 1500 }))}
                  className="h-9 rounded-xl border-border/60"
                />
              </div>
              <div className="space-y-1.5 w-24">
                <Label className="text-[10px] uppercase font-bold text-muted-foreground ml-1">청크 겹침</Label>
                <Input
                  type="number"
                  value={globalSettings.chunkOverlap}
                  onChange={(e) => setGlobalSettings(prev => ({ ...prev, chunkOverlap: parseInt(e.target.value) || 200 }))}
                  className="h-9 rounded-xl border-border/60"
                />
              </div>
              <div className="flex gap-2 ml-auto">
                <Button
                  data-testid="upload-bulk-process-button"
                  onClick={startBulkUploads}
                  disabled={bulkDisabled}
                  className="rounded-xl h-9 font-bold px-6 shadow-lg shadow-primary/20"
                >
                  <Play className="w-3.5 h-3.5 mr-2" />
                  {isBulkProcessing ? '일괄 처리 중...' : `일괄 처리 시작 (${selectedFilesCount + readyFilesCount})`}
                </Button>
                <Button
                  data-testid="upload-bulk-ready-button"
                  variant="outline"
                  onClick={markAllFilesReady}
                  disabled={isBulkProcessing}
                  className="rounded-xl h-9 font-bold border-border/60"
                >
                  준비만
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 업로드 영역 */}
      <div
        role="button"
        tabIndex={0}
        aria-label="업로드할 파일 선택"
        className={cn(
          "relative group cursor-pointer transition-all duration-300",
          "border-2 border-dashed rounded-[32px] p-12 text-center",
          isDragging
            ? "border-primary bg-primary/5 shadow-xl shadow-primary/10 scale-[0.99]"
            : "border-border hover:border-primary/40 hover:bg-muted/30"
        )}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={openFilePicker}
        onKeyDown={handleUploadAreaKeyDown}
      >
        <div className="flex flex-col items-center gap-4 transition-transform duration-300 group-hover:scale-105">
          <div className="w-20 h-20 rounded-3xl bg-primary/5 flex items-center justify-center text-primary transition-all group-hover:bg-primary group-hover:text-white group-hover:rotate-6">
            <UploadCloud className="w-10 h-10" />
          </div>
          <div className="space-y-2">
            <p className="text-xl font-black text-foreground">
              파일을 여기에 드래그하거나 클릭하세요
            </p>
            <p className="text-sm text-center text-muted-foreground font-medium max-w-sm mx-auto">
              PDF, TXT, Markdown, DOCX, PPTX, Excel, HTML, JSON<br />
              <span className="text-xs opacity-60">(파일당 최대 {MAX_UPLOAD_SIZE_LABEL} 지원, 대용량은 분할 업로드)</span>
            </p>
          </div>
          <span className="inline-flex h-9 items-center justify-center rounded-full border border-border/60 bg-background px-8 mt-2 text-sm font-bold transition-all group-hover:border-primary group-hover:text-primary">
            파일 선택하기
          </span>
        </div>
      </div>
      <input
        ref={fileInputRef}
        type="file"
        aria-label="업로드 파일"
        multiple
        accept={UPLOAD_ACCEPT}
        className="hidden"
        hidden
        tabIndex={-1}
        onChange={handleFileSelect}
      />

      {/* 업로드 파일 목록 */}
      {files.length > 0 && (
        <Card className="border-border/60 overflow-hidden rounded-[24px]">
          <CardHeader className="bg-muted/30 pb-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base font-bold">업로드 목록</CardTitle>
              <Badge variant="outline" className="font-bold border-primary/20 text-primary">
                {files.length} Files
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y divide-border/40">
              {files.map((file) => (
                <div key={file.id} data-testid="upload-file-row" className="p-4 hover:bg-muted/10 transition-colors">
                  <div className="flex gap-4 items-start">
                    <div className={cn(
                      "w-10 h-10 rounded-xl flex items-center justify-center shrink-0",
                      file.status === 'completed' ? "bg-emerald-500/10 text-emerald-500" :
                        file.status === 'failed' ? "bg-destructive/10 text-destructive" :
                          "bg-primary/5 text-primary"
                    )}>
                      {file.status === 'completed' ? <CheckCircle2 className="w-5 h-5" /> :
                        file.status === 'failed' ? <AlertCircle className="w-5 h-5" /> :
                          <FileText className="w-5 h-5" />}
                    </div>

                    <div className="flex-1 min-w-0 space-y-1">
                      <div className="flex items-start justify-between gap-3">
                        {/* 긴 파일명(공백 없는 CJK/URL 포함)도 컨테이너를 넘지 않도록 줄바꿈 허용 + 2줄 제한 */}
                        <p
                          className="min-w-0 flex-1 text-sm font-bold text-foreground leading-snug break-words [overflow-wrap:anywhere] line-clamp-2"
                          title={file.file.name}
                        >
                          {file.file.name}
                        </p>
                        {/* 상태 뱃지/삭제 버튼은 줄어들지 않도록 고정해 파일명과 겹침 방지 */}
                        <div className="flex shrink-0 items-center gap-2">
                          {getStatusBadge(file.status)}
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 rounded-lg text-muted-foreground/40 hover:text-destructive transition-all"
                            onClick={() => removeFile(file.id)}
                            disabled={['uploading', 'processing'].includes(file.status)}
                            aria-label={`${file.file.name} 제거`}
                          >
                            <X className="w-4 h-4" />
                          </Button>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 text-[11px] font-medium text-muted-foreground">
                        <span>{formatFileSize(file.file.size)}</span>
                        <span>•</span>
                        <span className="uppercase tracking-wider">{file.file.name.split('.').pop()}</span>
                      </div>

                      {file.error && (
                        // 공백 없는 토큰/URL 포함 장문 에러도 컨테이너 밖으로 넘치지 않도록 줄바꿈을 강제한다.
                        <div role="alert" className="mt-2 flex items-start gap-2 rounded-xl bg-destructive/5 px-3 py-2 text-destructive">
                          <AlertCircle className="h-3 w-3 shrink-0 mt-0.5" />
                          <p className="min-w-0 text-[11px] font-bold leading-tight break-words [overflow-wrap:anywhere]">
                            {file.error}
                          </p>
                        </div>
                      )}

                      {(file.status === 'uploading' || file.status === 'processing') && (
                        <div className="mt-3 space-y-1.5">
                          <div className="flex justify-between text-[10px] font-bold uppercase tracking-tighter">
                            <span className="text-primary">{file.status === 'uploading' ? 'Uploading...' : 'Processing...'}</span>
                            <span>{file.progress}%</span>
                          </div>
                          <Progress value={file.progress} className="h-1" />
                        </div>
                      )}

                      {file.status === 'completed' && file.processingDetails && (
                        <ProcessingDetails details={file.processingDetails} />
                      )}

                      <div className="flex gap-2 mt-3">
                        {file.status === 'selected' && (
                          <Button data-testid="upload-ready-button" size="sm" variant="outline" className="h-7 text-[11px] font-bold rounded-lg" onClick={() => markFileReady(file.id)}>
                            준비
                          </Button>
                        )}
                        {file.status === 'ready' && (
                          <Button data-testid="upload-start-button" size="sm" className="h-7 text-[11px] font-bold rounded-lg shadow-sm" onClick={() => startSingleFileUpload(file.id)} disabled={bulkDisabled}>
                            <Play className="w-3 h-3 mr-1" /> 시작
                          </Button>
                        )}
                        {file.status === 'failed' && (
                          <Button size="sm" variant="outline" className="h-7 text-[11px] font-bold rounded-lg border-destructive/30 text-destructive hover:bg-destructive/10" onClick={() => retryFailedFile(file.id)} disabled={bulkDisabled}>
                            <RefreshCw className="w-3 h-3 mr-1" /> 재시도
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

const ProcessingDetails = ({ details }: { details: UploadFile['processingDetails'] }) => {
  const [expanded, setExpanded] = useState(false);
  if (!details) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-[11px] font-bold text-primary flex items-center gap-1 hover:underline"
      >
        처리 상세 정보 {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>
      {expanded && (
        <div className="mt-2 p-3 rounded-xl bg-primary/5 border border-primary/10 grid grid-cols-2 gap-x-4 gap-y-2 animate-in slide-in-from-top-1">
          {/* 백엔드가 초 단위로 반환하므로 1000으로 나누지 않는다(기존 1000배 축소 버그 수정). */}
          <DetailItem icon={Clock} label="처리 시간" value={`${details.processingTime.toFixed(2)}초`} />
          <DetailItem icon={Layers} label="청크" value={`${details.chunksCount}개`} />
          <DetailItem icon={Cpu} label="로더/스플리터" value={`${details.loaderType} / ${details.splitterType}`} />
          <DetailItem icon={Database} label="저장 위치" value={details.storageLocation} />
        </div>
      )}
    </div>
  );
};

const DetailItem = ({ icon: Icon, label, value }: { icon: React.ElementType, label: string, value: string }) => (
  <div className="flex items-center gap-2">
    <Icon className="w-3 h-3 text-primary/60 shrink-0" />
    <div className="min-w-0">
      <p className="text-[9px] uppercase font-black text-muted-foreground/60 leading-none mb-0.5">{label}</p>
      <p className="text-[11px] font-bold text-foreground truncate">{value}</p>
    </div>
  </div>
);
