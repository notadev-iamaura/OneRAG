/**
 * 프롬프트 테이블 컴포넌트
 *
 * 프롬프트 목록을 테이블 형태로 표시합니다.
 * 각 행에는 프롬프트명, 설명, 카테고리, 상태(토글), 수정일, 액션 버튼을 포함합니다.
 * 로딩 상태, 빈 목록 상태에 대한 UI도 제공합니다.
 *
 * Props:
 * - prompts: 표시할 프롬프트 목록
 * - onEdit: 수정 버튼 핸들러
 * - onView: 상세 보기 버튼 핸들러
 * - onDelete: 삭제 버튼 핸들러
 * - onDuplicate: 복제 버튼 핸들러
 * - onToggleActive: 활성/비활성 토글 핸들러
 * - loading: 로딩 상태
 */

import React, { useState, useCallback } from 'react';
import { cn } from '@/lib/utils';
import {
  Edit2,
  Trash2,
  Copy,
  Eye,
  RefreshCcw,
  Info,
} from 'lucide-react';
import {
  Card,
  CardContent,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import type { Prompt } from '../../types/prompt';
import { PROMPT_CATEGORIES } from '../../types/prompt';

export interface PromptTableProps {
  /** 표시할 프롬프트 목록 */
  prompts: Prompt[];
  /** 수정 버튼 핸들러 */
  onEdit: (prompt: Prompt) => void;
  /** 상세 보기 버튼 핸들러 */
  onView: (prompt: Prompt) => void;
  /** 삭제 버튼 핸들러 */
  onDelete: (prompt: Prompt) => void;
  /** 복제 버튼 핸들러 */
  onDuplicate: (prompt: Prompt) => void;
  /** 활성/비활성 토글 핸들러 */
  onToggleActive: (prompt: Prompt) => void;
  /** 로딩 상태 */
  loading?: boolean;
}

export const PromptTable: React.FC<PromptTableProps> = ({
  prompts,
  onEdit,
  onView,
  onDelete,
  onDuplicate,
  onToggleActive,
  loading = false,
}) => {
  // 토글 애니메이션 상태
  const [isAnimating, setIsAnimating] = useState<string | null>(null);

  /** 토글 클릭 시 애니메이션 처리 후 핸들러 호출 */
  const handleToggleWithAnimation = useCallback((prompt: Prompt) => {
    if (!prompt.is_active) {
      setIsAnimating(prompt.id);
      setTimeout(() => setIsAnimating(null), 600);
    }
    onToggleActive(prompt);
  }, [onToggleActive]);

  // 로딩 상태 표시
  if (loading) {
    return (
      <Card className="border-border/40 rounded-2xl">
        <CardContent className="p-12 text-center space-y-4">
          <RefreshCcw className="w-8 h-8 mx-auto text-primary animate-spin opacity-40" />
          <p className="text-sm font-bold text-muted-foreground animate-pulse">프롬프트 데이터를 불러오는 중...</p>
        </CardContent>
      </Card>
    );
  }

  // 빈 목록 표시
  if (prompts.length === 0) {
    return (
      <Card className="border-border/40 rounded-2xl border-dashed bg-muted/20">
        <CardContent className="p-12 text-center">
          <Info className="w-8 h-8 mx-auto mb-3 text-muted-foreground opacity-30" />
          <p className="text-sm font-bold text-muted-foreground">해당하는 프롬프트가 없습니다.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="rounded-2xl border border-border/60 overflow-hidden bg-background/50">
      <Table>
        <TableHeader className="bg-muted/30">
          <TableRow className="hover:bg-transparent border-border/60">
            <TableHead className="w-[200px] font-bold py-4">프롬프트명</TableHead>
            <TableHead className="font-bold py-4">설명</TableHead>
            <TableHead className="w-[120px] font-bold py-4">카테고리</TableHead>
            <TableHead className="w-[100px] font-bold py-4">상태</TableHead>
            <TableHead className="w-[120px] font-bold py-4 text-right">수정일</TableHead>
            <TableHead className="w-[160px] font-bold py-4 text-right">작업</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {prompts.map((prompt) => (
            <TableRow
              key={prompt.id}
              className={cn(
                'group border-border/40 transition-all duration-300',
                prompt.is_active ? 'bg-primary/[0.03] hover:bg-primary/[0.05]' : 'hover:bg-muted/30',
                isAnimating === prompt.id && 'animate-pulse scale-[0.99] bg-primary/10'
              )}
            >
              {/* 프롬프트명 */}
              <TableCell className="py-4">
                <div className="flex items-center gap-2">
                  <span className={cn(
                    'font-bold transition-all truncate',
                    prompt.is_active ? 'text-primary' : 'text-foreground/80 group-hover:text-foreground'
                  )}>
                    {prompt.name}
                  </span>
                  {prompt.is_active && (
                    <Badge className="h-4 p-0 px-1 text-[8px] font-black uppercase rounded-sm bg-primary/20 text-primary border-primary/10 animate-pulse">
                      ACTIVE
                    </Badge>
                  )}
                </div>
              </TableCell>

              {/* 설명 */}
              <TableCell className="py-4">
                <p className="text-sm text-muted-foreground line-clamp-1 group-hover:text-foreground/70 transition-colors">
                  {prompt.description || '-'}
                </p>
              </TableCell>

              {/* 카테고리 */}
              <TableCell className="py-4">
                <Badge variant="outline" className={cn(
                  'rounded-md text-[10px] font-extrabold uppercase py-0 group-hover:border-primary/30 transition-all',
                  prompt.category === 'system' ? 'bg-blue-500/5 text-blue-500 border-blue-500/20' :
                    prompt.category === 'style' ? 'bg-purple-500/5 text-purple-500 border-purple-500/20' :
                      'bg-muted/50 text-muted-foreground border-border/50'
                )}>
                  {PROMPT_CATEGORIES.find(c => c.value === prompt.category)?.label || prompt.category}
                </Badge>
              </TableCell>

              {/* 활성/비활성 토글 */}
              <TableCell className="py-4">
                <Switch
                  checked={prompt.is_active}
                  onCheckedChange={() => handleToggleWithAnimation(prompt)}
                  className="data-[state=checked]:bg-primary h-5 w-9 scale-90"
                />
              </TableCell>

              {/* 수정일 */}
              <TableCell className="py-4 text-right text-xs font-medium text-muted-foreground">
                {new Date(prompt.updated_at).toLocaleDateString('ko-KR', {
                  year: '2-digit', month: '2-digit', day: '2-digit'
                })}
              </TableCell>

              {/* 액션 버튼 */}
              <TableCell className="py-4 text-right">
                <div className="flex items-center justify-end gap-1 opacity-60 group-hover:opacity-100 transition-opacity">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg" onClick={() => onView(prompt)}>
                        <Eye className="w-4 h-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>상세 보기</TooltipContent>
                  </Tooltip>

                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg" onClick={() => onEdit(prompt)}>
                        <Edit2 className="w-4 h-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>수정</TooltipContent>
                  </Tooltip>

                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg" onClick={() => onDuplicate(prompt)}>
                        <Copy className="w-4 h-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>복제</TooltipContent>
                  </Tooltip>

                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 rounded-lg text-destructive hover:bg-destructive/10"
                        onClick={() => onDelete(prompt)}
                        disabled={prompt.category === 'system' && prompt.name === 'system'}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>삭제</TooltipContent>
                  </Tooltip>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
};
