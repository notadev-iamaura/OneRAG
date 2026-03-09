/**
 * 프롬프트 관리 비즈니스 로직 훅
 *
 * PromptManager.tsx에서 추출한 17개 상태 변수와 11개 핸들러를 관리합니다.
 * 프롬프트 CRUD, 활성/비활성 토글, 가져오기/내보내기, 필터링 로직을 담당합니다.
 *
 * 주요 기능:
 * - 프롬프트 목록 로드 및 활성 프롬프트 자동 조정 (단일 활성 규칙)
 * - 프롬프트 생성/수정/삭제/복제
 * - 프롬프트 활성/비활성 토글 (라디오 방식: 1개만 활성)
 * - JSON 내보내기/가져오기
 * - 카테고리/활성 상태/검색어 필터링
 *
 * 의존성: promptService, useToast
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useToast } from '@/hooks/use-toast';
import { logger } from '../../utils/logger';
import promptService from '../../services/promptService';
import type {
  Prompt,
  CreatePromptRequest,
  UpdatePromptRequest,
} from '../../types/prompt';

// 안전한 에러 메시지 추출 유틸리티
function getErrorMessage(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: string } } }).response;
    const detail = response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
  }
  return fallback;
}

/** usePromptManager 훅 반환 타입 */
export interface UsePromptManagerReturn {
  // 상태 (17개)
  prompts: Prompt[];
  loading: boolean;
  error: string | null;
  modalError: string | null;
  currentTab: string;
  editDialogOpen: boolean;
  viewDialogOpen: boolean;
  deleteDialogOpen: boolean;
  importDialogOpen: boolean;
  selectedPrompt: Prompt | null;
  editingPrompt: CreatePromptRequest | UpdatePromptRequest | null;
  isEditMode: boolean;
  categoryFilter: string;
  activeFilter: string;
  searchQuery: string;
  importData: string;
  importOverwrite: boolean;

  // computed 값
  filteredPrompts: Prompt[];
  promptsByCategory: {
    system: Prompt[];
    style: Prompt[];
    custom: Prompt[];
  };

  // 핸들러 (11개 + 복제)
  loadPrompts: () => Promise<void>;
  handleCreateNew: () => void;
  handleEdit: (prompt: Prompt) => void;
  handleView: (prompt: Prompt) => void;
  handleDelete: (prompt: Prompt) => void;
  handleToggleActive: (prompt: Prompt) => Promise<void>;
  handleSave: () => Promise<void>;
  handleExport: () => Promise<void>;
  handleImportPrompts: () => Promise<void>;
  handleDeleteConfirm: () => Promise<void>;
  handleDuplicate: (prompt: Prompt) => Promise<void>;

  // setter 함수 (JSX에서 직접 사용)
  setEditDialogOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setViewDialogOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setDeleteDialogOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setImportDialogOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setCurrentTab: React.Dispatch<React.SetStateAction<string>>;
  setSearchQuery: React.Dispatch<React.SetStateAction<string>>;
  setCategoryFilter: React.Dispatch<React.SetStateAction<string>>;
  setActiveFilter: React.Dispatch<React.SetStateAction<string>>;
  setImportData: React.Dispatch<React.SetStateAction<string>>;
  setImportOverwrite: React.Dispatch<React.SetStateAction<boolean>>;
  setEditingPrompt: React.Dispatch<React.SetStateAction<CreatePromptRequest | UpdatePromptRequest | null>>;
  setError: React.Dispatch<React.SetStateAction<string | null>>;
  setModalError: React.Dispatch<React.SetStateAction<string | null>>;
}

/**
 * 프롬프트 관리 비즈니스 로직 훅
 *
 * PromptManager 컴포넌트의 모든 상태와 비즈니스 로직을 캡슐화합니다.
 * 컴포넌트는 이 훅의 반환값을 사용하여 JSX만 렌더링합니다.
 */
export const usePromptManager = (): UsePromptManagerReturn => {
  const { toast } = useToast();

  // ============================================================
  // 상태 관리 (17개)
  // ============================================================

  // 프롬프트 목록 및 로딩 상태
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);
  const [currentTab, setCurrentTab] = useState('all');

  // 다이얼로그 상태
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

  // ============================================================
  // 핸들러 (11개 + 복제)
  // ============================================================

  /** 프롬프트 목록 로드 (활성 프롬프트 자동 조정 포함) */
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
        // 활성 프롬프트가 여러 개인 경우: 첫 번째만 남기고 나머지 비활성화
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

  /** 새 프롬프트 생성 다이얼로그 열기 */
  const handleCreateNew = useCallback(() => {
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
  }, []);

  /** 프롬프트 편집 다이얼로그 열기 */
  const handleEdit = useCallback((prompt: Prompt) => {
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
  }, []);

  /** 프롬프트 상세 보기 다이얼로그 열기 */
  const handleView = useCallback((prompt: Prompt) => {
    setSelectedPrompt(prompt);
    setViewDialogOpen(true);
  }, []);

  /** 프롬프트 삭제 다이얼로그 열기 */
  const handleDelete = useCallback((prompt: Prompt) => {
    setSelectedPrompt(prompt);
    setDeleteDialogOpen(true);
  }, []);

  /** 프롬프트 삭제 확인 */
  const handleDeleteConfirm = useCallback(async () => {
    if (!selectedPrompt) return;

    try {
      const name = selectedPrompt.name;
      await promptService.deletePrompt(selectedPrompt.id);
      setDeleteDialogOpen(false);
      setSelectedPrompt(null);
      toast({
        variant: 'destructive',
        title: '프롬프트 삭제 완료',
        description: `'${name}' 프롬프트가 영구적으로 삭제되었습니다.`,
      });
      await loadPrompts();
    } catch (err: unknown) {
      logger.error('프롬프트 삭제 실패:', err);
      setError(getErrorMessage(err, '프롬프트 삭제에 실패했습니다.'));
    }
  }, [selectedPrompt, loadPrompts, toast]);

  /** 프롬프트 저장 (생성/수정) */
  const handleSave = useCallback(async () => {
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
          title: '프롬프트 수정 완료',
          description: `'${editingPrompt.name}' 프롬프트가 성공적으로 수정되었습니다.`,
        });
      } else {
        // 생성
        await promptService.createPrompt(editingPrompt as CreatePromptRequest);
        toast({
          title: '새 프롬프트 생성',
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
  }, [editingPrompt, isEditMode, selectedPrompt, loadPrompts, toast]);

  /** 프롬프트 활성/비활성 토글 (단일 선택 방식) */
  const handleToggleActive = useCallback(async (prompt: Prompt) => {
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
          title: '프롬프트 활성화',
          description: `'${prompt.name}' 프롬프트가 이제 시스템에 적용됩니다.`,
        });
      } else {
        // 비활성화하려는 경우
        const activeCount = prompts.filter(p => p.is_active).length;

        if (activeCount === 1) {
          // 마지막 활성 프롬프트를 비활성화하려는 경우
          const systemPrompt = prompts.find(p => p.category === 'system' && p.name === 'system');

          if (systemPrompt && systemPrompt.id !== prompt.id) {
            // 현재 프롬프트를 비활성화하고 시스템 프롬프트를 활성화
            await promptService.togglePrompt(prompt.id, false);
            await promptService.togglePrompt(systemPrompt.id, true);
            toast({
              title: '프롬프트 기본값 전환',
              description: `'${prompt.name}'이 비활성화되어 기본 시스템 프롬프트로 전환되었습니다.`,
            });
          } else {
            // 시스템 프롬프트가 없거나, 현재 프롬프트가 시스템 프롬프트인 경우
            setError('최소 하나의 프롬프트는 활성화되어 있어야 합니다.');
            return;
          }
        } else {
          // 다른 활성 프롬프트가 있는 경우 단순히 비활성화
          await promptService.togglePrompt(prompt.id, false);
          toast({
            title: '프롬프트 비활성화',
            description: `'${prompt.name}' 프롬프트가 비활성화되었습니다.`,
          });
        }
      }

      await loadPrompts();
    } catch (err: unknown) {
      logger.error('프롬프트 상태 변경 실패:', err);
      setError(getErrorMessage(err, '프롬프트 상태 변경에 실패했습니다.'));
    }
  }, [prompts, loadPrompts, toast]);

  /** 프롬프트 내보내기 (JSON 다운로드) */
  const handleExport = useCallback(async () => {
    if (prompts.length === 0) {
      toast({
        variant: 'destructive',
        title: '내보내기 실패',
        description: '내보낼 프롬프트가 없습니다.',
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
        title: '내보내기 완료',
        description: `'${fileName}' 파일이 다운로드되었습니다.`,
      });
    } catch (err: unknown) {
      logger.error('프롬프트 내보내기 실패:', err);
      setError('프롬프트 내보내기에 실패했습니다.');
    }
  }, [prompts, toast]);

  /**
   * 프롬프트 가져오기 (JSON 파싱 + API 호출)
   *
   * 버그 수정: promptService.importPrompts 반환 타입에 imported 필드만 존재.
   * 기존 PromptManager.tsx에서 result.updated를 참조하던 타입 불일치를 수정하여
   * imported 필드만 사용하도록 변경.
   */
  const handleImportPrompts = useCallback(async () => {
    try {
      const data = JSON.parse(importData);
      const result = await promptService.importPrompts(data, importOverwrite);
      setImportDialogOpen(false);
      setImportData('');
      setImportOverwrite(false);

      toast({
        title: '데이터 가져오기 성공',
        description: `${result.imported}개의 프롬프트를 가져왔습니다.`,
      });

      await loadPrompts();
    } catch (err: unknown) {
      logger.error('프롬프트 가져오기 실패:', err);
      setError(getErrorMessage(err, '프롬프트 가져오기에 실패했습니다.'));
    }
  }, [importData, importOverwrite, loadPrompts, toast]);

  /** 프롬프트 복제 */
  const handleDuplicate = useCallback(async (prompt: Prompt) => {
    try {
      const newName = `${prompt.name}_copy_${Date.now()}`;
      await promptService.duplicatePrompt(prompt.id, newName);
      toast({
        title: '프롬프트 복제 성공',
        description: `'${prompt.name}'의 복제본이 생성되었습니다.`,
      });
      await loadPrompts();
    } catch (err: unknown) {
      logger.error('프롬프트 복제 실패:', err);
      setError(getErrorMessage(err, '프롬프트 복제에 실패했습니다.'));
    }
  }, [loadPrompts, toast]);

  // ============================================================
  // computed 값
  // ============================================================

  /** 필터링된 프롬프트 목록 (활성 프롬프트를 상단에 정렬) */
  const filteredPrompts = useMemo(() => {
    return prompts
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
  }, [prompts, searchQuery]);

  /** 카테고리별 프롬프트 분류 */
  const promptsByCategory = useMemo(() => ({
    system: filteredPrompts.filter(p => p.category === 'system'),
    style: filteredPrompts.filter(p => p.category === 'style'),
    custom: filteredPrompts.filter(p => p.category === 'custom'),
  }), [filteredPrompts]);

  // ============================================================
  // 반환값
  // ============================================================

  return {
    // 상태
    prompts,
    loading,
    error,
    modalError,
    currentTab,
    editDialogOpen,
    viewDialogOpen,
    deleteDialogOpen,
    importDialogOpen,
    selectedPrompt,
    editingPrompt,
    isEditMode,
    categoryFilter,
    activeFilter,
    searchQuery,
    importData,
    importOverwrite,

    // computed
    filteredPrompts,
    promptsByCategory,

    // 핸들러
    loadPrompts,
    handleCreateNew,
    handleEdit,
    handleView,
    handleDelete,
    handleToggleActive,
    handleSave,
    handleExport,
    handleImportPrompts,
    handleDeleteConfirm,
    handleDuplicate,

    // setter
    setEditDialogOpen,
    setViewDialogOpen,
    setDeleteDialogOpen,
    setImportDialogOpen,
    setCurrentTab,
    setSearchQuery,
    setCategoryFilter,
    setActiveFilter,
    setImportData,
    setImportOverwrite,
    setEditingPrompt,
    setError,
    setModalError,
  };
};
