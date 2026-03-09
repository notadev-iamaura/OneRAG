/**
 * 문서 선택 관리 훅
 *
 * 문서의 단일/전체 선택, 상세 보기 열기/닫기를 관리합니다.
 * 유효하지 않은 문서 ID(temp- 접두사, 빈 문자열)에 대한 검증을 포함합니다.
 *
 * @example
 * const selection = useDocumentSelection({ showToast });
 * // selection.toggleSelect('doc-1')
 * // selection.toggleSelectAll(documents)
 * // selection.viewDetails(document)
 */
import { useState, useCallback } from 'react';
import type { Document, ToastMessage } from '../../types';

/** useDocumentSelection 훅의 옵션 */
interface UseDocumentSelectionOptions {
  /** 토스트 메시지 표시 콜백 */
  showToast: (message: Omit<ToastMessage, 'id'>) => void;
}

/** useDocumentSelection 훅의 반환 타입 */
export interface UseDocumentSelectionReturn {
  /** 선택된 문서 ID 집합 */
  selectedDocuments: Set<string>;
  /** 상세 보기 중인 문서 */
  selectedDocument: Document | null;
  /** 상세 보기 다이얼로그 열림 여부 */
  detailsOpen: boolean;
  /** 문서 선택/해제 토글 */
  toggleSelect: (id: string) => void;
  /** 전체 선택/해제 토글 */
  toggleSelectAll: (documents: Document[]) => void;
  /** 선택 초기화 */
  clearSelection: () => void;
  /** 문서 상세 보기 열기 */
  viewDetails: (document: Document) => void;
  /** 문서 상세 보기 닫기 */
  closeDetails: () => void;
}

/**
 * 문서 ID가 유효한지 확인합니다.
 * temp- 접두사, 빈 문자열, 공백만 있는 경우를 유효하지 않은 것으로 판단합니다.
 */
const isValidDocumentId = (id: string): boolean =>
  Boolean(id && !id.startsWith('temp-') && id.trim() !== '');

/**
 * 문서 선택 관리 훅
 *
 * 문서 목록에서의 체크박스 선택, 전체 선택, 상세 보기를 관리합니다.
 */
export const useDocumentSelection = ({
  showToast,
}: UseDocumentSelectionOptions): UseDocumentSelectionReturn => {
  // 선택 상태
  const [selectedDocuments, setSelectedDocuments] = useState<Set<string>>(new Set());
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);

  /** 문서 선택/해제를 토글합니다 */
  const toggleSelect = useCallback(
    (id: string) => {
      if (!isValidDocumentId(id)) {
        showToast({ type: 'warning', message: '선택할 수 없는 문서입니다.' });
        return;
      }
      setSelectedDocuments((prev) => {
        const newSelection = new Set(prev);
        if (newSelection.has(id)) {
          newSelection.delete(id);
        } else {
          newSelection.add(id);
        }
        return newSelection;
      });
    },
    [showToast],
  );

  /** 전체 문서를 선택하거나 해제합니다 */
  const toggleSelectAll = useCallback((documents: Document[]) => {
    const validIds = documents
      .filter((doc) => isValidDocumentId(doc.id))
      .map((doc) => doc.id);

    setSelectedDocuments((prev) => {
      if (prev.size === validIds.length) {
        // 전체 선택됨 → 전체 해제
        return new Set();
      }
      // 전체 선택
      return new Set(validIds);
    });
  }, []);

  /** 선택을 모두 초기화합니다 */
  const clearSelection = useCallback(() => {
    setSelectedDocuments(new Set());
  }, []);

  /** 문서 상세 정보를 표시합니다 */
  const viewDetails = useCallback((document: Document) => {
    setSelectedDocument(document);
    setDetailsOpen(true);
  }, []);

  /** 문서 상세 보기를 닫습니다 */
  const closeDetails = useCallback(() => {
    setDetailsOpen(false);
  }, []);

  return {
    // 상태
    selectedDocuments,
    selectedDocument,
    detailsOpen,
    // 핸들러
    toggleSelect,
    toggleSelectAll,
    clearSelection,
    viewDetails,
    closeDetails,
  };
};
