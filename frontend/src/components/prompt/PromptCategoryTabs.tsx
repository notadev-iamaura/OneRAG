/**
 * 프롬프트 카테고리 탭 컴포넌트
 *
 * 전체/시스템/스타일/커스텀 4개 탭과 각 탭 내의 PromptTable을 렌더링합니다.
 * 반복되는 탭 구조를 배열 매핑으로 DRY하게 처리합니다.
 */

import React from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { PromptTable } from './PromptTable';
import type { Prompt } from '../../types/prompt';

export interface PromptCategoryTabsProps {
  /** 현재 선택된 탭 */
  currentTab: string;
  /** 탭 변경 핸들러 */
  onTabChange: (tab: string) => void;
  /** 전체 필터링된 프롬프트 목록 */
  filteredPrompts: Prompt[];
  /** 카테고리별 분류된 프롬프트 */
  promptsByCategory: { system: Prompt[]; style: Prompt[]; custom: Prompt[] };
  /** 편집 핸들러 */
  onEdit: (prompt: Prompt) => void;
  /** 상세 보기 핸들러 */
  onView: (prompt: Prompt) => void;
  /** 삭제 핸들러 */
  onDelete: (prompt: Prompt) => void;
  /** 복제 핸들러 */
  onDuplicate: (prompt: Prompt) => Promise<void>;
  /** 활성/비활성 토글 핸들러 */
  onToggleActive: (prompt: Prompt) => Promise<void>;
  /** 로딩 상태 */
  loading: boolean;
}

/** 카테고리별 탭 설정 */
const CATEGORIES: { value: string; label: string; key: 'system' | 'style' | 'custom' }[] = [
  { value: 'system', label: '시스템', key: 'system' },
  { value: 'style', label: '스타일', key: 'style' },
  { value: 'custom', label: '커스텀', key: 'custom' },
];

const TAB_CLS = 'bg-transparent border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent rounded-none h-11 px-1 font-bold text-muted-foreground data-[state=active]:text-foreground transition-all';
const BADGE_CLS = 'ml-2 h-5 w-5 p-0 flex items-center justify-center rounded-full bg-muted text-muted-foreground';

export const PromptCategoryTabs: React.FC<PromptCategoryTabsProps> = ({
  currentTab, onTabChange, filteredPrompts, promptsByCategory,
  onEdit, onView, onDelete, onDuplicate, onToggleActive, loading,
}) => {
  /** PromptTable 공통 props */
  const tableProps = (prompts: Prompt[]) => ({
    prompts, onEdit, onView, onDelete, onDuplicate, onToggleActive, loading,
  });

  return (
    <Tabs value={currentTab} onValueChange={onTabChange} className="w-full space-y-6">
      <div className="flex items-center justify-between border-b border-border/60 pb-px">
        <TabsList className="bg-transparent h-auto p-0 gap-8 justify-start">
          <TabsTrigger value="all" className={TAB_CLS}>
            전체 <Badge className={BADGE_CLS}>{filteredPrompts.length}</Badge>
          </TabsTrigger>
          {CATEGORIES.map(({ value, label, key }) => (
            <TabsTrigger key={value} value={value} className={TAB_CLS}>
              {label} <Badge className={BADGE_CLS}>{promptsByCategory[key].length}</Badge>
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
      <TabsContent value="all" className="mt-0 outline-none">
        <PromptTable {...tableProps(filteredPrompts)} />
      </TabsContent>
      {CATEGORIES.map(({ value, key }) => (
        <TabsContent key={value} value={value} className="mt-0 outline-none">
          <PromptTable {...tableProps(promptsByCategory[key])} />
        </TabsContent>
      ))}
    </Tabs>
  );
};
