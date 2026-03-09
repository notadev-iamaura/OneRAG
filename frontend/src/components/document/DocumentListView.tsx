/**
 * 문서 리스트 뷰 컴포넌트
 *
 * 테이블 형태로 문서 목록을 표시합니다.
 * 체크박스 선택, 상태 아이콘, 파일 정보, 액션 버튼(상세/다운로드/삭제)을 제공합니다.
 */
import React from 'react';
import {
  Trash2,
  Info,
  Download,
  RotateCw,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
} from 'lucide-react';
import { Card } from '@/components/ui/card';
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
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import { formatFileSize } from '../../utils/documentUtils';
import type { Document } from '../../types';

/** DocumentListView 컴포넌트의 Props */
export interface DocumentListViewProps {
  /** 문서 배열 */
  documents: Document[];
  /** 선택된 문서 ID 집합 */
  selectedDocuments: Set<string>;
  /** 개별 문서 선택/해제 토글 */
  onToggleSelect: (id: string) => void;
  /** 전체 선택/해제 토글 */
  onToggleSelectAll: () => void;
  /** 문서 상세 보기 */
  onViewDetails: (doc: Document) => void;
  /** 문서 다운로드 */
  onDownload: (doc: Document) => void;
  /** 단일 문서 삭제 */
  onDeleteSingle: (id: string) => void;
}

/** 문서 ID가 유효한지 확인합니다 (UI 표시용) */
const isValidDocumentId = (id: string): boolean =>
  Boolean(id && !id.startsWith('temp-') && id.trim() !== '');

/** 문서 상태에 따른 아이콘을 반환합니다 */
const getStatusIcon = (status: Document['status']) => {
  switch (status) {
    case 'completed': return <CheckCircle2 className="w-4 h-4 text-emerald-500" />;
    case 'processing': return <RotateCw className="w-4 h-4 text-amber-500 animate-spin" />;
    case 'failed': return <AlertCircle className="w-4 h-4 text-destructive" />;
    default: return <HelpCircle className="w-4 h-4 text-muted-foreground" />;
  }
};

/**
 * 테이블 형태의 문서 리스트 뷰 컴포넌트
 *
 * 각 문서를 행(row)으로 표시하며, 체크박스/파일명/크기/날짜/상태/액션 열을 포함합니다.
 */
export const DocumentListView: React.FC<DocumentListViewProps> = ({
  documents,
  selectedDocuments,
  onToggleSelect,
  onToggleSelectAll,
  onViewDetails,
  onDownload,
  onDeleteSingle,
}) => {
  return (
    <Card className="border-border/60 overflow-hidden rounded-[24px]">
      <Table>
        <TableHeader className="bg-muted/30 hover:bg-muted/30">
          <TableRow className="border-b-border/40">
            <TableHead className="w-[50px]">
              <Checkbox
                checked={selectedDocuments.size === documents.filter(d => isValidDocumentId(d.id)).length && documents.length > 0}
                onCheckedChange={onToggleSelectAll}
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
                  onCheckedChange={() => onToggleSelect(doc.id)}
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
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 rounded-lg hover:bg-primary/10 hover:text-primary"
                    onClick={() => onViewDetails(doc)}
                    data-testid={`detail-button-${doc.id}`}
                  >
                    <Info className="w-4 h-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 rounded-lg hover:bg-primary/10 hover:text-primary"
                    onClick={() => onDownload(doc)}
                    data-testid={`download-button-${doc.id}`}
                  >
                    <Download className="w-4 h-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 rounded-lg hover:bg-destructive/10 hover:text-destructive"
                    onClick={() => onDeleteSingle(doc.id)}
                    disabled={!isValidDocumentId(doc.id)}
                    data-testid={`delete-button-${doc.id}`}
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
  );
};
