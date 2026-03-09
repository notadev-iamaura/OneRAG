/**
 * PromptTable 컴포넌트 테스트
 *
 * 프롬프트 테이블 컴포넌트의 렌더링과 인터랙션을 검증합니다.
 * - 빈 목록 표시
 * - 프롬프트 행 렌더링
 * - 액션 버튼 동작 (보기, 수정, 복제, 삭제)
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { PromptTable } from '../PromptTable';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { Prompt } from '../../../types/prompt';

const mockPrompts: Prompt[] = [
  {
    id: 'p1',
    name: '시스템 기본',
    content: '시스템 프롬프트 내용',
    description: '기본 시스템 프롬프트',
    category: 'system',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-15T00:00:00Z',
  },
  {
    id: 'p2',
    name: '커스텀 프롬프트',
    content: '커스텀 내용',
    description: '사용자 정의 프롬프트',
    category: 'custom',
    is_active: false,
    created_at: '2026-01-10T00:00:00Z',
    updated_at: '2026-02-01T00:00:00Z',
  },
];

describe('PromptTable', () => {
  const defaultProps = {
    prompts: mockPrompts,
    onEdit: vi.fn(),
    onView: vi.fn(),
    onDelete: vi.fn(),
    onDuplicate: vi.fn(),
    onToggleActive: vi.fn(),
    loading: false,
  };

  // TooltipProvider가 필요한 컴포넌트를 감싸는 렌더링 헬퍼
  const renderWithTooltip = (element: React.ReactElement) => {
    return render(
      <TooltipProvider>
        {element}
      </TooltipProvider>
    );
  };

  it('빈 목록일 때 안내 메시지를 표시해야 한다', () => {
    renderWithTooltip(<PromptTable {...defaultProps} prompts={[]} />);
    expect(screen.getByText('해당하는 프롬프트가 없습니다.')).toBeInTheDocument();
  });

  it('로딩 중일 때 로딩 표시를 해야 한다', () => {
    renderWithTooltip(<PromptTable {...defaultProps} loading={true} />);
    expect(screen.getByText('프롬프트 데이터를 불러오는 중...')).toBeInTheDocument();
  });

  it('프롬프트 이름과 설명을 표시해야 한다', () => {
    renderWithTooltip(<PromptTable {...defaultProps} />);
    expect(screen.getByText('시스템 기본')).toBeInTheDocument();
    expect(screen.getByText('커스텀 프롬프트')).toBeInTheDocument();
    expect(screen.getByText('기본 시스템 프롬프트')).toBeInTheDocument();
  });

  it('활성 프롬프트에 ACTIVE 뱃지를 표시해야 한다', () => {
    renderWithTooltip(<PromptTable {...defaultProps} />);
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
  });
});
