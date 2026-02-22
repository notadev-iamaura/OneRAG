import React, { useState, useEffect, useCallback } from 'react';
import { logger } from '../utils/logger';
import {
  Search,
  Trash2,
  Info,
  Download,
  RotateCw,
  Trash,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
  List as ListIcon,
  LayoutGrid,
  AlertTriangle,
  ArrowUp,
  ArrowDown,
  MoreHorizontal,
  ChevronLeft,
  ChevronRight,
  ShieldAlert,
  FileText,
} from 'lucide-react';
import { Document, ToastMessage } from '../types';
import { documentAPI } from '../services/api';
import { Card, CardContent, CardHeader, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';

interface DocumentsTabProps {
  showToast: (message: Omit<ToastMessage, 'id'>) => void;
}

export const DocumentsTab: React.FC<DocumentsTabProps> = ({ showToast }) => {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDocuments, setSelectedDocuments] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false);
  const [deleteAllConfirmOpen, setDeleteAllConfirmOpen] = useState(false);
  const [deleteAllStep, setDeleteAllStep] = useState<'confirm' | 'typing'>("confirm");
  const [deleteAllTyping, setDeleteAllTyping] = useState('');
  const [documentToDelete, setDocumentToDelete] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [bulkDeleteLoading, setBulkDeleteLoading] = useState(false);
  const [deleteAllLoading, setDeleteAllLoading] = useState(false);

  const [sortField, setSortField] = useState<'filename' | 'size' | 'uploadedAt' | 'type'>('uploadedAt');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('list');
  const [fetchError, setFetchError] = useState(false);

  const handleDeleteCancel = useCallback(() => {
    setDeleteConfirmOpen(false);
    setDocumentToDelete(null);
  }, []);

  const handleBulkDeleteCancel = useCallback(() => {
    setBulkDeleteConfirmOpen(false);
  }, []);

  const handleDeleteAllCancel = useCallback(() => {
    setDeleteAllConfirmOpen(false);
    setDeleteAllStep('confirm');
    setDeleteAllTyping('');
  }, []);

  const pageSize = 50;

  const sortDocuments = useCallback((docs: Document[]) => {
    return [...docs].sort((a, b) => {
      let aValue: string | number;
      let bValue: string | number;

      switch (sortField) {
        case 'filename':
          aValue = (a.originalName || a.filename).toLowerCase();
          bValue = (b.originalName || b.filename).toLowerCase();
          break;
        case 'size':
          aValue = a.size;
          bValue = b.size;
          break;
        case 'uploadedAt':
          aValue = new Date(a.uploadedAt).getTime();
          bValue = new Date(b.uploadedAt).getTime();
          break;
        case 'type':
          aValue = (a.originalName || a.filename).split('.').pop()?.toLowerCase() || '';
          bValue = (b.originalName || b.filename).split('.').pop()?.toLowerCase() || '';
          break;
        default:
          return 0;
      }

      if (aValue < bValue) return sortDirection === 'asc' ? -1 : 1;
      if (aValue > bValue) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });
  }, [sortField, sortDirection]);

  void handleSort;

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    setFetchError(false);
    try {
      const response = await documentAPI.getDocuments({
        page,
        limit: pageSize,
        search: searchQuery,
      });
      const sortedDocuments = sortDocuments(response.data.documents);
      setDocuments(sortedDocuments);
      setTotalPages(Math.ceil(response.data.total / pageSize));
    } catch {
      setFetchError(true);
      showToast({ type: 'error', message: '문서 목록 로드 실패' });
    } finally {
      setLoading(false);
    }
  }, [page, searchQuery, showToast, sortDocuments]);

  useEffect(() => { fetchDocuments(); }, [fetchDocuments]);

  const isValidDocumentId = (id: string): boolean => Boolean(id && !id.startsWith('temp-') && id.trim() !== '');

  const toggleDocumentSelection = (id: string) => {
    if (!isValidDocumentId(id)) {
      showToast({ type: 'warning', message: '선택할 수 없는 문서입니다.' });
      return;
    }
    const newSelection = new Set(selectedDocuments);
    if (newSelection.has(id)) newSelection.delete(id);
    else newSelection.add(id);
    setSelectedDocuments(newSelection);
  };

  const toggleSelectAll = () => {
    const validIds = documents.filter(doc => isValidDocumentId(doc.id)).map(doc => doc.id);
    if (selectedDocuments.size === validIds.length) setSelectedDocuments(new Set());
    else setSelectedDocuments(new Set(validIds));
  };

  const handleViewDetails = (document: Document) => {
    setSelectedDocument(document);
    setDetailsOpen(true);
  };

  const handleDeleteClick = useCallback((id: string) => {
    setDocumentToDelete(id);
    setDeleteConfirmOpen(true);
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
    if (!documentToDelete) return;
    setDeleteLoading(true);
    try {
      await documentAPI.deleteDocument(documentToDelete);
      showToast({ type: 'success', message: '문서 삭제 완료' });
      await fetchDocuments();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      logger.error('Document delete error:', error);
      showToast({ type: 'error', message: err.response?.data?.message || '삭제 실패' });
    } finally {
      setDeleteLoading(false);
      setDeleteConfirmOpen(false);
      setDocumentToDelete(null);
    }
  }, [documentToDelete, showToast, fetchDocuments]);

  const handleBulkDelete = useCallback(async () => {
    if (selectedDocuments.size === 0) {
      setBulkDeleteConfirmOpen(false);
      return;
    }
    setBulkDeleteLoading(true);
    try {
      const documentIds = Array.from(selectedDocuments).filter(isValidDocumentId);
      logger.log('Deleting documents:', documentIds);

      if (documentIds.length === 0) {
        showToast({
          type: 'warning',
          message: '삭제할 수 있는 유효한 문서가 없습니다.',
        });
        return;
      }

      await documentAPI.deleteDocuments(documentIds);
      showToast({ type: 'success', message: `${documentIds.length}개 문서 삭제 완료` });
      setSelectedDocuments(new Set());
      await fetchDocuments();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      logger.error('Bulk delete error:', error);
      showToast({ type: 'error', message: err.response?.data?.message || '일괄 삭제 실패' });
    } finally {
      setBulkDeleteLoading(false);
      setBulkDeleteConfirmOpen(false);
    }
  }, [selectedDocuments, showToast, fetchDocuments]);

  const handleDeleteAll = useCallback(async () => {
    if (deleteAllStep === 'confirm') {
      setDeleteAllStep('typing');
      return;
    }
    if (deleteAllTyping !== '문서 삭제에 동의합니다.') {
      showToast({ type: 'error', message: '문구를 정확히 입력해주세요.' });
      return;
    }
    setDeleteAllLoading(true);
    try {
      await documentAPI.deleteAllDocuments('DELETE_ALL_DOCUMENTS', '사용자 요청', false);
      showToast({ type: 'success', message: '모든 문서 삭제 완료' });
      setSelectedDocuments(new Set());
      await fetchDocuments();
      handleDeleteAllCancel();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      logger.error('Delete all documents error:', error);
      showToast({ type: 'error', message: err.response?.data?.message || '실패' });
    } finally {
      setDeleteAllLoading(false);
    }
  }, [deleteAllStep, deleteAllTyping, showToast, fetchDocuments, handleDeleteAllCancel]);

  const handleDownload = async (document: Document) => {
    try {
      const response = await documentAPI.downloadDocument(document.id);
      const blob = new Blob([response.data]);
      const url = window.URL.createObjectURL(blob);
      const a = globalThis.document.createElement('a');
      a.href = url;
      a.download = document.originalName || document.filename;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch {
      showToast({ type: 'error', message: '다운로드 실패' });
    }
  };

  const getStatusIcon = (status: Document['status']) => {
    switch (status) {
      case 'completed': return <CheckCircle2 className="w-4 h-4 text-emerald-500" />;
      case 'processing': return <RotateCw className="w-4 h-4 text-amber-500 animate-spin" />;
      case 'failed': return <AlertCircle className="w-4 h-4 text-destructive" />;
      default: return <HelpCircle className="w-4 h-4 text-muted-foreground" />;
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  return (
    <div className="space-y-6">
      {/* 툴바 */}
      <Card className="border-border/60 shadow-sm overflow-visible">
        <CardContent className="p-4">
          <div className="flex flex-col lg:flex-row gap-4">
            {/* 검색 및 정렬 */}
            <div className="flex flex-1 gap-2">
              <div className="relative flex-1 max-w-sm">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="문서 검색..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-10 rounded-xl border-border/60 focus-visible:ring-primary/20"
                />
              </div>
              <div className="w-40 shrink-0">
                <Select value={sortField} onValueChange={(v: string) => setSortField(v as typeof sortField)}>
                  <SelectTrigger className="rounded-xl border-border/60 font-bold">
                    <SelectValue placeholder="정렬 기준" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="uploadedAt">업로드 일시</SelectItem>
                    <SelectItem value="filename">파일명</SelectItem>
                    <SelectItem value="size">파일 크기</SelectItem>
                    <SelectItem value="type">파일 타입</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc')}
                className="rounded-xl border border-border/60 shrink-0 hover:bg-muted"
              >
                {sortDirection === 'asc' ? <ArrowUp className="w-4 h-4" /> : <ArrowDown className="w-4 h-4" />}
              </Button>
            </div>

            {/* 보기 모드 및 액션 */}
            <div className="flex items-center gap-3">
              <div className="flex p-1 bg-muted/50 rounded-xl border border-border/40 shrink-0">
                <Button
                  variant={viewMode === 'list' ? 'secondary' : 'ghost'}
                  size="icon"
                  onClick={() => setViewMode('list')}
                  className={cn("h-8 w-8 rounded-lg", viewMode === 'list' && "shadow-sm bg-background")}
                >
                  <ListIcon className="w-4 h-4" />
                </Button>
                <Button
                  variant={viewMode === 'grid' ? 'secondary' : 'ghost'}
                  size="icon"
                  onClick={() => setViewMode('grid')}
                  className={cn("h-8 w-8 rounded-lg", viewMode === 'grid' && "shadow-sm bg-background")}
                >
                  <LayoutGrid className="w-4 h-4" />
                </Button>
              </div>

              <Separator orientation="vertical" className="h-8 hidden lg:block" />

              <div className="flex items-center gap-2">
                {selectedDocuments.size > 0 && (
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setBulkDeleteConfirmOpen(true)}
                    className="rounded-xl h-9 font-bold px-4 animate-in zoom-in duration-200"
                  >
                    <Trash className="w-4 h-4 mr-2" />
                    선택 삭제 ({selectedDocuments.size})
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setDeleteAllConfirmOpen(true)}
                  className="rounded-xl h-9 font-bold border-destructive/30 text-destructive hover:bg-destructive/10"
                >
                  <AlertTriangle className="w-4 h-4 mr-2" />
                  전체 삭제
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={fetchDocuments}
                  className="rounded-xl h-9 w-9 text-primary hover:bg-primary/10"
                >
                  <RotateCw className={cn("w-4 h-4", loading && "animate-spin")} />
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 리스트/그리드 컨텐츠 */}
      {fetchError ? (
        <Card className="border-destructive/30 bg-destructive/5 py-16 flex flex-col items-center justify-center text-center gap-4 px-6">
          <div className="w-16 h-16 rounded-full bg-destructive/10 flex items-center justify-center mb-2">
            <AlertCircle className="w-8 h-8 text-destructive" />
          </div>
          <p className="text-lg font-black text-foreground">문서 목록을 불러올 수 없습니다</p>
          <p className="text-sm text-muted-foreground max-w-xs">
            백엔드 연결을 확인하거나 아래 버튼을 눌러 다시 시도해주세요.
          </p>
          <Button
            onClick={fetchDocuments}
            variant="default"
            className="gap-2 font-bold px-6 rounded-xl shadow-lg shadow-primary/20"
          >
            <RotateCw className="w-4 h-4" />
            다시 시도
          </Button>
        </Card>
      ) : loading ? (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
          <RotateCw className="w-10 h-10 text-primary animate-spin opacity-20" />
          <p className="text-sm font-bold text-muted-foreground animate-pulse">문서 목록을 불러오는 중...</p>
        </div>
      ) : documents.length === 0 ? (
        <Card className="border-dashed border-2 py-20 flex flex-col items-center justify-center text-center">
          <div className="w-20 h-20 rounded-full bg-muted/30 flex items-center justify-center mb-4">
            <Search className="w-10 h-10 text-muted-foreground/40" />
          </div>
          <p className="text-lg font-black text-foreground">문서가 없습니다</p>
          <p className="text-sm text-muted-foreground">검색어를 바꾸거나 새 문서를 업로드해 보세요</p>
        </Card>
      ) : (
        <>
          {viewMode === 'list' ? (
            <Card className="border-border/60 overflow-hidden rounded-[24px]">
              <Table>
                <TableHeader className="bg-muted/30 hover:bg-muted/30">
                  <TableRow className="border-b-border/40">
                    <TableHead className="w-[50px]">
                      <Checkbox
                        checked={selectedDocuments.size === documents.filter(d => isValidDocumentId(d.id)).length && documents.length > 0}
                        onCheckedChange={toggleSelectAll}
                        className="rounded-md border-border/60"
                      />
                    </TableHead>
                    <TableHead className="font-bold py-4">파일명</TableHead>
                    <TableHead className="font-bold">크기</TableHead>
                    <TableHead className="font-bold">업로드 일시</TableHead>
                    <TableHead className="font-bold">상태</TableHead>
                    <TableHead className="text-right font-bold pr-6">액션</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {documents.map((doc) => (
                    <TableRow key={doc.id} className={cn("group hover:bg-muted/10 transition-colors border-b-border/40", selectedDocuments.has(doc.id) && "bg-primary/5")}>
                      <TableCell>
                        <Checkbox
                          checked={selectedDocuments.has(doc.id)}
                          onCheckedChange={() => toggleDocumentSelection(doc.id)}
                          disabled={!isValidDocumentId(doc.id)}
                          className="rounded-md border-border/60"
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg bg-primary/5 flex items-center justify-center shrink-0">
                            {getStatusIcon(doc.status)}
                          </div>
                          <p className="text-sm font-bold truncate max-w-[300px]" title={doc.originalName || doc.filename}>
                            {doc.originalName || doc.filename}
                          </p>
                        </div>
                      </TableCell>
                      <TableCell className="text-xs font-medium text-muted-foreground">
                        {formatFileSize(doc.size)}
                      </TableCell>
                      <TableCell className="text-xs font-medium text-muted-foreground">
                        {new Date(doc.uploadedAt).toLocaleString('ko-KR', {
                          year: 'numeric', month: '2-digit', day: '2-digit',
                          hour: '2-digit', minute: '2-digit'
                        })}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={cn(
                          "font-bold text-[10px] uppercase tracking-wider",
                          doc.status === 'completed' ? "bg-emerald-500/10 text-emerald-600 border-emerald-200" :
                            doc.status === 'failed' ? "bg-destructive/10 text-destructive border-destructive/20" :
                              "bg-amber-500/10 text-amber-600 border-amber-200"
                        )}>
                          {doc.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right pr-6">
                        <div className="flex justify-end gap-1 opacity-100 lg:opacity-0 group-hover:opacity-100 transition-opacity">
                          <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg hover:bg-primary/10 hover:text-primary" onClick={() => handleViewDetails(doc)}>
                            <Info className="w-4 h-4" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg hover:bg-primary/10 hover:text-primary" onClick={() => handleDownload(doc)}>
                            <Download className="w-4 h-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 rounded-lg hover:bg-destructive/10 hover:text-destructive"
                            onClick={() => handleDeleteClick(doc.id)}
                            disabled={!isValidDocumentId(doc.id)}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {documents.map((doc) => (
                <Card key={doc.id} className={cn(
                  "group transition-all duration-300 rounded-[28px] border-border/60 hover:shadow-xl hover:shadow-primary/5 hover:border-primary/30",
                  selectedDocuments.has(doc.id) && "border-primary ring-2 ring-primary/10"
                )}>
                  <CardHeader className="p-4 flex flex-row items-start justify-between space-y-0">
                    <div className="w-12 h-12 rounded-2xl bg-primary/5 flex items-center justify-center text-primary group-hover:bg-primary group-hover:text-white transition-all">
                      <FileText className="w-6 h-6" />
                    </div>
                    <Checkbox
                      checked={selectedDocuments.has(doc.id)}
                      onCheckedChange={() => toggleDocumentSelection(doc.id)}
                      disabled={!isValidDocumentId(doc.id)}
                      className="rounded-md border-border/60"
                    />
                  </CardHeader>
                  <CardContent className="px-4 pb-2">
                    <h3 className="text-sm font-black text-foreground truncate mb-1" title={doc.originalName || doc.filename}>
                      {doc.originalName || doc.filename}
                    </h3>
                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] font-bold text-muted-foreground/60 uppercase tracking-wider">
                      <span className="flex items-center gap-1">
                        <MoreHorizontal className="w-3 h-3" /> {formatFileSize(doc.size)}
                      </span>
                      <span className="flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3" /> {doc.chunks || 0} Chunks
                      </span>
                    </div>
                    <div className="mt-4 flex items-center justify-between">
                      <Badge variant="outline" className={cn(
                        "font-extrabold text-[9px] uppercase h-5",
                        doc.status === 'completed' ? "bg-emerald-500 text-white border-none" : "bg-muted text-muted-foreground border-none"
                      )}>
                        {doc.status}
                      </Badge>
                      <span className="text-[10px] text-muted-foreground font-medium">
                        {new Date(doc.uploadedAt).toLocaleDateString()}
                      </span>
                    </div>
                  </CardContent>
                  <CardFooter className="p-2 pt-0 bg-muted/10 rounded-b-[28px] mt-2 group-hover:bg-muted/30 transition-colors gap-1">
                    <Button variant="ghost" size="sm" className="flex-1 h-8 text-[11px] font-bold rounded-xl" onClick={() => handleViewDetails(doc)}>상세</Button>
                    <Button variant="ghost" size="sm" className="flex-1 h-8 text-[11px] font-bold rounded-xl" onClick={() => handleDownload(doc)}>받기</Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="flex-1 h-8 text-[11px] font-bold rounded-xl text-destructive hover:bg-destructive/10"
                      onClick={() => handleDeleteClick(doc.id)}
                      disabled={!isValidDocumentId(doc.id)}
                    >
                      삭제
                    </Button>
                  </CardFooter>
                </Card>
              ))}
            </div>
          )}

          {/* 페이지네이션 */}
          <div className="flex items-center justify-center gap-2 py-8">
            <Button
              variant="outline"
              size="icon"
              disabled={page === 1}
              onClick={() => setPage(1)}
              className="rounded-xl h-9 w-9 border-border/60"
            >
              <ChevronLeft className="w-4 h-4 mr-[-1px]" />
              <ChevronLeft className="w-4 h-4 ml-[-1px]" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              disabled={page === 1}
              onClick={() => setPage(p => p - 1)}
              className="rounded-xl h-9 w-9 border-border/60"
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>

            <div className="flex items-center gap-1 mx-2">
              <span className="text-sm font-black">Page {page}</span>
              <span className="text-sm text-muted-foreground font-bold">of {totalPages}</span>
            </div>

            <Button
              variant="outline"
              size="icon"
              disabled={page === totalPages}
              onClick={() => setPage(p => p + 1)}
              className="rounded-xl h-9 w-9 border-border/60"
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              disabled={page === totalPages}
              onClick={() => setPage(totalPages)}
              className="rounded-xl h-9 w-9 border-border/60"
            >
              <ChevronRight className="w-4 h-4 mr-[-1px]" />
              <ChevronRight className="w-4 h-4 ml-[-1px]" />
            </Button>
          </div>
        </>
      )}

      {/* 상세 정보 다이얼로그 */}
      <Dialog open={detailsOpen} onOpenChange={setDetailsOpen}>
        <DialogContent className="max-w-md rounded-[28px] border-border/40 p-0 overflow-hidden">
          <DialogHeader className="p-6 pb-4 bg-muted/30">
            <DialogTitle className="text-xl font-black">문서 상세 정보</DialogTitle>
            <DialogDescription className="text-sm font-medium">문서의 메타데이터와 상태 정보를 확인합니다</DialogDescription>
          </DialogHeader>
          <div className="p-6 pt-0 space-y-4">
            <ScrollArea className="max-h-[60vh] pr-4">
              {selectedDocument && (
                <div className="space-y-4">
                  <DetailRow label="파일명" value={selectedDocument.originalName} />
                  <DetailRow label="문서 ID" value={selectedDocument.id} copyable />
                  <DetailRow label="파일 크기" value={formatFileSize(selectedDocument.size)} />
                  <DetailRow label="MIME 타입" value={selectedDocument.mimeType} />
                  <DetailRow label="업로드 일시" value={new Date(selectedDocument.uploadedAt).toLocaleString()} />
                  <DetailRow label="상태" value={selectedDocument.status} />
                  {selectedDocument.chunks && <DetailRow label="청크 수" value={`${selectedDocument.chunks}개`} />}
                  {selectedDocument.metadata?.pageCount && <DetailRow label="페이지 수" value={`${selectedDocument.metadata.pageCount}P`} />}
                  {selectedDocument.metadata?.wordCount && <DetailRow label="단어 수" value={`${selectedDocument.metadata.wordCount}개`} />}
                </div>
              )}
            </ScrollArea>
          </div>
          <DialogFooter className="p-6 bg-muted/10">
            <Button variant="secondary" className="rounded-xl font-bold w-full" onClick={() => setDetailsOpen(false)}>닫기</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 삭제 확인 다이얼로그 */}
      <Dialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <DialogContent className="rounded-[28px] max-w-sm">
          <DialogHeader>
            <div className="w-12 h-12 rounded-2xl bg-destructive/10 text-destructive flex items-center justify-center mb-4">
              <Trash2 className="w-6 h-6" />
            </div>
            <DialogTitle className="text-xl font-black">문서 삭제</DialogTitle>
            <DialogDescription className="font-medium text-sm">
              이 문서를 삭제하시겠습니까? <br />이 작업은 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 mt-4">
            <Button variant="ghost" onClick={handleDeleteCancel} disabled={deleteLoading} className="rounded-xl font-bold">취소</Button>
            <Button variant="destructive" onClick={handleDeleteConfirm} disabled={deleteLoading} className="rounded-xl font-bold shadow-lg shadow-destructive/20">
              {deleteLoading ? <RotateCw className="w-4 h-4 mr-2 animate-spin" /> : null}
              {deleteLoading ? '삭제 중...' : '삭제하기'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 일괄 삭제 확인 다이얼로그 */}
      <Dialog open={bulkDeleteConfirmOpen} onOpenChange={setBulkDeleteConfirmOpen}>
        <DialogContent className="rounded-[28px] max-w-sm">
          <DialogHeader>
            <div className="w-12 h-12 rounded-2xl bg-destructive/10 text-destructive flex items-center justify-center mb-4">
              <ShieldAlert className="w-6 h-6" />
            </div>
            <DialogTitle className="text-xl font-black">{selectedDocuments.size}개 문서 삭제</DialogTitle>
            <DialogDescription className="font-medium text-sm">
              선택한 모든 문서를 영구적으로 삭제합니다.<br />정말 진행하시겠습니까?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 mt-4">
            <Button variant="ghost" onClick={handleBulkDeleteCancel} disabled={bulkDeleteLoading} className="rounded-xl font-bold">취소</Button>
            <Button variant="destructive" onClick={handleBulkDelete} disabled={bulkDeleteLoading} className="rounded-xl font-bold shadow-lg shadow-destructive/20">
              {bulkDeleteLoading ? <RotateCw className="w-4 h-4 mr-2 animate-spin" /> : null}
              삭제 승인
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 전체 삭제 확인 다이얼로그 (CRITICAL) */}
      <Dialog open={deleteAllConfirmOpen} onOpenChange={setDeleteAllConfirmOpen}>
        <DialogContent className="rounded-[32px] max-w-md border-destructive/20">
          <DialogHeader>
            <div className="w-16 h-16 rounded-3xl bg-destructive text-white flex items-center justify-center mb-6 mx-auto shadow-2xl shadow-destructive/40 rotate-12">
              <AlertTriangle className="w-8 h-8" />
            </div>
            <DialogTitle className="text-2xl font-black text-center">전체 문서 삭제</DialogTitle>
            <DialogDescription className="text-center font-bold text-destructive px-4">
              위험! DB의 모든 문서 데이터가 영구적으로 삭제됩니다. 이 작업은 즉시 실행되며 복구가 불가능합니다.
            </DialogDescription>
          </DialogHeader>

          {deleteAllStep === 'typing' && (
            <div className="mt-6 space-y-4 animate-in fade-in slide-in-from-top-4">
              <p className="text-sm font-black text-center">
                실행하시려면 아래 문구를 정확히 입력하세요:
                <br />
                <span className="text-primary mt-2 block backdrop-blur-sm bg-primary/5 p-2 rounded-lg italic">"문서 삭제에 동의합니다."</span>
              </p>
              <Input
                value={deleteAllTyping}
                onChange={(e) => setDeleteAllTyping(e.target.value)}
                placeholder="문구를 입력하세요"
                className="text-center font-bold border-destructive/40 focus-visible:ring-destructive/20 rounded-xl h-12"
              />
            </div>
          )}

          <DialogFooter className="mt-8 flex-col sm:flex-col gap-3">
            <Button
              variant={deleteAllStep === 'confirm' ? 'destructive' : 'default'}
              className={cn("w-full h-12 rounded-xl font-black text-base shadow-xl", deleteAllStep === 'confirm' ? "shadow-destructive/30" : "bg-black hover:bg-zinc-800 shadow-zinc-200")}
              onClick={handleDeleteAll}
              disabled={deleteAllLoading || (deleteAllStep === 'typing' && deleteAllTyping !== '문서 삭제에 동의합니다.')}
            >
              {deleteAllLoading ? <RotateCw className="w-5 h-5 mr-2 animate-spin" /> : null}
              {deleteAllStep === 'confirm' ? '네, 정말 모두 삭제합니다' : '전체 삭제 실행'}
            </Button>
            <Button variant="ghost" className="w-full font-bold h-12 rounded-xl" onClick={handleDeleteAllCancel} disabled={deleteAllLoading}>
              지금 중단하고 돌아가기
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

const DetailRow = ({ label, value, copyable }: { label: string, value: string | number | undefined | null, copyable?: boolean }) => (
  <div className="group/row">
    <p className="text-[10px] uppercase font-black text-muted-foreground/60 mb-1 tracking-wider">{label}</p>
    <div className="flex items-center justify-between p-3 rounded-xl bg-muted/30 border border-transparent group-hover/row:border-border/60 transition-all">
      <p className="text-sm font-bold text-foreground break-all">{value || '-'}</p>
      {copyable && value && (
        <Button variant="ghost" size="icon" className="h-6 w-6 opacity-0 group-hover/row:opacity-100 transition-opacity" onClick={() => navigator.clipboard.writeText(value)}>
          <MoreHorizontal className="w-3 h-3" />
        </Button>
      )}
    </div>
  </div>
);