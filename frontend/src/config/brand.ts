/* eslint-disable no-restricted-syntax */
/**
 * 모노톤 브랜드 설정 파일
 *
 * ⚠️ 완전한 모노톤 디자인 시스템
 * ⚠️ 모든 색상은 COLORS (colors.ts)에서 관리
 * ⚠️ 이 파일은 브랜드 메타데이터만 포함 (보라색 사용 금지)
 */

// 브랜드 정보
export const BRAND_CONFIG = {
  // 앱 이름
  appName: 'OneRAG',
  appTitle: 'OneRAG', // HTML title

  // 로고 설정
  logo: {
    // 메인 로고 (기본 OneRAG 텍스트로 대체하기 위해 빈 문자열 혹은 파비콘 할당)
    main: '', // 텍스트 로고로 렌더링하도록 유도
    // 다크 모드용 로고
    dark: '',
    // 파비콘
    favicon: '/chatbot.svg',
    // 다양한 크기의 아이콘
    icon192: '/icon-192x192.png',
    icon512: '/icon-512x512.png',
    // 애플 터치 아이콘
    appleTouchIcon: '/apple-touch-icon.png',
    // 로고 대체 텍스트
    alt: 'OneRAG 로고',
    // 로고 사용 방식
    type: 'text' as 'image' | 'svg-component' | 'text', // 'text': 텍스트 로고
    // SVG 컴포넌트를 사용할 경우 폴백 이미지
    fallback: '/chatbot.svg',
  },

  // 그림자 설정 - 모노톤
  shadows: {
    default: {
      light: '0 2px 8px rgba(0, 0, 0, 0.04)',
      dark: '0 2px 8px rgba(0, 0, 0, 0.3)',
    },
    hover: {
      light: '0 4px 12px rgba(0, 0, 0, 0.08)',
      dark: '0 4px 12px rgba(0, 0, 0, 0.4)',
    },
    medium: {
      light: '0 4px 14px 0 rgba(0, 0, 0, 0.08)',
      dark: '0 4px 14px 0 rgba(0, 0, 0, 0.3)',
    },
  },
} as const;

// 페이지별 제목 생성 헬퍼 함수
export const getPageTitle = (pageName?: string): string => {
  if (pageName) {
    return `${BRAND_CONFIG.appName} - ${pageName}`;
  }
  return BRAND_CONFIG.appName;
};

export default BRAND_CONFIG;
