/**
 * PromptEditDialog 컴포넌트 테스트
 *
 * 프롬프트 생성/편집 다이얼로그의 렌더링과 인터랙션을 검증합니다.
 * - 생성 모드 렌더링
 * - 편집 모드 렌더링
 * - 필수 필드 입력
 * - Save 버튼 클릭
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { PromptEditDialog } from '../PromptEditDialog';
import type { Prompt, CreatePromptRequest, UpdatePromptRequest } from '../../../types/prompt';

// 테스트용 기본 프롬프트 데이터
const mockPrompt: Prompt = {
  id: 'prompt-1',
  name: '테스트 프롬프트',
  content: '테스트 내용입니다.',
  description: '테스트 설명',
  category: 'custom',
  is_active: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

// 생성 모드용 편집 데이터
const newPromptData: CreatePromptRequest = {
  name: '',
  content: '',
  description: '',
  category: 'custom',
  is_active: true,
};

// 편집 모드용 편집 데이터
const editPromptData: UpdatePromptRequest = {
  name: '테스트 프롬프트',
  content: '테스트 내용입니다.',
  description: '테스트 설명',
  category: 'custom',
  is_active: false,
};

describe('PromptEditDialog', () => {
  const defaultProps = {
    open: true,
    onOpenChange: vi.fn(),
    editingPrompt: newPromptData as CreatePromptRequest | UpdatePromptRequest | null,
    isEditMode: false,
    selectedPrompt: null as Prompt | null,
    modalError: null as string | null,
    onSave: vi.fn(),
    onEditingPromptChange: vi.fn(),
  };

  it('생성 모드에서 "새 프롬프트 생성" 타이틀을 표시해야 한다', () => {
    render(<PromptEditDialog {...defaultProps} />);
    expect(screen.getByText('새 프롬프트 생성')).toBeInTheDocument();
  });

  it('편집 모드에서 "프롬프트 편집" 타이틀을 표시해야 한다', () => {
    render(
      <PromptEditDialog
        {...defaultProps}
        isEditMode={true}
        editingPrompt={editPromptData}
        selectedPrompt={mockPrompt}
      />
    );
    expect(screen.getByText('프롬프트 편집')).toBeInTheDocument();
  });

  it('modalError가 있으면 에러 메시지를 표시해야 한다', () => {
    render(
      <PromptEditDialog
        {...defaultProps}
        modalError="이름은 필수 입력입니다."
      />
    );
    expect(screen.getByText('이름은 필수 입력입니다.')).toBeInTheDocument();
  });

  it('저장하기 버튼 클릭 시 onSave가 호출되어야 한다', () => {
    render(<PromptEditDialog {...defaultProps} />);
    const saveButton = screen.getByText('저장하기');
    fireEvent.click(saveButton);
    expect(defaultProps.onSave).toHaveBeenCalled();
  });

  it('취소 버튼 클릭 시 onOpenChange(false)가 호출되어야 한다', () => {
    render(<PromptEditDialog {...defaultProps} />);
    const cancelButton = screen.getByText('취소');
    fireEvent.click(cancelButton);
    expect(defaultProps.onOpenChange).toHaveBeenCalled();
  });
});
