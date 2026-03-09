/**
 * 문서 툴바 컴포넌트
 *
 * 문서 목록 상단의 검색, 정렬, 뷰 모드 전환, 일괄 삭제/전체 삭제 버튼을 제공합니다.
 * DocumentsTab의 인라인 JSX에서 분리된 프레젠테이션 컴포넌트입니다.
 */
import React from 'react';
import {
  Search,
  Trash,
  RotateCw,
  AlertTriangle,
  ArrowUp,
  ArrowDown,
  List as ListIcon,
  LayoutGrid,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import type { SortField, SortDirection } from '../../utils/documentUtils';

/** DocumentToolbar 컴포넌트의 Props */
export interface DocumentToolbarProps {
  /** 현재 검색어 */
  searchQuery: string;
  /** 현재 정렬 필드 */
  sortField: SortField;
  /** 현재 정렬 방향 */
  sortDirection: SortDirection;
  /** 현재 뷰 모드 */
  viewMode: 'list' | 'grid';
  /** 로딩 상태 (새로고침 아이콘 애니메이션용) */
  loading: boolean;
  /** 선택된 문서 수 */
  selectedCount: number;
  /** 검색어 변경 핸들러 */
  onSearchChange: (query: string) => void;
  /** 정렬 필드 변경 핸들러 */
  onSortFieldChange: (field: SortField) => void;
  /** 정렬 방향 토글 핸들러 */
  onSortDirectionToggle: () => void;
  /** 뷰 모드 변경 핸들러 */
  onViewModeChange: (mode: 'list' | 'grid') => void;
  /** 새로고침 핸들러 */
  onRefresh: () => void;
  /** 일괄 삭제 핸들러 */
  onBulkDelete: () => void;
  /** 전체 삭제 핸들러 */
  onDeleteAll: () => void;
}

/**
 * 문서 관리 툴바 컴포넌트
 *
 * 검색, 정렬, 뷰 모드 전환, 삭제 액션을 하나의 카드 형태 UI로 구성합니다.
 */
export const DocumentToolbar: React.FC<DocumentToolbarProps> = ({
  searchQuery,
  sortField,
  sortDirection,
  viewMode,
  loading,
  selectedCount,
  onSearchChange,
  onSortFieldChange,
  onSortDirectionToggle,
  onViewModeChange,
  onRefresh,
  onBulkDelete,
  onDeleteAll,
}) => {
  return (
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
                onChange={(e) => onSearchChange(e.target.value)}
                className="pl-10 rounded-xl border-border/60 focus-visible:ring-primary/20"
              />
            </div>
            <div className="w-40 shrink-0">
              <Select value={sortField} onValueChange={(v: string) => onSortFieldChange(v as SortField)}>
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
              onClick={onSortDirectionToggle}
              className="rounded-xl border border-border/60 shrink-0 hover:bg-muted"
              data-testid="sort-direction-button"
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
                onClick={() => onViewModeChange('list')}
                className={cn("h-8 w-8 rounded-lg", viewMode === 'list' && "shadow-sm bg-background")}
                data-testid="view-mode-list"
              >
                <ListIcon className="w-4 h-4" />
              </Button>
              <Button
                variant={viewMode === 'grid' ? 'secondary' : 'ghost'}
                size="icon"
                onClick={() => onViewModeChange('grid')}
                className={cn("h-8 w-8 rounded-lg", viewMode === 'grid' && "shadow-sm bg-background")}
                data-testid="view-mode-grid"
              >
                <LayoutGrid className="w-4 h-4" />
              </Button>
            </div>

            <Separator orientation="vertical" className="h-8 hidden lg:block" />

            <div className="flex items-center gap-2">
              {selectedCount > 0 && (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={onBulkDelete}
                  className="rounded-xl h-9 font-bold px-4 animate-in zoom-in duration-200"
                >
                  <Trash className="w-4 h-4 mr-2" />
                  선택 삭제 ({selectedCount})
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={onDeleteAll}
                className="rounded-xl h-9 font-bold border-destructive/30 text-destructive hover:bg-destructive/10"
              >
                <AlertTriangle className="w-4 h-4 mr-2" />
                전체 삭제
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={onRefresh}
                className="rounded-xl h-9 w-9 text-primary hover:bg-primary/10"
                data-testid="refresh-button"
              >
                <RotateCw className={cn("w-4 h-4", loading && "animate-spin")} />
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
