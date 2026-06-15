/**
 * AccessControl 컴포넌트 테스트
 *
 * 관리자 접근 코드의 결정 우선순위를 검증한다:
 *   1) window.RUNTIME_CONFIG.ACCESS_CODE (config.js — 재배포 없이 변경 가능)
 *   2) VITE_ACCESS_CODE (개발 모드 빌드 환경변수)
 *   3) 기본값 '1127' (하위 호환)
 *
 * 핵심 회귀 보호: 접근 코드는 모듈 로드 시점이 아니라 "제출 시점"에 평가되어야
 * config.js 로드 순서/테스트 환경과 무관하게 런타임 설정이 반영된다.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { AccessControl } from '../AccessControl';

// 로거 mock (콘솔 노이즈 차단)
vi.mock('../../utils/logger', () => ({
  logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

/** 접근코드 입력 후 제출 폼을 클릭하는 헬퍼 */
const submitCode = (code: string) => {
  const input = document.querySelector('input[type="password"]') as HTMLInputElement;
  expect(input).toBeTruthy();
  fireEvent.change(input, { target: { value: code } });
  const submitButton = document.querySelector('button[type="submit"]') as HTMLButtonElement;
  expect(submitButton).toBeTruthy();
  fireEvent.click(submitButton);
};

describe('AccessControl', () => {
  const onAccessGranted = vi.fn();
  const onCancel = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    delete window.RUNTIME_CONFIG;
  });

  afterEach(() => {
    delete window.RUNTIME_CONFIG;
    sessionStorage.clear();
  });

  it('설정이 없으면 기본 코드 1127로 접근이 허용된다 (하위 호환)', () => {
    render(<AccessControl isOpen onAccessGranted={onAccessGranted} onCancel={onCancel} />);

    submitCode('1127');

    expect(onAccessGranted).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem('admin_access_granted')).toBe('true');
  });

  it('잘못된 코드는 거부되고 권한이 저장되지 않는다', () => {
    render(<AccessControl isOpen onAccessGranted={onAccessGranted} onCancel={onCancel} />);

    submitCode('0000');

    expect(onAccessGranted).not.toHaveBeenCalled();
    expect(sessionStorage.getItem('admin_access_granted')).toBeNull();
  });

  it('RUNTIME_CONFIG.ACCESS_CODE가 설정되면 그 값으로 접근이 허용된다', () => {
    window.RUNTIME_CONFIG = { ACCESS_CODE: '2580' };
    render(<AccessControl isOpen onAccessGranted={onAccessGranted} onCancel={onCancel} />);

    submitCode('2580');

    expect(onAccessGranted).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem('admin_access_granted')).toBe('true');
  });

  it('RUNTIME_CONFIG.ACCESS_CODE가 설정되면 기본 코드 1127은 거부된다', () => {
    window.RUNTIME_CONFIG = { ACCESS_CODE: '2580' };
    render(<AccessControl isOpen onAccessGranted={onAccessGranted} onCancel={onCancel} />);

    submitCode('1127');

    expect(onAccessGranted).not.toHaveBeenCalled();
    expect(sessionStorage.getItem('admin_access_granted')).toBeNull();
  });

  it('RUNTIME_CONFIG.ACCESS_CODE가 빈 문자열이면 기본 코드로 폴백한다', () => {
    window.RUNTIME_CONFIG = { ACCESS_CODE: '' };
    render(<AccessControl isOpen onAccessGranted={onAccessGranted} onCancel={onCancel} />);

    submitCode('1127');

    expect(onAccessGranted).toHaveBeenCalledTimes(1);
  });

  it('RUNTIME_CONFIG.ACCESS_CODE가 공백뿐이면 기본 코드로 폴백한다', () => {
    window.RUNTIME_CONFIG = { ACCESS_CODE: '   ' };
    render(<AccessControl isOpen onAccessGranted={onAccessGranted} onCancel={onCancel} />);

    submitCode('1127');

    expect(onAccessGranted).toHaveBeenCalledTimes(1);
  });

  it('런타임 코드 앞뒤 공백은 무시하고 비교한다', () => {
    window.RUNTIME_CONFIG = { ACCESS_CODE: ' 2580 ' };
    render(<AccessControl isOpen onAccessGranted={onAccessGranted} onCancel={onCancel} />);

    submitCode('2580');

    expect(onAccessGranted).toHaveBeenCalledTimes(1);
  });

  it('컴포넌트 렌더 후 RUNTIME_CONFIG가 바뀌어도 제출 시점 값으로 평가한다', () => {
    render(<AccessControl isOpen onAccessGranted={onAccessGranted} onCancel={onCancel} />);
    // 렌더(모듈 로드) 이후에 런타임 설정 주입 — 제출 시점 평가 보장 검증
    window.RUNTIME_CONFIG = { ACCESS_CODE: '7777' };

    submitCode('7777');

    expect(onAccessGranted).toHaveBeenCalledTimes(1);
  });
});
