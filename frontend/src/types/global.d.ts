// Feature Flag 설정 타입 (features.ts에서 import)
import type { FeatureConfig } from '../config/features';

// Railway 런타임 설정 타입 정의
interface RuntimeConfig {
  ACCESS_CODE?: string;
  API_BASE_URL?: string;
  WS_BASE_URL?: string;
  NODE_ENV?: string;
  TIMESTAMP?: string;
  RAILWAY_ENVIRONMENT?: string | null;
  // Feature Flag 설정 추가
  FEATURES?: Partial<FeatureConfig>;
}

// window 객체 확장 - 전체 앱에서 사용
declare global {
  interface Window {
    RUNTIME_CONFIG?: RuntimeConfig;
  }
}

export {};
