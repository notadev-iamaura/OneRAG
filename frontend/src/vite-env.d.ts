/// <reference types="vite/client" />

// Vite 환경변수 타입 정의
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_DEV_API_BASE_URL: string;
  readonly VITE_DEV_WS_BASE_URL: string;
  readonly VITE_ACCESS_CODE: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
