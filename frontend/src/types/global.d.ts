// Feature Flag 설정 타입 (features.ts에서 import)
import type { FeatureConfig } from '../config/features';

// Railway 런타임 설정 타입 정의
interface RuntimeConfig {
  ACCESS_CODE?: string;
  API_BASE_URL?: string;
  WS_BASE_URL?: string;
  // 빈 화면(Empty State) 등 관리자 쓰기 API에 사용하는 X-API-Key.
  // 배포 시 주입되면 운영자가 키를 수동 입력하지 않아도 관리자 저장이 동작한다.
  ADMIN_API_KEY?: string;
  NODE_ENV?: string;
  TIMESTAMP?: string;
  RAILWAY_ENVIRONMENT?: string | null;
  // Feature Flag 설정 추가
  FEATURES?: Partial<FeatureConfig>;
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
