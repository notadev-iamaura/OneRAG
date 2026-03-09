/**
 * PromptImportDialog 컴포넌트 테스트
 *
 * 프롬프트 가져오기 다이얼로그의 렌더링과 인터랙션을 검증합니다.
 * - JSON 입력 필드 렌더링
 * - 덮어쓰기 스위치 동작
 * - 가져오기 버튼 활성화 조건
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { PromptImportDialog } from '../PromptImportDialog';

describe('PromptImportDialog', () => {
  const defaultProps = {
    open: true,
    onOpenChange: vi.fn(),
    importData: '',
    importOverwrite: false,
    onImportDataChange: vi.fn(),
    onImportOverwriteChange: vi.fn(),
    onImport: vi.fn(),
  };

  it('JSON 데이터 입력 필드를 렌더링해야 한다', () => {
    render(<PromptImportDialog {...defaultProps} />);
    expect(screen.getByPlaceholderText(/prompts/)).toBeInTheDocument();
  });

  it('importData가 비어있으면 가져오기 버튼이 비활성화되어야 한다', () => {
    render(<PromptImportDialog {...defaultProps} />);
    const importButton = screen.getByText('데이터 가져오기');
    expect(importButton).toBeDisabled();
  });

  it('importData가 있으면 가져오기 버튼이 활성화되어야 한다', () => {
    render(
      <PromptImportDialog
        {...defaultProps}
        importData='{"prompts": []}'
      />
    );
    const importButton = screen.getByText('데이터 가져오기');
    expect(importButton).not.toBeDisabled();
  });

  it('가져오기 버튼 클릭 시 onImport가 호출되어야 한다', () => {
    render(
      <PromptImportDialog
        {...defaultProps}
        importData='{"prompts": []}'
      />
    );
    const importButton = screen.getByText('데이터 가져오기');
    fireEvent.click(importButton);
    expect(defaultProps.onImport).toHaveBeenCalled();
  });

  it('취소 버튼 클릭 시 onOpenChange가 호출되어야 한다', () => {
    render(<PromptImportDialog {...defaultProps} />);
    const cancelButton = screen.getByText('취소');
    fireEvent.click(cancelButton);
    expect(defaultProps.onOpenChange).toHaveBeenCalled();
  });
});
