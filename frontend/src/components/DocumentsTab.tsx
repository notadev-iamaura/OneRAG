/**
 * 문서 관리 탭 오케스트레이터
 *
 * 3개 훅(목록/선택/삭제) + 7개 하위 컴포넌트를 조합합니다.
 * 비즈니스 로직은 훅에, UI는 하위 컴포넌트에 위임하며
 * 이 파일은 조합과 배치만 담당합니다.
 */
import React from 'react';
import { Search, RotateCw, AlertCircle, ChevronLeft, ChevronRight } from 'lucide-react';
import { Document, ToastMessage } from '../types';
import { documentAPI } from '../services/api';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useDocumentList, useDocumentSelection, useDocumentDelete } from '../hooks/document';
import {
  DocumentToolbar, DocumentListView, DocumentGridView, DocumentDetailDialog,
  DocumentDeleteDialog, DocumentBulkDeleteDialog, DocumentDeleteAllDialog,
} from './document';

interface DocumentsTabProps {
  showToast: (message: Omit<ToastMessage, 'id'>) => void;
}

/** 에러 상태 표시 */
const ErrorState: React.FC<{ onRetry: () => void }> = ({ onRetry }) => (
  <Card className="border-destructive/30 bg-destructive/5 py-16 flex flex-col items-center justify-center text-center gap-4 px-6">
    <div className="w-16 h-16 rounded-full bg-destructive/10 flex items-center justify-center mb-2">
      <AlertCircle className="w-8 h-8 text-destructive" />
    </div>
    <p className="text-lg font-black text-foreground">문서 목록을 불러올 수 없습니다</p>
    <p className="text-sm text-muted-foreground max-w-xs">백엔드 연결을 확인하거나 아래 버튼을 눌러 다시 시도해주세요.</p>
    <Button onClick={onRetry} variant="default" className="gap-2 font-bold px-6 rounded-xl shadow-lg shadow-primary/20">
      <RotateCw className="w-4 h-4" />다시 시도
    </Button>
  </Card>
);

/** 로딩 상태 표시 */
const LoadingState: React.FC = () => (
  <div className="flex flex-col items-center justify-center py-20 gap-4">
    <RotateCw className="w-10 h-10 text-primary animate-spin opacity-20" />
    <p className="text-sm font-bold text-muted-foreground animate-pulse">문서 목록을 불러오는 중...</p>
  </div>
);

/** 빈 목록 상태 표시 */
const EmptyState: React.FC = () => (
  <Card className="border-dashed border-2 py-20 flex flex-col items-center justify-center text-center">
    <div className="w-20 h-20 rounded-full bg-muted/30 flex items-center justify-center mb-4">
      <Search className="w-10 h-10 text-muted-foreground/40" />
    </div>
    <p className="text-lg font-black text-foreground">문서가 없습니다</p>
    <p className="text-sm text-muted-foreground">검색어를 바꾸거나 새 문서를 업로드해 보세요</p>
  </Card>
);

/** 페이지네이션 컨트롤 */
const Pagination: React.FC<{ page: number; total: number; onChange: (p: number) => void }> = ({ page, total, onChange }) => {
  const btn = "rounded-xl h-9 w-9 border-border/60";
  return (
    <div className="flex items-center justify-center gap-2 py-8">
      <Button variant="outline" size="icon" disabled={page === 1} onClick={() => onChange(1)} className={btn}>
        <ChevronLeft className="w-4 h-4 mr-[-1px]" /><ChevronLeft className="w-4 h-4 ml-[-1px]" />
      </Button>
      <Button variant="outline" size="icon" disabled={page === 1} onClick={() => onChange(page - 1)} className={btn}>
        <ChevronLeft className="w-4 h-4" />
      </Button>
      <div className="flex items-center gap-1 mx-2">
        <span className="text-sm font-black">Page {page}</span>
        <span className="text-sm text-muted-foreground font-bold">of {total}</span>
      </div>
      <Button variant="outline" size="icon" disabled={page === total} onClick={() => onChange(page + 1)} className={btn}>
        <ChevronRight className="w-4 h-4" />
      </Button>
      <Button variant="outline" size="icon" disabled={page === total} onClick={() => onChange(total)} className={btn}>
        <ChevronRight className="w-4 h-4 mr-[-1px]" /><ChevronRight className="w-4 h-4 ml-[-1px]" />
      </Button>
    </div>
  );
};

/** 문서 다운로드 (브라우저 DOM API 사용) */
const downloadDocument = async (doc: Document, showToast: DocumentsTabProps['showToast']) => {
  try {
    const resp = await documentAPI.downloadDocument(doc.id);
    const url = window.URL.createObjectURL(new Blob([resp.data]));
    const a = globalThis.document.createElement('a');
    a.href = url; a.download = doc.originalName || doc.filename; a.click();
    window.URL.revokeObjectURL(url);
  } catch { showToast({ type: 'error', message: '다운로드 실패' }); }
};

export const DocumentsTab: React.FC<DocumentsTabProps> = ({ showToast }) => {
  const list = useDocumentList({ showToast });
  const selection = useDocumentSelection({ showToast });
  const deletion = useDocumentDelete({ showToast, onDeleted: list.fetchDocuments, clearSelection: selection.clearSelection });
  const download = (doc: Document) => downloadDocument(doc, showToast);

  // 콘텐츠 영역: 에러 → 로딩 → 빈 목록 → 문서 뷰
  const renderContent = () => {
    if (list.fetchError) return <ErrorState onRetry={list.fetchDocuments} />;
    if (list.loading) return <LoadingState />;
    if (list.documents.length === 0) return <EmptyState />;
    const shared = { documents: list.documents, selectedDocuments: selection.selectedDocuments,
      onToggleSelect: selection.toggleSelect, onViewDetails: selection.viewDetails, onDownload: download, onDeleteSingle: deletion.handleDeleteSingle };
    return (<>
      {list.viewMode === 'list'
        ? <DocumentListView {...shared} onToggleSelectAll={() => selection.toggleSelectAll(list.documents)} />
        : <DocumentGridView {...shared} />}
      <Pagination page={list.page} total={list.totalPages} onChange={list.setPage} />
    </>);
  };

  return (
    <div className="space-y-6">
      <DocumentToolbar searchQuery={list.searchQuery} sortField={list.sortField} sortDirection={list.sortDirection}
        viewMode={list.viewMode} loading={list.loading} selectedCount={selection.selectedDocuments.size}
        onSearchChange={list.handleSearch} onSortFieldChange={list.handleSort} onSortDirectionToggle={list.handleSortDirection}
        onViewModeChange={list.setViewMode} onRefresh={list.fetchDocuments} onBulkDelete={deletion.handleDeleteBulk} onDeleteAll={deletion.handleDeleteAll} />
      {renderContent()}
      <DocumentDetailDialog open={selection.detailsOpen} document={selection.selectedDocument} onClose={selection.closeDetails} />
      <DocumentDeleteDialog open={deletion.deleteConfirmOpen} loading={deletion.deleteLoading} onConfirm={deletion.confirmDeleteSingle} onCancel={deletion.handleDeleteCancel} />
      <DocumentBulkDeleteDialog open={deletion.bulkDeleteConfirmOpen} loading={deletion.bulkDeleteLoading}
        selectedCount={selection.selectedDocuments.size} onConfirm={() => deletion.confirmDeleteBulk(selection.selectedDocuments)} onCancel={deletion.handleBulkDeleteCancel} />
      <DocumentDeleteAllDialog open={deletion.deleteAllConfirmOpen} loading={deletion.deleteAllLoading} step={deletion.deleteAllStep}
        typingValue={deletion.deleteAllTyping} onConfirm={deletion.confirmDeleteAll} onCancel={deletion.handleDeleteAllCancel} onTypingChange={deletion.setDeleteAllTyping} />
    </div>
  );
};
