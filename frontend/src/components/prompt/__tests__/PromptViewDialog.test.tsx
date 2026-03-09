/**
 * PromptViewDialog 컴포넌트 테스트
 *
 * 프롬프트 상세 조회 다이얼로그의 렌더링을 검증합니다.
 * - 프롬프트 내용 표시
 * - 복사 버튼 동작
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PromptViewDialog } from '../PromptViewDialog';
import type { Prompt } from '../../../types/prompt';

const mockPrompt: Prompt = {
  id: 'prompt-1',
  name: '시스템 프롬프트',
  content: '당신은 친절한 AI 어시스턴트입니다.',
  description: '기본 시스템 프롬프트',
  category: 'system',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-02-15T12:00:00Z',
};

// navigator.clipboard 모킹 (happy-dom에서는 defineProperty 사용 필요)
const mockWriteText = vi.fn().mockResolvedValue(undefined);

describe('PromptViewDialog', () => {
  const defaultProps = {
    open: true,
    onOpenChange: vi.fn(),
    selectedPrompt: mockPrompt,
    onEdit: vi.fn(),
  };

  beforeEach(() => {
    mockWriteText.mockClear();
    // happy-dom에서 clipboard는 read-only이므로 defineProperty로 오버라이드
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: mockWriteText },
      writable: true,
      configurable: true,
    });
  });

  it('프롬프트 이름과 내용을 표시해야 한다', () => {
    render(<PromptViewDialog {...defaultProps} />);
    expect(screen.getByText('시스템 프롬프트')).toBeInTheDocument();
    expect(screen.getByText('당신은 친절한 AI 어시스턴트입니다.')).toBeInTheDocument();
  });

  it('복사 버튼 클릭 시 clipboard에 내용을 복사해야 한다', () => {
    render(<PromptViewDialog {...defaultProps} />);
    const copyButton = screen.getByText('복사');
    fireEvent.click(copyButton);
    expect(mockWriteText).toHaveBeenCalledWith('당신은 친절한 AI 어시스턴트입니다.');
  });

  it('프롬프트 수정 버튼 클릭 시 onEdit이 호출되어야 한다', () => {
    render(<PromptViewDialog {...defaultProps} />);
    const editButton = screen.getByText('프롬프트 수정');
    fireEvent.click(editButton);
    expect(defaultProps.onEdit).toHaveBeenCalledWith(mockPrompt);
  });

  it('닫기 버튼 클릭 시 onOpenChange가 호출되어야 한다', () => {
    render(<PromptViewDialog {...defaultProps} />);
    const closeButton = screen.getByText('닫기');
    fireEvent.click(closeButton);
    expect(defaultProps.onOpenChange).toHaveBeenCalledWith(false);
  });
});
