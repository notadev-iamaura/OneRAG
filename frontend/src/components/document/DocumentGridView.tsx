/**
 * 문서 그리드 뷰 컴포넌트
 *
 * 카드 형태로 문서를 그리드 레이아웃에 표시합니다.
 * 체크박스, 파일 정보, 상태 뱃지, 액션 버튼(상세/받기/삭제)을 제공합니다.
 */
import React from 'react';
import {
  MoreHorizontal,
  CheckCircle2,
  FileText,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import { formatFileSize } from '../../utils/documentUtils';
import type { Document } from '../../types';

/** DocumentGridView 컴포넌트의 Props */
export interface DocumentGridViewProps {
  /** 문서 배열 */
  documents: Document[];
  /** 선택된 문서 ID 집합 */
  selectedDocuments: Set<string>;
  /** 개별 문서 선택/해제 토글 */
  onToggleSelect: (id: string) => void;
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

/**
 * 그리드 형태의 문서 카드 뷰 컴포넌트
 *
 * 각 문서를 카드로 표시하며, 파일 아이콘/이름/크기/청크 수/상태/날짜를 포함합니다.
 */
export const DocumentGridView: React.FC<DocumentGridViewProps> = ({
  documents,
  selectedDocuments,
  onToggleSelect,
  onViewDetails,
  onDownload,
  onDeleteSingle,
}) => {
  return (
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
              onCheckedChange={() => onToggleSelect(doc.id)}
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
            <Button variant="ghost" size="sm" className="flex-1 h-8 text-[11px] font-bold rounded-xl" onClick={() => onViewDetails(doc)}>상세</Button>
            <Button variant="ghost" size="sm" className="flex-1 h-8 text-[11px] font-bold rounded-xl" onClick={() => onDownload(doc)}>받기</Button>
            <Button
              variant="ghost"
              size="sm"
              className="flex-1 h-8 text-[11px] font-bold rounded-xl text-destructive hover:bg-destructive/10"
              onClick={() => onDeleteSingle(doc.id)}
              disabled={!isValidDocumentId(doc.id)}
            >
              삭제
            </Button>
          </CardFooter>
        </Card>
      ))}
    </div>
  );
};
