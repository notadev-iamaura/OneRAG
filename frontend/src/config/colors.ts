/* eslint-disable no-restricted-syntax */
/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * 중앙 집중식 색상 관리 시스템
 *
 * ⚠️ 모든 색상은 이 파일에서만 정의하고 관리합니다.
 * ⚠️ 컴포넌트에서 직접 색상 값을 하드코딩하지 마세요.
 *
 * 사용법:
 * import { COLORS } from '@/config/colors';
 * className={cn("text-primary", ...)} // Tailwind 우선 사용 권장
 */

/**
 * 모노톤 색상 팔레트
 * 다크모드/라이트모드 지원
 */
export const COLORS = {
  // 기본 텍스트 색상
  text: {
    primary: {
      light: '#1a1a1a',
      dark: '#ffffff',
    },
    secondary: {
      light: '#666666',
      dark: '#a0a0a0',
    },
    disabled: {
      light: '#999999',
      dark: '#666666',
    },
  },

  // 배경 색상
  background: {
    // 메인 배경
    primary: {
      light: '#ffffff',
      dark: '#1a1a1a',
    },
    // 보조 배경
    secondary: {
      light: '#f5f5f5',
      dark: '#2d2d2d',
    },
    // 3차 배경
    tertiary: {
      light: '#e8e8e8',
      dark: '#404040',
    },
    // 페이퍼 배경
    paper: {
      light: '#ffffff',
      dark: '#1a1a1a',
    },
  },

  // 그라디언트 배경
  gradient: {
    // 상단바 그라디언트 (실제 헤더용 - 순수 검정)
    header: {
      light: '#000000',
      dark: '#000000',
    },
    // 채팅화면 헤더 그라디언트 (원래 그라디언트 유지)
    chatHeader: {
      light: 'linear-gradient(135deg, #ffffff 0%, #f5f5f5 50%, #e8e8e8 100%)',
      dark: 'linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 50%, #404040 100%)',
    },
    // 메시지 영역 그라디언트
    message: {
      light: 'linear-gradient(to bottom, #FAFAFA 0%, #F5F5F5 100%)',
      dark: 'linear-gradient(to bottom, #1a1a1a 0%, #0d0d0d 100%)',
    },
    // 버튼 그라디언트
    button: {
      light: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      dark: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    },
    // 버튼 호버 그라디언트
    buttonHover: {
      light: 'linear-gradient(135deg, #5568d3 0%, #63408b 100%)',
      dark: 'linear-gradient(135deg, #5568d3 0%, #63408b 100%)',
    },
  },

  // 인터랙티브 요소 (버튼, 카드 등)
  interactive: {
    // 기본 상태
    default: {
      light: 'rgba(0, 0, 0, 0.04)',
      dark: 'rgba(255, 255, 255, 0.08)',
    },
    // 호버 상태
    hover: {
      light: 'rgba(0, 0, 0, 0.08)',
      dark: 'rgba(255, 255, 255, 0.12)',
    },
    // 활성 상태
    active: {
      light: 'rgba(0, 0, 0, 0.12)',
      dark: 'rgba(255, 255, 255, 0.18)',
    },
    // 비활성 상태
    disabled: {
      light: 'rgba(128, 128, 128, 0.15)',
      dark: 'rgba(128, 128, 128, 0.15)',
    },
  },

  // 보더 색상
  border: {
    default: {
      light: 'rgba(0, 0, 0, 0.06)',
      dark: 'rgba(255, 255, 255, 0.08)',
    },
    hover: {
      light: 'rgba(0, 0, 0, 0.12)',
      dark: 'rgba(255, 255, 255, 0.15)',
    },
    focus: {
      light: 'rgba(0, 0, 0, 0.15)',
      dark: 'rgba(255, 255, 255, 0.2)',
    },
  },

  // 그림자
  shadow: {
    sm: {
      light: '0 2px 8px rgba(0, 0, 0, 0.04)',
      dark: '0 2px 8px rgba(0, 0, 0, 0.3)',
    },
    md: {
      light: '0 4px 12px rgba(0, 0, 0, 0.08)',
      dark: '0 4px 12px rgba(0, 0, 0, 0.4)',
    },
    lg: {
      light: '0 8px 24px rgba(0, 0, 0, 0.08)',
      dark: '0 8px 24px rgba(0, 0, 0, 0.3)',
    },
  },

  // 상태 표시 색상 (성공, 오류, 경고 등)
  status: {
    success: {
      light: 'rgba(0, 128, 0, 0.1)',
      dark: 'rgba(0, 255, 0, 0.15)',
    },
    error: {
      light: 'rgba(255, 0, 0, 0.1)',
      dark: 'rgba(255, 100, 100, 0.15)',
    },
    warning: {
      light: 'rgba(255, 165, 0, 0.1)',
      dark: 'rgba(255, 200, 0, 0.15)',
    },
    info: {
      light: 'rgba(0, 0, 255, 0.1)',
      dark: 'rgba(100, 150, 255, 0.15)',
    },
  },

  // 투명도 레벨
  opacity: {
    backdrop: {
      light: 'rgba(255, 255, 255, 0.95)',
      dark: 'rgba(26, 26, 26, 0.95)',
    },
    overlay: {
      light: 'rgba(0, 0, 0, 0.5)',
      dark: 'rgba(0, 0, 0, 0.7)',
    },
  },

  // 스크롤바 색상
  scrollbar: {
    thumb: {
      light: 'rgba(0, 0, 0, 0.2)',
      dark: 'rgba(255, 255, 255, 0.2)',
    },
    thumbHover: {
      light: 'rgba(0, 0, 0, 0.35)',
      dark: 'rgba(255, 255, 255, 0.35)',
    },
  },

  // 차트 색상 (데이터 시각화)
  chart: {
    blue: '#0066cc',
    green: '#28a745',
    yellow: '#ffc107',
    purple: '#8884d8',
    orange: '#ff9800',
    red: '#d32f2f',
    background: {
      light: '#f8f9fa',
      dark: '#2d2d2d',
    },
    border: {
      light: '#e9ecef',
      dark: 'rgba(255, 255, 255, 0.12)',
    },
    cardBg: {
      light: '#fafbfc',
      dark: '#1f1f1f',
    },
  },


  // Semantic 색상 (시스템 상태 표시)
  semantic: {
    error: {
      main: {
        light: '#d32f2f',
        dark: '#ff6b6b',
      },
      light: {
        light: '#ef5350',
        dark: '#ff8787',
      },
      dark: {
        light: '#c62828',
        dark: '#ff4f4f',
      },
    },
    warning: {
      main: {
        light: '#ed6c02',
        dark: '#ffa726',
      },
      light: {
        light: '#ff9800',
        dark: '#ffb74d',
      },
      dark: {
        light: '#e65100',
        dark: '#f57c00',
      },
      background: {
        light: '#fff3e0',
        dark: 'rgba(255, 167, 38, 0.15)',
      },
      text: {
        light: '#e65100',
        dark: '#ffb74d',
      },
    },
    success: {
      main: {
        light: '#2e7d32',
        dark: '#66bb6a',
      },
      light: {
        light: '#4caf50',
        dark: '#81c784',
      },
      dark: {
        light: '#1b5e20',
        dark: '#4caf50',
      },
    },
    info: {
      main: {
        light: '#0288d1',
        dark: '#29b6f6',
      },
      light: {
        light: '#03a9f4',
        dark: '#4fc3f7',
      },
      dark: {
        light: '#01579b',
        dark: '#0277bd',
      },
    },
  },

  // 공통 스타일 상수
  common: {
    // 헤더 그라디언트
    headerGradient: {
      light: '#000000',
      dark: '#000000',
    },
    // 카드 그림자
    cardShadow: {
      light: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
      dark: '0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -1px rgba(0, 0, 0, 0.2)',
    },
    // 모달 그림자
    modalShadow: {
      light: '0 8px 40px rgba(0, 0, 0, 0.12)',
      dark: '0 8px 40px rgba(0, 0, 0, 0.5)',
    },
    // 호버 그림자
    hoverShadow: {
      light: '0 4px 16px rgba(0, 0, 0, 0.12)',
      dark: '0 4px 16px rgba(0, 0, 0, 0.4)',
    },
    // 강한 호버 그림자
    hoverShadowStrong: {
      light: '0 6px 20px rgba(0, 0, 0, 0.15)',
      dark: '0 6px 20px rgba(0, 0, 0, 0.5)',
    },
  },
} as const;

/**
 * 테마 모드에 따른 색상 가져오기 헬퍼 함수
 */
export const getColor = (
  colorPath: string,
  mode: 'light' | 'dark' = 'light'
): string => {
  const keys = colorPath.split('.');
  let value: any = COLORS;

  for (const key of keys) {
    if (value && typeof value === 'object') {
      value = value[key];
    } else {
      return '';
    }
  }

  if (value && typeof value === 'object' && (value.light || value.dark)) {
    return value[mode] || '';
  }

  return typeof value === 'string' ? value : '';
};


/**
 * light/dark 모드별 색상 쌍
 */
export interface ColorPair {
  light: string;
  dark: string;
}

/**
 * 브랜드 색상 (프리셋에서만 제공되는 선택 항목)
 */
export interface BrandColors {
  primary: ColorPair;
  secondary: ColorPair;
  accent: ColorPair;
}

/** `as const` 리터럴 색상 값을 일반 string으로 넓힌다(프리셋/런타임 오버라이드 허용). */
type WidenColorValues<T> = T extends string
  ? string
  : { -readonly [K in keyof T]: WidenColorValues<T[K]> };

/**
 * ColorConfig 타입 정의 (프리셋 시스템에서 사용)
 */
export type ColorConfig = WidenColorValues<typeof COLORS> & {
  brand?: BrandColors;
};
