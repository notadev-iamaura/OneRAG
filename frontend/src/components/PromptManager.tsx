import React, { useState, useEffect, useCallback } from 'react';
import { logger } from '../utils/logger';
import { cn } from '@/lib/utils';
import {
  Plus,
  Edit2,
  Trash2,
  Copy,
  Eye,
  Download,
  Upload,
  RefreshCcw,
  Save,
  X,
  BrainCircuit,
  Search,
  Info,
} from 'lucide-react';
import {
  Card,
  CardContent,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useToast } from '@/hooks/use-toast';

import promptService, {
  Prompt,
  CreatePromptRequest,
  UpdatePromptRequest,
  PROMPT_CATEGORIES
} from '../services/promptService';

// 안전한 에러 메시지 추출 유틸리티
function getErrorMessage(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: string } } }).response;
    const detail = response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
  }
  return fallback;
}

const PromptManager: React.FC = () => {
  const { toast } = useToast();
  // State 관리
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);
  const [currentTab, setCurrentTab] = useState('all');

  // Dialog 상태
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);

  // 선택된 프롬프트
  const [selectedPrompt, setSelectedPrompt] = useState<Prompt | null>(null);
  const [editingPrompt, setEditingPrompt] = useState<CreatePromptRequest | UpdatePromptRequest | null>(null);
  const [isEditMode, setIsEditMode] = useState(false);

  // 필터 및 검색
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [activeFilter, setActiveFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');

  // 가져오기/내보내기
  const [importData, setImportData] = useState('');
  const [importOverwrite, setImportOverwrite] = useState(false);

  // 프롬프트 목록 로드
  const loadPrompts = useCallback(async () => {
    setLoading(true);
    try {
      const params: { page_size: number; category?: string; is_active?: boolean } = { page_size: 100 };
      if (categoryFilter !== 'all') params.category = categoryFilter;
      if (activeFilter === 'active') params.is_active = true;
      else if (activeFilter === 'inactive') params.is_active = false;

      const response = await promptService.getPrompts(params);

      // 활성 프롬프트 검증 및 자동 조정
      const loadedPrompts = response.prompts;
      const activePrompts = loadedPrompts.filter(p => p.is_active);

      if (activePrompts.length === 0) {
        // 활성 프롬프트가 없는 경우: 시스템 프롬프트 자동 활성화
        const systemPrompt = loadedPrompts.find(p => p.category === 'system' && p.name === 'system');
        if (systemPrompt) {
          await promptService.togglePrompt(systemPrompt.id, true);
          // 프롬프트 목록 다시 로드
          const reloadParams: { page_size: number; category?: string } = { page_size: 100 };
          if (categoryFilter !== 'all') reloadParams.category = categoryFilter;
          const updatedResponse = await promptService.getPrompts(reloadParams);
          setPrompts(updatedResponse.prompts);
        } else {
          setPrompts(loadedPrompts);
        }
      } else if (activePrompts.length > 1) {
        // 활성 프롬프트가 여러 개인 경우: 첫 번째 것만 남기고 나머지 비활성화
        logger.warn(`여러 프롬프트가 활성화되어 있습니다. 첫 번째 프롬프트만 활성 상태로 유지합니다.`);

        // 첫 번째를 제외한 나머지 비활성화
        for (const ap of activePrompts.slice(1)) {
          await promptService.togglePrompt(ap.id, false);
        }

        // 프롬프트 목록 다시 로드
        const reloadParams2: { page_size: number; category?: string } = { page_size: 100 };
        if (categoryFilter !== 'all') reloadParams2.category = categoryFilter;
        const updatedResponse = await promptService.getPrompts(reloadParams2);
        setPrompts(updatedResponse.prompts);
      } else {
        // 정상적으로 1개만 활성화된 경우
        setPrompts(loadedPrompts);
      }

      setError(null);
    } catch (err) {
      logger.error('프롬프트 로딩 실패:', err);
      setError('프롬프트를 불러오는데 실패했습니다.');
    } finally {
      setLoading(false);
    }
  }, [categoryFilter, activeFilter]);

  // 초기 로드
  useEffect(() => {
    loadPrompts();
  }, [loadPrompts]);

  // 프롬프트 저장
  const handleSavePrompt = async () => {
    if (!editingPrompt) return;

    try {
      // 클라이언트 검증
      const validationErrors = promptService.validatePrompt(editingPrompt);
      if (validationErrors.length > 0) {
        setModalError(validationErrors.join(', '));
        return;
      }

      if (isEditMode && selectedPrompt) {
        // 수정
        await promptService.updatePrompt(selectedPrompt.id, editingPrompt as UpdatePromptRequest);
        toast({
          title: "프롬프트 수정 완료",
          description: `'${editingPrompt.name}' 프롬프트가 성공적으로 수정되었습니다.`,
        });
      } else {
        // 생성
        await promptService.createPrompt(editingPrompt as CreatePromptRequest);
        toast({
          title: "새 프롬프트 생성",
          description: `'${editingPrompt.name}' 프롬프트가 성공적으로 생성되었습니다.`,
        });
      }

      setEditDialogOpen(false);
      setEditingPrompt(null);
      setModalError(null);
      await loadPrompts();
    } catch (err: unknown) {
      logger.error('프롬프트 저장 실패:', err);
      setModalError(getErrorMessage(err, '프롬프트 저장에 실패했습니다.'));
    }
  };

  // 프롬프트 삭제
  const handleDeletePrompt = async () => {
    if (!selectedPrompt) return;

    try {
      const name = selectedPrompt.name;
      await promptService.deletePrompt(selectedPrompt.id);
      setDeleteDialogOpen(false);
      setSelectedPrompt(null);
      toast({
        variant: "destructive",
        title: "프롬프트 삭제 완료",
        description: `'${name}' 프롬프트가 영구적으로 삭제되었습니다.`,
      });
      await loadPrompts();
    } catch (err: unknown) {
      logger.error('프롬프트 삭제 실패:', err);
      setError(getErrorMessage(err, '프롬프트 삭제에 실패했습니다.'));
    }
  };

  // 프롬프트 복제
  const handleDuplicatePrompt = async (prompt: Prompt) => {
    try {
      const newName = `${prompt.name}_copy_${Date.now()}`;
      await promptService.duplicatePrompt(prompt.id, newName);
      toast({
        title: "프롬프트 복제 성공",
        description: `'${prompt.name}'의 복제본이 생성되었습니다.`,
      });
      await loadPrompts();
    } catch (err: unknown) {
      logger.error('프롬프트 복제 실패:', err);
      setError(getErrorMessage(err, '프롬프트 복제에 실패했습니다.'));
    }
  };

  // 프롬프트 활성화/비활성화 (단일 선택 방식)
  const handleToggleActive = async (prompt: Prompt) => {
    try {
      if (!prompt.is_active) {
        // 활성화하려는 경우: 다른 모든 프롬프트를 비활성화하고 현재 프롬프트만 활성화
        const activePrompts = prompts.filter(p => p.is_active);

        // 다른 활성 프롬프트들을 모두 비활성화
        for (const activePrompt of activePrompts) {
          await promptService.togglePrompt(activePrompt.id, false);
        }

        // 현재 프롬프트 활성화
        await promptService.togglePrompt(prompt.id, true);
        toast({
          title: "프롬프트 활성화",
          description: `'${prompt.name}' 프롬프트가 이제 시스템에 적용됩니다.`,
        });
      } else {
        // 비활성화하려는 경우
        const activeCount = prompts.filter(p => p.is_active).length;

        if (activeCount === 1) {
          // 마지막 활성 프롬프트를 비활성화하려는 경우
          // 시스템 프롬프트를 자동으로 활성화
          const systemPrompt = prompts.find(p => p.category === 'system' && p.name === 'system');

          if (systemPrompt && systemPrompt.id !== prompt.id) {
            // 현재 프롬프트를 비활성화하고 시스템 프롬프트를 활성화
            await promptService.togglePrompt(prompt.id, false);
            await promptService.togglePrompt(systemPrompt.id, true);
            toast({
              title: "프롬프트 기본값 전환",
              description: `'${prompt.name}'이 비활성화되어 기본 시스템 프롬프트로 전환되었습니다.`,
            });
          } else {
            // 시스템 프롬프트가 없거나, 현재 프롬프트가 시스템 프롬프트인 경우
            // 비활성화를 막고 경고 메시지 표시
            setError('최소 하나의 프롬프트는 활성화되어 있어야 합니다.');
            return;
          }
        } else {
          // 다른 활성 프롬프트가 있는 경우 단순히 비활성화
          await promptService.togglePrompt(prompt.id, false);
          toast({
            title: "프롬프트 비활성화",
            description: `'${prompt.name}' 프롬프트가 비활성화되었습니다.`,
          });
        }
      }

      await loadPrompts();
    } catch (err: unknown) {
      logger.error('프롬프트 상태 변경 실패:', err);
      setError(getErrorMessage(err, '프롬프트 상태 변경에 실패했습니다.'));
    }
  };

  // 프롬프트 내보내기
  const handleExportPrompts = async () => {
    if (prompts.length === 0) {
      toast({
        variant: "destructive",
        title: "내보내기 실패",
        description: "내보낼 프롬프트가 없습니다.",
      });
      return;
    }

    try {
      const exportData = await promptService.exportPrompts();
      const blob = new Blob([JSON.stringify(exportData, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const fileName = `prompts_export_${new Date().toISOString().split('T')[0]}.json`;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast({
        title: "내보내기 완료",
        description: `'${fileName}' 파일이 다운로드되었습니다.`,
      });
    } catch (err: unknown) {
      logger.error('프롬프트 내보내기 실패:', err);
      setError('프롬프트 내보내기에 실패했습니다.');
    }
  };

  // 프롬프트 가져오기
  const handleImportPrompts = async () => {
    try {
      const data = JSON.parse(importData);
      const result = await promptService.importPrompts(data, importOverwrite);
      setImportDialogOpen(false);
      setImportData('');
      setImportOverwrite(false);

      toast({
        title: "데이터 가져오기 성공",
        description: `${result.imported + result.updated}개의 프롬프트를 처리했습니다. (신규: ${result.imported}, 갱신: ${result.updated})`,
      });

      await loadPrompts();
    } catch (err: unknown) {
      logger.error('프롬프트 가져오기 실패:', err);
      setError(getErrorMessage(err, '프롬프트 가져오기에 실패했습니다.'));
    }
  };

  // 새 프롬프트 생성 다이얼로그 열기
  const handleCreateNew = () => {
    setEditingPrompt({
      name: '',
      content: '',
      description: '',
      category: 'custom',
      is_active: true,
    });
    setModalError(null);
    setIsEditMode(false);
    setEditDialogOpen(true);
  };

  // 프롬프트 편집 다이얼로그 열기
  const handleEditPrompt = (prompt: Prompt) => {
    setSelectedPrompt(prompt);
    const nextEditing: CreatePromptRequest | UpdatePromptRequest = {
      name: prompt.name,
      content: prompt.content,
      description: prompt.description,
      category: prompt.category,
      is_active: prompt.is_active,
      ...(prompt.metadata ? { metadata: prompt.metadata } : {}),
    };
    setEditingPrompt(nextEditing);
    setModalError(null);
    setIsEditMode(true);
    setEditDialogOpen(true);
  };

  // 프롬프트 보기 다이얼로그 열기
  const handleViewPrompt = (prompt: Prompt) => {
    setSelectedPrompt(prompt);
    setViewDialogOpen(true);
  };

  // 프롬프트 삭제 다이얼로그 열기
  const handleDeleteClick = (prompt: Prompt) => {
    setSelectedPrompt(prompt);
    setDeleteDialogOpen(true);
  };

  // 필터링된 프롬프트 목록 (활성 프롬프트를 상단에 정렬)
  const filteredPrompts = prompts
    .filter((prompt) => {
      const matchesSearch = prompt.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        prompt.description.toLowerCase().includes(searchQuery.toLowerCase());
      return matchesSearch;
    })
    .sort((a, b) => {
      // 활성화된 프롬프트를 맨 위로
      if (a.is_active !== b.is_active) {
        return a.is_active ? -1 : 1;
      }
      // 같은 활성화 상태면 이름순 정렬
      return a.name.localeCompare(b.name);
    });

  // 카테고리별 프롬프트 분류
  const promptsByCategory = {
    system: filteredPrompts.filter(p => p.category === 'system'),
    style: filteredPrompts.filter(p => p.category === 'style'),
    custom: filteredPrompts.filter(p => p.category === 'custom'),
  };

  return (
    <TooltipProvider>
      <div className="space-y-6">
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
                <Button variant="outline" size="icon" onClick={loadPrompts} disabled={loading} className="rounded-xl">
                  <RefreshCcw className={cn("w-4 h-4", loading && "animate-spin")} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>새로고침</TooltipContent>
            </Tooltip>

            <Button variant="outline" onClick={() => setImportDialogOpen(true)} className="gap-2 rounded-xl border-border/60">
              <Upload className="w-4 h-4" />
              가져오기
            </Button>

            <Button variant="outline" onClick={handleExportPrompts} className="gap-2 rounded-xl border-border/60">
              <Download className="w-4 h-4" />
              내보내기
            </Button>

            <Button onClick={handleCreateNew} className="gap-2 rounded-xl shadow-lg shadow-primary/20">
              <Plus className="w-4 h-4" />
              새 프롬프트
            </Button>
          </div>
        </div>

        {error && (
          <Alert variant="destructive" className="bg-destructive/10 text-destructive border-none rounded-2xl animate-in slide-in-from-top-2 duration-300">
            <Info className="h-4 w-4" />
            <AlertTitle className="font-bold">오류 발생</AlertTitle>
            <AlertDescription className="text-sm">{error}</AlertDescription>
            <Button variant="ghost" size="icon" className="absolute top-2 right-2 h-6 w-6 text-destructive hover:bg-destructive/20" onClick={() => setError(null)}>
              <X className="h-4 w-4" />
            </Button>
          </Alert>
        )}

        <Card className="border-border/60 shadow-sm rounded-2xl overflow-hidden bg-background/50 backdrop-blur-sm">
          <CardContent className="p-6">
            <div className="grid grid-cols-1 md:grid-cols-12 gap-4 items-center">
              <div className="md:col-span-5 relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="이름 또는 설명으로 검색..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-10 h-10 rounded-xl border-border/40 focus-visible:ring-primary/20 transition-all"
                />
              </div>
              <div className="md:col-span-3">
                <Select value={categoryFilter} onValueChange={setCategoryFilter}>
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
              <div className="md:col-span-3">
                <Select value={activeFilter} onValueChange={setActiveFilter}>
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
              <div className="md:col-span-1 text-right">
                <span className="text-xs font-bold text-muted-foreground bg-muted/50 px-2 py-1 rounded-lg">
                  총 {filteredPrompts.length}개
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Alert className="bg-amber-500/10 border-none text-amber-700 dark:text-amber-400 rounded-2xl">
          <Info className="h-4 w-4" />
          <AlertDescription className="text-sm font-medium">
            프롬프트는 오직 1개만 활성화할 수 있습니다. 새로운 프롬프트를 활성화하면 기존 제품은 자동으로 비활성화됩니다.
          </AlertDescription>
        </Alert>

        <Tabs value={currentTab} onValueChange={setCurrentTab} className="w-full space-y-6">
          <div className="flex items-center justify-between border-b border-border/60 pb-px">
            <TabsList className="bg-transparent h-auto p-0 gap-8 justify-start">
              <TabsTrigger
                value="all"
                className="bg-transparent border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent rounded-none h-11 px-1 font-bold text-muted-foreground data-[state=active]:text-foreground transition-all"
              >
                전체 <Badge className="ml-2 h-5 w-5 p-0 flex items-center justify-center rounded-full bg-muted text-muted-foreground">{filteredPrompts.length}</Badge>
              </TabsTrigger>
              <TabsTrigger
                value="system"
                className="bg-transparent border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent rounded-none h-11 px-1 font-bold text-muted-foreground data-[state=active]:text-foreground transition-all"
              >
                시스템 <Badge className="ml-2 h-5 w-5 p-0 flex items-center justify-center rounded-full bg-muted text-muted-foreground">{promptsByCategory.system.length}</Badge>
              </TabsTrigger>
              <TabsTrigger
                value="style"
                className="bg-transparent border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent rounded-none h-11 px-1 font-bold text-muted-foreground data-[state=active]:text-foreground transition-all"
              >
                스타일 <Badge className="ml-2 h-5 w-5 p-0 flex items-center justify-center rounded-full bg-muted text-muted-foreground">{promptsByCategory.style.length}</Badge>
              </TabsTrigger>
              <TabsTrigger
                value="custom"
                className="bg-transparent border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent rounded-none h-11 px-1 font-bold text-muted-foreground data-[state=active]:text-foreground transition-all"
              >
                커스텀 <Badge className="ml-2 h-5 w-5 p-0 flex items-center justify-center rounded-full bg-muted text-muted-foreground">{promptsByCategory.custom.length}</Badge>
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="all" className="mt-0 outline-none">
            <PromptTable
              prompts={filteredPrompts}
              onEdit={handleEditPrompt}
              onView={handleViewPrompt}
              onDelete={handleDeleteClick}
              onDuplicate={handleDuplicatePrompt}
              onToggleActive={handleToggleActive}
              loading={loading}
            />
          </TabsContent>

          <TabsContent value="system" className="mt-0 outline-none">
            <PromptTable
              prompts={promptsByCategory.system}
              onEdit={handleEditPrompt}
              onView={handleViewPrompt}
              onDelete={handleDeleteClick}
              onDuplicate={handleDuplicatePrompt}
              onToggleActive={handleToggleActive}
              loading={loading}
            />
          </TabsContent>

          <TabsContent value="style" className="mt-0 outline-none">
            <PromptTable
              prompts={promptsByCategory.style}
              onEdit={handleEditPrompt}
              onView={handleViewPrompt}
              onDelete={handleDeleteClick}
              onDuplicate={handleDuplicatePrompt}
              onToggleActive={handleToggleActive}
              loading={loading}
            />
          </TabsContent>

          <TabsContent value="custom" className="mt-0 outline-none">
            <PromptTable
              prompts={promptsByCategory.custom}
              onEdit={handleEditPrompt}
              onView={handleViewPrompt}
              onDelete={handleDeleteClick}
              onDuplicate={handleDuplicatePrompt}
              onToggleActive={handleToggleActive}
              loading={loading}
            />
          </TabsContent>
        </Tabs>

        {/* 편집/생성 다이얼로그 */}
        <Dialog open={editDialogOpen} onOpenChange={(open) => {
          setEditDialogOpen(open);
          if (!open) setModalError(null);
        }}>
          <DialogContent className="sm:max-w-2xl overflow-hidden p-0 rounded-3xl border-none">
            <DialogHeader className="p-6 pb-0">
              <DialogTitle className="text-xl font-bold">{isEditMode ? '프롬프트 편집' : '새 프롬프트 생성'}</DialogTitle>
              <DialogDescription>
                {isEditMode ? '기존 프롬프트를 수정합니다.' : '새로운 시스템 프롬프트를 생성합니다.'}
              </DialogDescription>
            </DialogHeader>

            <ScrollArea className="max-h-[60vh] p-6 pt-2">
              {modalError && (
                <Alert variant="destructive" className="mb-4 bg-destructive/10 text-destructive border-none rounded-2xl animate-in slide-in-from-top-2 duration-300">
                  <Info className="h-4 w-4" />
                  <AlertTitle className="font-bold">입력 오류</AlertTitle>
                  <AlertDescription className="text-sm">{modalError}</AlertDescription>
                </Alert>
              )}
              {editingPrompt && (
                <div className="space-y-6 pt-0">
                  <div className="space-y-2">
                    <Label htmlFor="prompt-name" className="text-sm font-bold">프롬프트 이름</Label>
                    <Input
                      id="prompt-name"
                      value={editingPrompt.name || ''}
                      onChange={(e) => setEditingPrompt({ ...editingPrompt, name: e.target.value })}
                      disabled={isEditMode && selectedPrompt?.category === 'system'}
                      className="rounded-xl border-border/60"
                      placeholder="프롬프트 명칭을 입력하세요"
                    />
                    {isEditMode && selectedPrompt?.category === 'system' && (
                      <p className="text-[10px] text-muted-foreground font-medium flex items-center gap-1">
                        <Info className="w-3 h-3" /> 시스템 프롬프트는 이름을 변경할 수 없습니다
                      </p>
                    )}
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="prompt-desc" className="text-sm font-bold">설명</Label>
                    <Input
                      id="prompt-desc"
                      value={editingPrompt.description || ''}
                      onChange={(e) => setEditingPrompt({ ...editingPrompt, description: e.target.value })}
                      className="rounded-xl border-border/60"
                      placeholder="어떤 역할이나 페르소나인지 간단히 설명하세요"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label className="text-sm font-bold">카테고리</Label>
                    <Select
                      value={editingPrompt.category || 'custom'}
                      onValueChange={(val) => setEditingPrompt({ ...editingPrompt, category: val as 'system' | 'assistant' | 'user' | 'custom' })}
                      disabled={isEditMode && selectedPrompt?.category === 'system'}
                    >
                      <SelectTrigger className="rounded-xl border-border/60">
                        <SelectValue placeholder="카테고리 선택" />
                      </SelectTrigger>
                      <SelectContent className="rounded-xl">
                        {PROMPT_CATEGORIES.map((category) => (
                          <SelectItem key={category.value} value={category.value}>
                            {category.label} - {category.description}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="prompt-content" className="text-sm font-bold">프롬프트 내용</Label>
                    <Textarea
                      id="prompt-content"
                      value={editingPrompt.content || ''}
                      onChange={(e) => setEditingPrompt({ ...editingPrompt, content: e.target.value })}
                      className="min-h-[200px] rounded-xl border-border/60 font-mono text-sm leading-relaxed"
                      placeholder="AI에게 전달할 시스템 지침을 입력하세요..."
                    />
                  </div>

                  <div className="flex items-center justify-between p-4 bg-muted/30 rounded-2xl border border-border/40">
                    <div className="space-y-0.5">
                      <Label className="text-sm font-bold">활성화 상태</Label>
                      <p className="text-xs text-muted-foreground font-medium">저장 시 이 프롬프트를 즉시 적용합니다.</p>
                    </div>
                    <Switch
                      checked={editingPrompt.is_active !== false}
                      onCheckedChange={(checked) => setEditingPrompt({ ...editingPrompt, is_active: checked })}
                    />
                  </div>
                </div>
              )}
            </ScrollArea>

            <DialogFooter className="p-6 border-t border-border/40 bg-muted/10">
              <Button variant="ghost" onClick={() => setEditDialogOpen(false)} className="rounded-xl font-bold">
                취소
              </Button>
              <Button onClick={handleSavePrompt} className="rounded-xl font-bold gap-2 px-8">
                <Save className="w-4 h-4" />
                저장하기
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* 보기 다이얼로그 */}
        <Dialog open={viewDialogOpen} onOpenChange={setViewDialogOpen}>
          <DialogContent className="sm:max-w-2xl overflow-hidden p-0 rounded-3xl border-none">
            <DialogHeader className="p-6 pb-0">
              <DialogTitle className="text-xl font-bold">프롬프트 상세 정보</DialogTitle>
              <DialogDescription>
                프롬프트의 구성 요소와 설정 내역을 확인합니다.
              </DialogDescription>
            </DialogHeader>

            <ScrollArea className="max-h-[70vh] p-6">
              {selectedPrompt && (
                <div className="space-y-8">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1">
                      <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">프롬프트명</Label>
                      <p className="font-bold flex items-center gap-2">
                        {selectedPrompt.name}
                        <Badge variant={selectedPrompt.is_active ? "default" : "secondary"} className="h-5 text-[10px] rounded-sm font-black">
                          {selectedPrompt.is_active ? 'ACTIVE' : 'INACTIVE'}
                        </Badge>
                      </p>
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">카테고리</Label>
                      <div>
                        <Badge variant="outline" className="rounded-md border-primary/20 text-primary bg-primary/5 font-bold">
                          {PROMPT_CATEGORIES.find(c => c.value === selectedPrompt.category)?.label || selectedPrompt.category}
                        </Badge>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">설명</Label>
                    <p className="text-sm text-foreground/80 leading-relaxed">{selectedPrompt.description || '설명이 없습니다.'}</p>
                  </div>

                  <div className="grid grid-cols-2 gap-4 pt-2">
                    <div className="space-y-1">
                      <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">생성일</Label>
                      <p className="text-xs font-medium text-muted-foreground italic">{new Date(selectedPrompt.created_at).toLocaleString('ko-KR')}</p>
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">수정일</Label>
                      <p className="text-xs font-medium text-muted-foreground italic">{new Date(selectedPrompt.updated_at).toLocaleString('ko-KR')}</p>
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <Label className="text-[10px] uppercase tracking-wider font-extrabold text-muted-foreground">프롬프트 본문</Label>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-[10px] px-2 rounded-lg font-bold gap-1"
                        onClick={() => {
                          navigator.clipboard.writeText(selectedPrompt.content);
                        }}
                      >
                        <Copy className="w-3 h-3" /> 복사
                      </Button>
                    </div>
                    <div className="p-4 bg-muted/50 rounded-2xl border border-border/40 min-h-[100px] overflow-auto">
                      <pre className="text-xs font-mono leading-relaxed whitespace-pre-wrap break-all opacity-80 select-all">
                        {selectedPrompt.content}
                      </pre>
                    </div>
                  </div>
                </div>
              )}
            </ScrollArea>

            <DialogFooter className="p-6 border-t border-border/40 bg-muted/10">
              <Button variant="ghost" onClick={() => setViewDialogOpen(false)} className="rounded-xl font-bold">
                닫기
              </Button>
              {selectedPrompt && (
                <Button onClick={() => {
                  setViewDialogOpen(false);
                  handleEditPrompt(selectedPrompt);
                }} className="rounded-xl font-bold gap-2 px-8">
                  <Edit2 className="w-4 h-4" />
                  프롬프트 수정
                </Button>
              )}
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* 삭제 확인 다이얼로그 */}
        <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
          <DialogContent className="sm:max-w-md p-0 overflow-hidden rounded-3xl border-none shadow-2xl">
            <div className="p-8 pb-4 text-center space-y-4">
              <div className="mx-auto w-16 h-16 bg-destructive/10 rounded-full flex items-center justify-center text-destructive">
                <Trash2 className="w-8 h-8" />
              </div>
              <div className="space-y-1">
                <h3 className="text-xl font-bold text-foreground">프롬프트 삭제</h3>
                <p className="text-sm text-muted-foreground">
                  '<span className="font-bold text-foreground">{selectedPrompt?.name}</span>' 프롬프트를 정말 삭제하시겠습니까?<br />이 작업은 되돌릴 수 없습니다.
                </p>
              </div>

              {selectedPrompt?.category === 'system' && (
                <Alert variant="destructive" className="bg-destructive/10 text-destructive border-none rounded-2xl text-left mt-4 p-3">
                  <Info className="h-4 w-4" />
                  <AlertDescription className="text-xs font-bold leading-tight uppercase tracking-tight">
                    시스템 핵심 프롬프트입니다. 삭제 시 시스템 동작이 불안정해질 수 있습니다.
                  </AlertDescription>
                </Alert>
              )}
            </div>
            <DialogFooter className="p-6 pt-2 grid grid-cols-2 gap-3">
              <Button variant="outline" onClick={() => setDeleteDialogOpen(false)} className="rounded-xl font-bold h-12">
                취소
              </Button>
              <Button variant="destructive" onClick={handleDeletePrompt} className="rounded-xl font-bold h-12 shadow-lg shadow-destructive/20">
                확인 및 삭제
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* 가져오기 다이얼로그 */}
        <Dialog open={importDialogOpen} onOpenChange={setImportDialogOpen}>
          <DialogContent className="sm:max-w-2xl overflow-hidden p-0 rounded-3xl border-none">
            <DialogHeader className="p-6 pb-0">
              <DialogTitle className="text-xl font-bold">프롬프트 데이터 가져오기</DialogTitle>
              <DialogDescription>
                JSON 형식으로 내보낸 프롬프트 데이터를 복사하여 아래에 붙여넣어 주세요.
              </DialogDescription>
            </DialogHeader>

            <div className="p-6 space-y-6">
              <Alert className="bg-primary/5 border-none text-primary/80 rounded-2xl p-4">
                <Info className="h-4 w-4" />
                <AlertDescription className="text-xs font-medium">
                  내보내기 기능을 통해 저장된 파일의 JSON 본문 전체를 입력해 주세요.
                </AlertDescription>
              </Alert>

              <div className="space-y-2">
                <Label className="text-sm font-bold">JSON 데이터</Label>
                <Textarea
                  placeholder='{"prompts": [...], "exported_at": "...", "total": 0}'
                  value={importData}
                  onChange={(e) => setImportData(e.target.value)}
                  className="min-h-[250px] font-mono text-xs rounded-xl border-border/60"
                />
              </div>

              <div className="flex items-center justify-between p-4 bg-muted/30 rounded-2xl border border-border/40">
                <div className="space-y-0.5">
                  <Label className="text-sm font-bold">중복 시 덮어쓰기</Label>
                  <p className="text-xs text-muted-foreground font-medium italic">이미 동일한 이름의 프롬프트가 존재하는 경우 새로운 데이터로 교체합니다.</p>
                </div>
                <Switch
                  checked={importOverwrite}
                  onCheckedChange={setImportOverwrite}
                />
              </div>
            </div>

            <DialogFooter className="p-6 border-t border-border/40 bg-muted/10">
              <Button variant="ghost" onClick={() => setImportDialogOpen(false)} className="rounded-xl font-bold">
                취소
              </Button>
              <Button
                onClick={handleImportPrompts}
                disabled={!importData.trim()}
                className="rounded-xl font-bold px-10 shadow-lg shadow-primary/20"
              >
                데이터 가져오기
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </TooltipProvider>
  );
};

interface PromptTableProps {
  prompts: Prompt[];
  onEdit: (prompt: Prompt) => void;
  onView: (prompt: Prompt) => void;
  onDelete: (prompt: Prompt) => void;
  onDuplicate: (prompt: Prompt) => void;
  onToggleActive: (prompt: Prompt) => void;
  loading?: boolean;
}

const PromptTable: React.FC<PromptTableProps> = ({
  prompts,
  onEdit,
  onView,
  onDelete,
  onDuplicate,
  onToggleActive,
  loading = false,
}) => {
  const [isAnimating, setIsAnimating] = useState<string | null>(null);

  const handleToggleWithAnimation = useCallback((prompt: Prompt) => {
    if (!prompt.is_active) {
      setIsAnimating(prompt.id);
      setTimeout(() => setIsAnimating(null), 600);
    }
    onToggleActive(prompt);
  }, [onToggleActive]);

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
                "group border-border/40 transition-all duration-300",
                prompt.is_active ? "bg-primary/[0.03] hover:bg-primary/[0.05]" : "hover:bg-muted/30",
                isAnimating === prompt.id && "animate-pulse scale-[0.99] bg-primary/10"
              )}
            >
              <TableCell className="py-4">
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "font-bold transition-all truncate",
                    prompt.is_active ? "text-primary" : "text-foreground/80 group-hover:text-foreground"
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
              <TableCell className="py-4">
                <p className="text-sm text-muted-foreground line-clamp-1 group-hover:text-foreground/70 transition-colors">
                  {prompt.description || '-'}
                </p>
              </TableCell>
              <TableCell className="py-4">
                <Badge variant="outline" className={cn(
                  "rounded-md text-[10px] font-extrabold uppercase py-0 group-hover:border-primary/30 transition-all",
                  prompt.category === 'system' ? "bg-blue-500/5 text-blue-500 border-blue-500/20" :
                    prompt.category === 'style' ? "bg-purple-500/5 text-purple-500 border-purple-500/20" :
                      "bg-muted/50 text-muted-foreground border-border/50"
                )}>
                  {PROMPT_CATEGORIES.find(c => c.value === prompt.category)?.label || prompt.category}
                </Badge>
              </TableCell>
              <TableCell className="py-4">
                <Switch
                  checked={prompt.is_active}
                  onCheckedChange={() => handleToggleWithAnimation(prompt)}
                  className="data-[state=checked]:bg-primary h-5 w-9 scale-90"
                />
              </TableCell>
              <TableCell className="py-4 text-right text-xs font-medium text-muted-foreground">
                {new Date(prompt.updated_at).toLocaleDateString('ko-KR', {
                  year: '2-digit', month: '2-digit', day: '2-digit'
                })}
              </TableCell>
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

export default PromptManager;