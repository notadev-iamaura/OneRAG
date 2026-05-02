/**
 * 프롬프트 관리 오케스트레이터 컴포넌트
 *
 * usePromptManager 훅의 상태/핸들러를 8개 하위 컴포넌트에 전달하는
 * 얇은 조합(composition) 레이어입니다.
 *
 * 하위 컴포넌트: PromptHeader, PromptFilterBar, PromptCategoryTabs,
 *   PromptEditDialog, PromptViewDialog, PromptDeleteDialog, PromptImportDialog
 */

import React, { useCallback } from 'react';
import { Info, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { TooltipProvider } from '@/components/ui/tooltip';

import { usePromptManager } from '../hooks/prompt';
import {
  PromptHeader, PromptFilterBar, PromptCategoryTabs,
  PromptEditDialog, PromptViewDialog,
  PromptDeleteDialog, PromptImportDialog,
} from './prompt';

const PromptManager: React.FC = () => {
  const pm = usePromptManager();

  /** 편집 다이얼로그 닫힐 때 모달 에러 초기화 */
  const handleEditDialogChange = useCallback((open: boolean) => {
    pm.setEditDialogOpen(open);
    if (!open) pm.setModalError(null);
  }, [pm]);

  return (
    <TooltipProvider>
      <div className="space-y-6">
        <PromptHeader
          loading={pm.loading} onRefresh={pm.loadPrompts}
          onImport={() => pm.setImportDialogOpen(true)} onExport={pm.handleExport} onCreateNew={pm.handleCreateNew}
        />

        {/* 에러 알림 */}
        {pm.error && (
          <Alert variant="destructive" className="bg-destructive/10 text-destructive border-none rounded-2xl animate-in slide-in-from-top-2 duration-300">
            <Info className="h-4 w-4" />
            <AlertTitle className="font-bold">오류 발생</AlertTitle>
            <AlertDescription className="text-sm">{pm.error}</AlertDescription>
            <Button variant="ghost" size="icon" className="absolute top-2 right-2 h-6 w-6 text-destructive hover:bg-destructive/20" onClick={() => pm.setError(null)}>
              <X className="h-4 w-4" />
            </Button>
          </Alert>
        )}

        <PromptFilterBar
          searchQuery={pm.searchQuery} categoryFilter={pm.categoryFilter} activeFilter={pm.activeFilter}
          filteredCount={pm.filteredPrompts.length}
          onSearchQueryChange={pm.setSearchQuery} onCategoryFilterChange={pm.setCategoryFilter} onActiveFilterChange={pm.setActiveFilter}
        />

        {/* 활성화 규칙 안내 */}
        <Alert className="bg-amber-500/10 border-none text-amber-700 dark:text-amber-400 rounded-2xl">
          <Info className="h-4 w-4" />
          <AlertDescription className="text-sm font-medium">
            프롬프트는 오직 1개만 활성화할 수 있습니다. 새로운 프롬프트를 활성화하면 기존 프롬프트는 자동으로 비활성화됩니다.
          </AlertDescription>
        </Alert>

        <PromptCategoryTabs
          currentTab={pm.currentTab} onTabChange={pm.setCurrentTab}
          filteredPrompts={pm.filteredPrompts} promptsByCategory={pm.promptsByCategory}
          onEdit={pm.handleEdit} onView={pm.handleView} onDelete={pm.handleDelete}
          onDuplicate={pm.handleDuplicate} onToggleActive={pm.handleToggleActive} loading={pm.loading}
        />

        {/* 다이얼로그 4종 */}
        <PromptEditDialog
          open={pm.editDialogOpen} onOpenChange={handleEditDialogChange}
          editingPrompt={pm.editingPrompt} isEditMode={pm.isEditMode}
          selectedPrompt={pm.selectedPrompt} modalError={pm.modalError}
          onSave={pm.handleSave} onEditingPromptChange={pm.setEditingPrompt}
        />
        <PromptViewDialog open={pm.viewDialogOpen} onOpenChange={pm.setViewDialogOpen} selectedPrompt={pm.selectedPrompt} onEdit={pm.handleEdit} />
        <PromptDeleteDialog open={pm.deleteDialogOpen} onOpenChange={pm.setDeleteDialogOpen} selectedPrompt={pm.selectedPrompt} onConfirm={pm.handleDeleteConfirm} />
        <PromptImportDialog
          open={pm.importDialogOpen} onOpenChange={pm.setImportDialogOpen}
          importData={pm.importData} importOverwrite={pm.importOverwrite}
          onImportDataChange={pm.setImportData} onImportOverwriteChange={pm.setImportOverwrite} onImport={pm.handleImportPrompts}
        />
      </div>
    </TooltipProvider>
  );
};

export default PromptManager;
