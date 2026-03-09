/**
 * 프롬프트 관리 헤더 컴포넌트
 *
 * 타이틀(BrainCircuit 아이콘 + "프롬프트 관리")과
 * 액션 버튼(새로고침, 가져오기, 내보내기, 새 프롬프트)을 렌더링합니다.
 */

import React from 'react';
import { cn } from '@/lib/utils';
import { Plus, Download, Upload, RefreshCcw, BrainCircuit } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

export interface PromptHeaderProps {
  /** 로딩 중 여부 (새로고침 버튼 비활성화 및 회전 애니메이션) */
  loading: boolean;
  /** 새로고침 클릭 핸들러 */
  onRefresh: () => void;
  /** 가져오기 클릭 핸들러 */
  onImport: () => void;
  /** 내보내기 클릭 핸들러 */
  onExport: () => void;
  /** 새 프롬프트 클릭 핸들러 */
  onCreateNew: () => void;
}

export const PromptHeader: React.FC<PromptHeaderProps> = ({
  loading, onRefresh, onImport, onExport, onCreateNew,
}) => (
  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
    <div className="flex items-center gap-3">
      <div className="p-2.5 bg-primary/10 rounded-2xl text-primary">
        <BrainCircuit className="w-6 h-6" />
      </div>
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-foreground">프롬프트 관리</h2>
        <p className="text-sm text-muted-foreground">시스템 프롬프트를 동적으로 관리하고 페르소나를 설정합니다.</p>
      </div>
    </div>
    <div className="flex flex-wrap gap-2">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="outline" size="icon" onClick={onRefresh} disabled={loading} className="rounded-xl">
            <RefreshCcw className={cn('w-4 h-4', loading && 'animate-spin')} />
          </Button>
        </TooltipTrigger>
        <TooltipContent>새로고침</TooltipContent>
      </Tooltip>
      <Button variant="outline" onClick={onImport} className="gap-2 rounded-xl border-border/60">
        <Upload className="w-4 h-4" />가져오기
      </Button>
      <Button variant="outline" onClick={onExport} className="gap-2 rounded-xl border-border/60">
        <Download className="w-4 h-4" />내보내기
      </Button>
      <Button onClick={onCreateNew} className="gap-2 rounded-xl shadow-lg shadow-primary/20">
        <Plus className="w-4 h-4" />새 프롬프트
      </Button>
    </div>
  </div>
);
