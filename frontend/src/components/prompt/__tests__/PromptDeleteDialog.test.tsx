/**
 * PromptDeleteDialog 컴포넌트 테스트
 *
 * 프롬프트 삭제 확인 다이얼로그의 렌더링과 인터랙션을 검증합니다.
 * - 삭제 확인 메시지 표시
 * - 확인/취소 버튼 동작
 * - 시스템 프롬프트 삭제 경고 표시
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { PromptDeleteDialog } from '../PromptDeleteDialog';
import type { Prompt } from '../../../types/prompt';

const mockPrompt: Prompt = {
  id: 'prompt-1',
  name: '커스텀 프롬프트',
  content: '내용',
  description: '설명',
  category: 'custom',
  is_active: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const systemPrompt: Prompt = {
  id: 'prompt-sys',
  name: 'system',
  content: '시스템 내용',
  description: '시스템 설명',
  category: 'system',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

describe('PromptDeleteDialog', () => {
  const defaultProps = {
    open: true,
    onOpenChange: vi.fn(),
    selectedPrompt: mockPrompt,
    onConfirm: vi.fn(),
  };

  it('삭제할 프롬프트 이름을 표시해야 한다', () => {
    render(<PromptDeleteDialog {...defaultProps} />);
    expect(screen.getByText(/커스텀 프롬프트/)).toBeInTheDocument();
  });

  it('확인 및 삭제 버튼 클릭 시 onConfirm이 호출되어야 한다', () => {
    render(<PromptDeleteDialog {...defaultProps} />);
    const confirmButton = screen.getByText('확인 및 삭제');
    fireEvent.click(confirmButton);
    expect(defaultProps.onConfirm).toHaveBeenCalled();
  });

  it('취소 버튼 클릭 시 onOpenChange(false)가 호출되어야 한다', () => {
    render(<PromptDeleteDialog {...defaultProps} />);
    const cancelButton = screen.getByText('취소');
    fireEvent.click(cancelButton);
    expect(defaultProps.onOpenChange).toHaveBeenCalledWith(false);
  });

  it('시스템 프롬프트 삭제 시 경고 메시지를 표시해야 한다', () => {
    render(
      <PromptDeleteDialog
        {...defaultProps}
        selectedPrompt={systemPrompt}
      />
    );
    expect(screen.getByText(/시스템 핵심 프롬프트입니다/)).toBeInTheDocument();
  });
});
