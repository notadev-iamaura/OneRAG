// Feature Flag 설정 타입 (features.ts에서 import)
import type { FeatureConfig } from '../config/features';
import type { DeepPartial } from '../config/deepPartial';

// Railway 런타임 설정 타입 정의
interface RuntimeConfig {
  ACCESS_CODE?: string;
  API_BASE_URL?: string;
  WS_BASE_URL?: string;
  // 관리자 API 키(X-API-Key)는 런타임 설정에 포함하지 않는다. config.js는 공개 정적
  // 파일이므로 비밀값을 넣을 수 없다. 키는 운영자 설정(localStorage)에서만 읽는다.
  NODE_ENV?: string;
  TIMESTAMP?: string;
  RAILWAY_ENVIRONMENT?: string | null;
  // Feature Flag 설정 추가
  FEATURES?: DeepPartial<FeatureConfig>;
  // 임베드(embed) 허용 부모 origin 화이트리스트.
  // 외부 사이트에 /embed/chat을 iframe으로 임베드할 때, postMessage 통신을 허용할 origin 목록이다.
  // 배열 또는 콤마 구분 문자열을 모두 허용하며, 와일드카드('*')는 지원하지 않는다(보안).
  // 미설정(빈 배열)이면 현재 origin(same-origin)만 허용한다.
  EMBED_ALLOWED_ORIGINS?: string[] | string;
}

// window 객체 확장 - 전체 앱에서 사용
declare global {
  interface Window {
    RUNTIME_CONFIG?: RuntimeConfig;
  }
}

export {};
