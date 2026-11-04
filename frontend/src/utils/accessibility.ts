/**
 * 접근성 유틸리티 함수
 * ARIA 속성, 시맨틱 HTML, 스크린 리더 지원
 */

/**
 * 스크린 리더 전용 텍스트 생성
 * 시각적으로는 숨겨지지만 스크린 리더에서는 읽힘
 */
export const srOnlyStyles = {
  position: 'absolute' as const,
  width: '1px',
  height: '1px',
  padding: 0,
  margin: '-1px',
  overflow: 'hidden',
  clip: 'rect(0, 0, 0, 0)',
  whiteSpace: 'nowrap' as const,
  borderWidth: 0,
};

/**
 * ARIA Live Region 업데이트
 * 동적 콘텐츠 변경 시 스크린 리더에 알림
 */
export function announceToScreenReader(
  message: string,
  priority: 'polite' | 'assertive' = 'polite'
): void {
  const announcement = document.createElement('div');
  announcement.setAttribute('role', 'status');
  announcement.setAttribute('aria-live', priority);
  announcement.setAttribute('aria-atomic', 'true');
  announcement.style.cssText = Object.entries(srOnlyStyles)
    .map(([key, value]) => `${key}: ${value}`)
    .join('; ');
  announcement.textContent = message;

  document.body.appendChild(announcement);

  // 3초 후 제거
  setTimeout(() => {
    document.body.removeChild(announcement);
  }, 3000);
}

/**
 * 포커스 가능한 요소 조회
 */
export function getFocusableElements(container: HTMLElement): HTMLElement[] {
  const selector =
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  return Array.from(container.querySelectorAll<HTMLElement>(selector));
}

/**
 * 첫 번째 포커스 가능한 요소로 이동
 */
export function focusFirstElement(container: HTMLElement): void {
  const focusableElements = getFocusableElements(container);
  focusableElements[0]?.focus();
}

/**
 * 마지막 포커스 가능한 요소로 이동
 */
export function focusLastElement(container: HTMLElement): void {
  const focusableElements = getFocusableElements(container);
  focusableElements[focusableElements.length - 1]?.focus();
}

/**
 * ARIA 속성 생성 헬퍼
 */
export interface AriaAttributes {
  role?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  'aria-describedby'?: string;
  'aria-expanded'?: boolean;
  'aria-hidden'?: boolean;
  'aria-disabled'?: boolean;
  'aria-checked'?: boolean;
  'aria-pressed'?: boolean;
  'aria-selected'?: boolean;
  'aria-current'?: 'page' | 'step' | 'location' | 'date' | 'time' | boolean;
  'aria-live'?: 'polite' | 'assertive' | 'off';
  'aria-atomic'?: boolean;
  'aria-busy'?: boolean;
  'aria-controls'?: string;
  'aria-haspopup'?: boolean | 'menu' | 'listbox' | 'tree' | 'grid' | 'dialog';
  'aria-modal'?: boolean;
  'aria-required'?: boolean;
  'aria-invalid'?: boolean;
  'aria-errormessage'?: string;
}

/**
 * 색상 대비 비율 계산 (WCAG 2.1)
 * @returns 대비 비율 (1-21)
 */
export function calculateContrastRatio(
  foreground: string,
  background: string
): number {
  const getLuminance = (color: string): number => {
    // RGB 추출 (hex 또는 rgb 형식)
    let r: number, g: number, b: number;

    if (color.startsWith('#')) {
      const hex = color.substring(1);
      r = parseInt(hex.substring(0, 2), 16);
      g = parseInt(hex.substring(2, 4), 16);
      b = parseInt(hex.substring(4, 6), 16);
    } else if (color.startsWith('rgb')) {
      const match = color.match(/\d+/g);
      if (!match) return 0;
      const [matchedR, matchedG, matchedB] = match.map(Number);
      if (matchedR === undefined || matchedG === undefined || matchedB === undefined) return 0;
      r = matchedR;
      g = matchedG;
      b = matchedB;
    } else {
      return 0;
    }

    // sRGB → 선형 RGB 변환
    const toLinear = (value: number): number => {
      const v = value / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };

    const rLinear = toLinear(r);
    const gLinear = toLinear(g);
    const bLinear = toLinear(b);

    // 상대 휘도 계산
    return 0.2126 * rLinear + 0.7152 * gLinear + 0.0722 * bLinear;
  };

  const l1 = getLuminance(foreground);
  const l2 = getLuminance(background);

  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);

  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * WCAG 색상 대비 검증
 * @param level - 'AA' 또는 'AAA'
 * @param isLargeText - 큰 텍스트 여부 (18pt+ 또는 14pt+ bold)
 */
export function meetsContrastRequirement(
  foreground: string,
  background: string,
  level: 'AA' | 'AAA' = 'AA',
  isLargeText: boolean = false
): boolean {
  const ratio = calculateContrastRatio(foreground, background);

  if (level === 'AAA') {
    return isLargeText ? ratio >= 4.5 : ratio >= 7;
  } else {
    return isLargeText ? ratio >= 3 : ratio >= 4.5;
  }
}

/**
 * 키보드 전용 사용자 감지
 */
export function detectKeyboardUser(): void {
  let isKeyboardUser = false;

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Tab') {
      isKeyboardUser = true;
      document.body.classList.add('keyboard-user');
    }
  });

  document.addEventListener('mousedown', () => {
    if (isKeyboardUser) {
      isKeyboardUser = false;
      document.body.classList.remove('keyboard-user');
    }
  });
}

/**
 * 고대비 모드 감지
 */
export function isHighContrastMode(): boolean {
  if (typeof window === 'undefined') return false;

  return window.matchMedia('(prefers-contrast: high)').matches;
}

/**
 * 감소된 모션 모드 감지
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false;

  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * 다크 모드 감지
 */
export function prefersDarkMode(): boolean {
  if (typeof window === 'undefined') return false;

  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

/**
 * 문서 제목 업데이트 (스크린 리더 알림)
 */
export function updateDocumentTitle(title: string, announce: boolean = false): void {
  document.title = title;

  if (announce) {
    announceToScreenReader(`페이지 제목이 ${title}(으)로 변경되었습니다.`);
  }
}

/**
 * Skip Link 컴포넌트를 위한 메인 콘텐츠 ID
 */
export const MAIN_CONTENT_ID = 'main-content';

/**
 * 메인 콘텐츠로 포커스 이동
 */
export function skipToMainContent(): void {
  const mainContent = document.getElementById(MAIN_CONTENT_ID);
  if (mainContent) {
    mainContent.focus();
    mainContent.scrollIntoView();
  }
}
