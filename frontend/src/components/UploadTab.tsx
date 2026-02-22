import React, { useState, useRef, useCallback } from 'react';
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
} from 'lucide-react';
import { ToastMessage } from '../types';
import { documentAPI } from '../services/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
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
    embedderModel: string;
    storageLocation: string;
  };
}

export const UploadTab: React.FC<UploadTabProps> = ({ showToast }) => {
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [globalSettings, setGlobalSettings] = useState<UploadSettings>({
    splitterType: 'recursive',
    chunkSize: 1500,
    chunkOverlap: 200
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
    const allowedExtensions = ['.pdf', '.txt', '.md', '.markdown', '.doc', '.docx', '.xls', '.xlsx', '.html', '.htm', '.json'];
    const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase();
    const maxSize = 50 * 1024 * 1024; // 50MB

    if (!allowedExtensions.includes(fileExtension)) {
      return '지원되지 않는 형식입니다. PDF, TXT, Markdown, Word, Excel, HTML, JSON만 가능합니다.';
    }

    if (file.size > maxSize) {
      return '파일 크기는 50MB를 초과할 수 없습니다.';
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

  const markFileReady = (fileId: string) => {
    setFiles((prev) => prev.map((f) => f.id === fileId ? { ...f, status: 'ready' } : f));
  };

  const markAllFilesReadyAndStart = () => {
    const selectedFiles = files.filter(f => f.status === 'selected');
    setFiles((prev) => prev.map((f) => f.status === 'selected' ? { ...f, status: 'ready' } : f));

    setTimeout(() => {
      selectedFiles.forEach(file => {
        uploadSingleFile({ ...file, status: 'ready' });
      });
    }, 200);
  };

  const markAllFilesReady = () => {
    setFiles((prev) => prev.map((f) => f.status === 'selected' ? { ...f, status: 'ready' } : f));
  };

  const startSingleFileUpload = (fileId: string) => {
    const file = files.find(f => f.id === fileId);
    if (file) uploadSingleFile(file);
  };

  const retryFailedFile = (fileId: string) => {
    setFiles(prev => prev.map(f => f.id === fileId && f.status === 'failed' ? { ...f, status: 'ready', error: undefined, progress: 0 } : f));
    setTimeout(() => {
      const file = files.find(f => f.id === fileId);
      if (file) uploadSingleFile({ ...file, status: 'ready', error: undefined, progress: 0 });
    }, 100);
  };

  const startAllUploads = () => {
    files.filter(f => f.status === 'ready').forEach(file => uploadSingleFile(file));
  };
  void startAllUploads; // retained for future use

  const uploadSingleFile = async (uploadFile: UploadFile) => {
    try {
      setFiles((prev) => prev.map((f) => f.id === uploadFile.id ? { ...f, status: 'uploading' } : f));

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
        setFiles((prev) => prev.map((f) => f.id === uploadFile.id ? { ...f, status: 'processing', progress: 100 } : f));
        checkUploadStatus(uploadFile.id, jobId);
      } else {
        throw new Error(responseData.message || responseData.error || '작업 ID 생성 실패');
      }
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : '업로드 중 오류가 발생했습니다.';
      setFiles((prev) => prev.map((f) => f.id === uploadFile.id ? { ...f, status: 'failed', error: errorMessage } : f));
      showToast({ type: 'error', message: `${uploadFile.file.name} 실패: ${errorMessage}` });
    }
  };

  const checkUploadStatus = async (fileId: string, jobId: string) => {
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

        if (status.status === 'completed' || status.status === 'completed_with_errors') {
          clearInterval(checkInterval);
          setFiles((prev) => prev.map((f) => f.id === fileId ? {
            ...f,
            status: 'completed',
            documentId: status.documentId || status.job_id,
            processingDetails: {
              processingTime: status.processing_time || 0,
              chunksCount: status.chunk_count || 0,
              loaderType: 'Markdown',
              splitterType: 'Recursive',
              embedderModel: 'OpenAI',
              storageLocation: 'Vector Database'
            }
          } : f));
          showToast({ type: 'success', message: `업로드 완료: ${status.chunk_count || 0}개 청크` });
        } else if (status.status === 'failed') {
          clearInterval(checkInterval);
          setFiles((prev) => prev.map((f) => f.id === fileId ? { ...f, status: 'failed', error: status.error_message || '처리 오류' } : f));
          showToast({ type: 'error', message: '문서 처리에 실패했습니다.' });
        } else if (checkCount >= maxChecks) {
          clearInterval(checkInterval);
          setFiles((prev) => prev.map((f) => f.id === fileId ? { ...f, status: 'failed', error: '시간 초과' } : f));
        }
      } catch (error: unknown) {
        void error;
        failureCount++;
        if (failureCount >= maxFailures) {
          clearInterval(checkInterval);
          setFiles((prev) => prev.map((f) => f.id === fileId ? { ...f, status: 'failed', error: '네트워크 상의 문제로 상태 확인 중단' } : f));
        }
      }
    }, 5000);
  };

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
  const processingFilesCount = files.filter(f => ['uploading', 'processing'].includes(f.status)).length;

  return (
    <div className="space-y-6">
      {/* 글로벌 설정 패널 */}
      {(selectedFilesCount > 0) && (
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
                  onClick={markAllFilesReadyAndStart}
                  disabled={processingFilesCount > 0}
                  className="rounded-xl h-9 font-bold px-6 shadow-lg shadow-primary/20"
                >
                  <Play className="w-3.5 h-3.5 mr-2" />
                  일괄 처리 시작 ({selectedFilesCount})
                </Button>
                <Button
                  variant="outline"
                  onClick={markAllFilesReady}
                  disabled={processingFilesCount > 0}
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
        onClick={() => fileInputRef.current?.click()}
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
              PDF, TXT, Markdown, Word, Excel, HTML, JSON<br />
              <span className="text-xs opacity-60">(파일당 최대 50MB 지원)</span>
            </p>
          </div>
          <Button variant="outline" className="rounded-full font-bold px-8 mt-2 border-border/60 transition-all hover:border-primary hover:text-primary">
            파일 선택하기
          </Button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.txt,.md,.markdown,.doc,.docx,.xls,.xlsx,.html,.htm,.json"
          className="hidden"
          onChange={handleFileSelect}
        />
      </div>

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
                <div key={file.id} className="p-4 hover:bg-muted/10 transition-colors">
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
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-bold text-foreground truncate max-w-[70%]">
                          {file.file.name}
                        </p>
                        <div className="flex items-center gap-2">
                          {getStatusBadge(file.status)}
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 rounded-lg text-muted-foreground/40 hover:text-destructive transition-all"
                            onClick={() => removeFile(file.id)}
                            disabled={['uploading', 'processing'].includes(file.status)}
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
                        <Alert variant="destructive" className="mt-2 py-2 bg-destructive/5 border-none rounded-xl">
                          <AlertCircle className="h-3 w-3" />
                          <AlertDescription className="text-[11px] font-bold">
                            {file.error}
                          </AlertDescription>
                        </Alert>
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
                          <Button size="sm" variant="outline" className="h-7 text-[11px] font-bold rounded-lg" onClick={() => markFileReady(file.id)}>
                            준비
                          </Button>
                        )}
                        {file.status === 'ready' && (
                          <Button size="sm" className="h-7 text-[11px] font-bold rounded-lg shadow-sm" onClick={() => startSingleFileUpload(file.id)} disabled={processingFilesCount > 0}>
                            <Play className="w-3 h-3 mr-1" /> 시작
                          </Button>
                        )}
                        {file.status === 'failed' && (
                          <Button size="sm" variant="outline" className="h-7 text-[11px] font-bold rounded-lg border-destructive/30 text-destructive hover:bg-destructive/10" onClick={() => retryFailedFile(file.id)}>
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
          <DetailItem icon={Clock} label="처리 시간" value={`${(details.processingTime / 1000).toFixed(2)}초`} />
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