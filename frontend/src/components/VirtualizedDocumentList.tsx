/**
 * 가상화된 문서 목록 컴포넌트
 * react-window를 사용한 대용량 데이터 렌더링 최적화
 */
import React from 'react';
import { FixedSizeList as List } from 'react-window';
import AutoSizer from 'react-virtualized-auto-sizer';
import {
  Info,
  Download,
  Trash2,
  FileText,
  Clock,
  HardDrive
} from 'lucide-react';
import { Document } from '../types';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface VirtualizedDocumentListProps {
  documents: Document[];
  onDocumentClick: (document: Document) => void;
  onDocumentDelete: (id: string) => void;
  onDocumentDownload: (id: string) => void;
}

interface RowProps {
  index: number;
  style: React.CSSProperties;
}

export const VirtualizedDocumentList: React.FC<VirtualizedDocumentListProps> = ({
  documents,
  onDocumentClick,
  onDocumentDelete,
  onDocumentDownload,
}) => {
  const Row = ({ index, style }: RowProps) => {
    const document = documents[index];

    const getStatusLabel = (status: string) => {
      switch (status) {
        case 'completed': return '완료';
        case 'processing': return '처리중';
        case 'failed': return '실패';
        default: return '알 수 없음';
      }
    };

    const formatFileSize = (bytes: number): string => {
      if (bytes === 0) return '0 Bytes';
      const k = 1024;
      const sizes = ['Bytes', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    return (
      <div style={style} className="p-2">
        <Card
          className={cn(
            "h-[calc(100%-8px)] flex flex-col group transition-all duration-200 hover:shadow-lg hover:shadow-primary/5 hover:border-primary/30",
            "rounded-[20px] border-border/60"
          )}
          onClick={() => onDocumentClick(document)}
        >
          <CardContent className="flex-1 p-4 flex flex-col">
            <div className="flex justify-between items-start gap-4 mb-3">
              <div className="flex items-center gap-2 min-w-0">
                <div className="w-8 h-8 rounded-lg bg-primary/5 flex items-center justify-center shrink-0">
                  <FileText className="w-4 h-4 text-primary" />
                </div>
                <h3 className="font-bold text-sm truncate" title={document.originalName || document.filename}>
                  {document.originalName || document.filename}
                </h3>
              </div>
              <Badge
                variant="outline"
                className={cn(
                  "text-[10px] font-bold uppercase",
                  document.status === 'completed' && "bg-emerald-500/10 text-emerald-600 border-emerald-200",
                  document.status === 'processing' && "bg-amber-500/10 text-amber-600 border-amber-200",
                  document.status === 'failed' && "bg-destructive/10 text-destructive border-destructive/20"
                )}
              >
                {getStatusLabel(document.status)}
              </Badge>
            </div>

            <div className="space-y-1.5 flex-1">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground font-medium">
                <HardDrive className="w-3 h-3" />
                <span>크기: {formatFileSize(document.size)}</span>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground font-medium">
                <Clock className="w-3 h-3" />
                <span>업로드: {new Date(document.uploadedAt).toLocaleDateString('ko-KR')}</span>
              </div>
            </div>

            <div className="flex items-center gap-1 mt-4 pt-3 border-t border-border/40 opacity-100 lg:opacity-0 group-hover:opacity-100 transition-opacity">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-lg hover:bg-primary/10 hover:text-primary"
                onClick={(e) => {
                  e.stopPropagation();
                  onDocumentClick(document);
                }}
              >
                <Info className="w-4 h-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-lg hover:bg-primary/10 hover:text-primary"
                onClick={(e) => {
                  e.stopPropagation();
                  onDocumentDownload(document.id);
                }}
              >
                <Download className="w-4 h-4" />
              </Button>
              <div className="flex-1" />
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-lg hover:bg-destructive/10 hover:text-destructive"
                onClick={(e) => {
                  e.stopPropagation();
                  onDocumentDelete(document.id);
                }}
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  };

  if (documents.length === 0) {
    return (
      <div className="h-[400px] flex flex-col items-center justify-center text-muted-foreground gap-4">
        <div className="w-16 h-16 rounded-full bg-muted/30 flex items-center justify-center">
          <FileText className="w-8 h-8 opacity-20" />
        </div>
        <p className="font-bold">문서가 없습니다</p>
      </div>
    );
  }

  return (
    <div className="h-[600px] w-full rounded-[24px] border border-border/60 overflow-hidden bg-background/50 backdrop-blur-sm">
      <AutoSizer>
        {({ height, width }: { height: number; width: number }) => (
          <List
            height={height}
            itemCount={documents.length}
            itemSize={180}
            width={width}
            className="scrollbar-hide"
          >
            {Row}
          </List>
        )}
      </AutoSizer>
    </div>
  );
};
