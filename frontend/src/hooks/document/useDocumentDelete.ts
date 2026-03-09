/**
 * 문서 삭제 관리 훅
 *
 * 단일 삭제, 일괄 삭제, 전체 삭제(2단계 확인) 플로우를 관리합니다.
 * documentAPI를 통해 백엔드와 통신하며, showToast와 onDeleted 콜백으로
 * 상위 컴포넌트에 결과를 알립니다.
 *
 * @example
 * const deletion = useDocumentDelete({
 *   showToast,
 *   onDeleted: list.fetchDocuments,
 *   clearSelection: selection.clearSelection,
 * });
 */
import { useState, useCallback } from 'react';
import type { ToastMessage } from '../../types';
import { documentAPI } from '../../services/api';
import { logger } from '../../utils/logger';

/** useDocumentDelete 훅의 옵션 */
interface UseDocumentDeleteOptions {
  /** 토스트 메시지 표시 콜백 */
  showToast: (message: Omit<ToastMessage, 'id'>) => void;
  /** 삭제 완료 후 호출되는 콜백 (목록 새로고침 등) */
  onDeleted: () => Promise<void> | void;
  /** 선택 초기화 콜백 */
  clearSelection: () => void;
}

/** useDocumentDelete 훅의 반환 타입 */
export interface UseDocumentDeleteReturn {
  /** 단일 삭제 확인 다이얼로그 열림 여부 */
  deleteConfirmOpen: boolean;
  /** 일괄 삭제 확인 다이얼로그 열림 여부 */
  bulkDeleteConfirmOpen: boolean;
  /** 전체 삭제 확인 다이얼로그 열림 여부 */
  deleteAllConfirmOpen: boolean;
  /** 전체 삭제 단계 (confirm: 1단계, typing: 2단계) */
  deleteAllStep: 'confirm' | 'typing';
  /** 전체 삭제 확인 문구 입력값 */
  deleteAllTyping: string;
  /** 삭제 대상 문서 ID */
  documentToDelete: string | null;
  /** 단일 삭제 로딩 상태 */
  deleteLoading: boolean;
  /** 일괄 삭제 로딩 상태 */
  bulkDeleteLoading: boolean;
  /** 전체 삭제 로딩 상태 */
  deleteAllLoading: boolean;
  /** 단일 삭제 다이얼로그 열기 */
  handleDeleteSingle: (id: string) => void;
  /** 일괄 삭제 다이얼로그 열기 */
  handleDeleteBulk: () => void;
  /** 전체 삭제 다이얼로그 열기 */
  handleDeleteAll: () => void;
  /** 단일 삭제 취소 */
  handleDeleteCancel: () => void;
  /** 일괄 삭제 취소 */
  handleBulkDeleteCancel: () => void;
  /** 전체 삭제 취소 (상태 초기화 포함) */
  handleDeleteAllCancel: () => void;
  /** 단일 삭제 확인 실행 */
  confirmDeleteSingle: () => Promise<void>;
  /** 일괄 삭제 확인 실행 */
  confirmDeleteBulk: (selectedDocuments: Set<string>) => Promise<void>;
  /** 전체 삭제 확인 실행 (2단계 플로우) */
  confirmDeleteAll: () => Promise<void>;
  /** 전체 삭제 확인 문구 입력 setter */
  setDeleteAllTyping: (value: string) => void;
}

/**
 * 문서 ID가 유효한지 확인합니다.
 */
const isValidDocumentId = (id: string): boolean =>
  Boolean(id && !id.startsWith('temp-') && id.trim() !== '');

/**
 * 문서 삭제 관리 훅
 *
 * 3가지 삭제 플로우를 제공합니다:
 * 1. 단일 삭제: handleDeleteSingle → confirmDeleteSingle
 * 2. 일괄 삭제: handleDeleteBulk → confirmDeleteBulk
 * 3. 전체 삭제: handleDeleteAll → confirmDeleteAll (confirm → typing 2단계)
 */
export const useDocumentDelete = ({
  showToast,
  onDeleted,
  clearSelection,
}: UseDocumentDeleteOptions): UseDocumentDeleteReturn => {
  // 단일 삭제 상태
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [documentToDelete, setDocumentToDelete] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // 일괄 삭제 상태
  const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false);
  const [bulkDeleteLoading, setBulkDeleteLoading] = useState(false);

  // 전체 삭제 상태
  const [deleteAllConfirmOpen, setDeleteAllConfirmOpen] = useState(false);
  const [deleteAllStep, setDeleteAllStep] = useState<'confirm' | 'typing'>('confirm');
  const [deleteAllTyping, setDeleteAllTyping] = useState('');
  const [deleteAllLoading, setDeleteAllLoading] = useState(false);

  // ============================================================
  // 단일 삭제 핸들러
  // ============================================================

  /** 단일 삭제 확인 다이얼로그를 엽니다 */
  const handleDeleteSingle = useCallback((id: string) => {
    setDocumentToDelete(id);
    setDeleteConfirmOpen(true);
  }, []);

  /** 단일 삭제를 취소합니다 */
  const handleDeleteCancel = useCallback(() => {
    setDeleteConfirmOpen(false);
    setDocumentToDelete(null);
  }, []);

  /** 단일 삭제를 실행합니다 */
  const confirmDeleteSingle = useCallback(async () => {
    if (!documentToDelete) return;

    setDeleteLoading(true);
    try {
      await documentAPI.deleteDocument(documentToDelete);
      showToast({ type: 'success', message: '문서 삭제 완료' });
      await onDeleted();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      logger.error('Document delete error:', error);
      showToast({
        type: 'error',
        message: err.response?.data?.message || '삭제 실패',
      });
    } finally {
      setDeleteLoading(false);
      setDeleteConfirmOpen(false);
      setDocumentToDelete(null);
    }
  }, [documentToDelete, showToast, onDeleted]);

  // ============================================================
  // 일괄 삭제 핸들러
  // ============================================================

  /** 일괄 삭제 확인 다이얼로그를 엽니다 */
  const handleDeleteBulk = useCallback(() => {
    setBulkDeleteConfirmOpen(true);
  }, []);

  /** 일괄 삭제를 취소합니다 */
  const handleBulkDeleteCancel = useCallback(() => {
    setBulkDeleteConfirmOpen(false);
  }, []);

  /** 일괄 삭제를 실행합니다 */
  const confirmDeleteBulk = useCallback(
    async (selectedDocuments: Set<string>) => {
      if (selectedDocuments.size === 0) {
        setBulkDeleteConfirmOpen(false);
        return;
      }

      setBulkDeleteLoading(true);
      try {
        const documentIds = Array.from(selectedDocuments).filter(isValidDocumentId);
        logger.log('Deleting documents:', documentIds);

        if (documentIds.length === 0) {
          showToast({
            type: 'warning',
            message: '삭제할 수 있는 유효한 문서가 없습니다.',
          });
          return;
        }

        await documentAPI.deleteDocuments(documentIds);
        showToast({
          type: 'success',
          message: `${documentIds.length}개 문서 삭제 완료`,
        });
        clearSelection();
        await onDeleted();
      } catch (error: unknown) {
        const err = error as { response?: { data?: { message?: string } } };
        logger.error('Bulk delete error:', error);
        showToast({
          type: 'error',
          message: err.response?.data?.message || '일괄 삭제 실패',
        });
      } finally {
        setBulkDeleteLoading(false);
        setBulkDeleteConfirmOpen(false);
      }
    },
    [showToast, onDeleted, clearSelection],
  );

  // ============================================================
  // 전체 삭제 핸들러 (2단계 확인)
  // ============================================================

  /** 전체 삭제 확인 다이얼로그를 엽니다 */
  const handleDeleteAll = useCallback(() => {
    setDeleteAllConfirmOpen(true);
  }, []);

  /** 전체 삭제를 취소하고 상태를 초기화합니다 */
  const handleDeleteAllCancel = useCallback(() => {
    setDeleteAllConfirmOpen(false);
    setDeleteAllStep('confirm');
    setDeleteAllTyping('');
  }, []);

  /**
   * 전체 삭제를 실행합니다 (2단계 플로우)
   *
   * 1단계 (confirm): typing 단계로 전환
   * 2단계 (typing): 올바른 문구 입력 확인 후 삭제 실행
   */
  const confirmDeleteAll = useCallback(async () => {
    // 1단계: confirm → typing
    if (deleteAllStep === 'confirm') {
      setDeleteAllStep('typing');
      return;
    }

    // 2단계: 문구 검증
    if (deleteAllTyping !== '문서 삭제에 동의합니다.') {
      showToast({ type: 'error', message: '문구를 정확히 입력해주세요.' });
      return;
    }

    // 삭제 실행
    setDeleteAllLoading(true);
    try {
      await documentAPI.deleteAllDocuments('DELETE_ALL_DOCUMENTS', '사용자 요청', false);
      showToast({ type: 'success', message: '모든 문서 삭제 완료' });
      clearSelection();
      await onDeleted();
      // 성공 시 상태 초기화
      handleDeleteAllCancel();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      logger.error('Delete all documents error:', error);
      showToast({
        type: 'error',
        message: err.response?.data?.message || '실패',
      });
    } finally {
      setDeleteAllLoading(false);
    }
  }, [deleteAllStep, deleteAllTyping, showToast, onDeleted, clearSelection, handleDeleteAllCancel]);

  return {
    // 상태
    deleteConfirmOpen,
    bulkDeleteConfirmOpen,
    deleteAllConfirmOpen,
    deleteAllStep,
    deleteAllTyping,
    documentToDelete,
    deleteLoading,
    bulkDeleteLoading,
    deleteAllLoading,
    // 핸들러
    handleDeleteSingle,
    handleDeleteBulk,
    handleDeleteAll,
    handleDeleteCancel,
    handleBulkDeleteCancel,
    handleDeleteAllCancel,
    confirmDeleteSingle,
    confirmDeleteBulk,
    confirmDeleteAll,
    setDeleteAllTyping,
  };
};
