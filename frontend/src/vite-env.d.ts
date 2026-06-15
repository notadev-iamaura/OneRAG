/// <reference types="vite/client" />

// Vite 환경변수 타입 정의
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_DEV_API_BASE_URL: string;
  readonly VITE_DEV_WS_BASE_URL: string;
  readonly VITE_ACCESS_CODE: string;
  // i18n 기본 로케일 재정의(미설정 시 'ko'). 지원 값: 'ko' | 'en'
  readonly VITE_DEFAULT_LOCALE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
