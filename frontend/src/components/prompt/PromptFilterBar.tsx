/**
 * 프롬프트 필터 바 컴포넌트
 *
 * 프롬프트 목록의 검색, 카테고리 필터, 활성 상태 필터를 제공합니다.
 * 카드 형태로 감싸져 있으며 필터링된 총 개수도 표시합니다.
 *
 * Props:
 * - searchQuery: 현재 검색어
 * - categoryFilter: 현재 카테고리 필터 값
 * - activeFilter: 현재 활성 상태 필터 값
 * - filteredCount: 필터링된 프롬프트 총 개수
 * - onSearchQueryChange: 검색어 변경 핸들러
 * - onCategoryFilterChange: 카테고리 필터 변경 핸들러
 * - onActiveFilterChange: 활성 상태 필터 변경 핸들러
 */

import React from 'react';
import { Search } from 'lucide-react';
import {
  Card,
  CardContent,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

import { PROMPT_CATEGORIES } from '../../types/prompt';

export interface PromptFilterBarProps {
  /** 현재 검색어 */
  searchQuery: string;
  /** 현재 카테고리 필터 값 */
  categoryFilter: string;
  /** 현재 활성 상태 필터 값 */
  activeFilter: string;
  /** 필터링된 프롬프트 총 개수 */
  filteredCount: number;
  /** 검색어 변경 핸들러 */
  onSearchQueryChange: (query: string) => void;
  /** 카테고리 필터 변경 핸들러 */
  onCategoryFilterChange: (category: string) => void;
  /** 활성 상태 필터 변경 핸들러 */
  onActiveFilterChange: (filter: string) => void;
}

export const PromptFilterBar: React.FC<PromptFilterBarProps> = ({
  searchQuery,
  categoryFilter,
  activeFilter,
  filteredCount,
  onSearchQueryChange,
  onCategoryFilterChange,
  onActiveFilterChange,
}) => {
  return (
    <Card className="border-border/60 shadow-sm rounded-2xl overflow-hidden bg-background/50 backdrop-blur-sm">
      <CardContent className="p-6">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-4 items-center">
          {/* 검색 입력 */}
          <div className="md:col-span-5 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="이름 또는 설명으로 검색..."
              value={searchQuery}
              onChange={(e) => onSearchQueryChange(e.target.value)}
              className="pl-10 h-10 rounded-xl border-border/40 focus-visible:ring-primary/20 transition-all"
            />
          </div>

          {/* 카테고리 필터 */}
          <div className="md:col-span-3">
            <Select value={categoryFilter} onValueChange={onCategoryFilterChange}>
              <SelectTrigger className="h-10 rounded-xl border-border/40">
                <SelectValue placeholder="카테고리 선택" />
              </SelectTrigger>
              <SelectContent className="rounded-xl">
                <SelectItem value="all">전체 카테고리</SelectItem>
                {PROMPT_CATEGORIES.map((category) => (
                  <SelectItem key={category.value} value={category.value}>
                    {category.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* 활성 상태 필터 */}
          <div className="md:col-span-3">
            <Select value={activeFilter} onValueChange={onActiveFilterChange}>
              <SelectTrigger className="h-10 rounded-xl border-border/40">
                <SelectValue placeholder="상태 선택" />
              </SelectTrigger>
              <SelectContent className="rounded-xl">
                <SelectItem value="all">전체 상태</SelectItem>
                <SelectItem value="active">활성 프롬프트</SelectItem>
                <SelectItem value="inactive">비활성 프롬프트</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* 총 개수 표시 */}
          <div className="md:col-span-1 text-right">
            <span className="text-xs font-bold text-muted-foreground bg-muted/50 px-2 py-1 rounded-lg">
              총 {filteredCount}개
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
