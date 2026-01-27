/**
 * Feature Flag 설정 시스템
 *
 * 이 파일은 애플리케이션의 기능 모듈을 제어하는 Feature Flag를 정의합니다.
 * 환경변수와 런타임 구성을 통해 기능의 활성화/비활성화를 제어할 수 있습니다.
 */

/**
 * 챗봇 기능 설정
 */
export interface ChatbotFeatures {
  enabled: boolean;           // 챗봇 기능 전체 활성화 여부
  streaming: boolean;         // 스트리밍 응답 기능
  history: boolean;           // 채팅 기록 기능
  sessionManagement: boolean; // 세션 관리 기능
  markdown: boolean;          // 마크다운 렌더링 기능
}

/**
 * 문서 관리 기능 설정
 */
export interface DocumentManagementFeatures {
  enabled: boolean;      // 문서 관리 기능 전체 활성화 여부
  upload: boolean;       // 파일 업로드 기능
  bulkDelete: boolean;   // 일괄 삭제 기능
  search: boolean;       // 검색 기능
  pagination: boolean;   // 페이지네이션 기능
  dragAndDrop: boolean;  // 드래그 앤 드롭 업로드 기능
  preview: boolean;      // 문서 미리보기 기능
}

/**
 * 관리자 기능 설정
 */
export interface AdminFeatures {
  enabled: boolean;          // 관리자 기능 전체 활성화 여부
  userManagement: boolean;   // 사용자 관리 기능
  systemStats: boolean;      // 시스템 통계 기능
  qdrantManagement: boolean; // Qdrant 벡터 DB 관리 기능
  accessControl: boolean;    // 접근 제어 기능
}

/**
 * 프롬프트 관리 기능 설정
 */
export interface PromptsFeatures {
  enabled: boolean;    // 프롬프트 관리 기능 활성화 여부
  templates: boolean;  // 템플릿 기능
  history: boolean;    // 프롬프트 기록 기능
}

/**
 * 분석 기능 설정
 */
export interface AnalysisFeatures {
  enabled: boolean;      // 분석 기능 활성화 여부
  realtime: boolean;     // 실시간 분석 기능
  export: boolean;       // 데이터 내보내기 기능
  visualization: boolean; // 시각화 기능
}

/**
 * 프라이버시 기능 설정
 */
export interface PrivacyFeatures {
  enabled: boolean;          // 프라이버시 기능 전체 활성화 여부
  maskPhoneNumbers: boolean; // 전화번호 자동 마스킹 기능
}

/**
 * 전체 Feature Flag 설정 인터페이스
 */
export interface FeatureConfig {
  chatbot: ChatbotFeatures;
  documentManagement: DocumentManagementFeatures;
  admin: AdminFeatures;
  prompts: PromptsFeatures;
  analysis: AnalysisFeatures;
  privacy: PrivacyFeatures;
}

/**
 * 기본 Feature Flag 설정
 * 모든 기능이 활성화된 상태
 */
export const DEFAULT_FEATURES: FeatureConfig = {
  chatbot: {
    enabled: true,
    streaming: true,
    history: true,
    sessionManagement: true,
    markdown: true,
  },
  documentManagement: {
    enabled: true,
    upload: true,
    bulkDelete: true,
    search: true,
    pagination: true,
    dragAndDrop: true,
    preview: true,
  },
  admin: {
    enabled: true,
    userManagement: true,
    systemStats: true,
    qdrantManagement: true,
    accessControl: true,
  },
  prompts: {
    enabled: true,
    templates: true,
    history: true,
  },
  analysis: {
    enabled: true,
    realtime: true,
    export: true,
    visualization: true,
  },
  privacy: {
    enabled: true,
    maskPhoneNumbers: true,
  },
};

/**
 * 환경변수에서 boolean 값을 안전하게 파싱
 */
function parseBooleanEnv(value: string | undefined, defaultValue: boolean): boolean {
  if (value === undefined) return defaultValue;
  return value.toLowerCase() === 'true';
}

/**
 * 환경변수에서 Feature Flag 로드
 */
function loadFeaturesFromEnv(): Partial<FeatureConfig> {
  const env = import.meta.env;

  return {
    chatbot: {
      enabled: parseBooleanEnv(env.VITE_FEATURE_CHATBOT, true),
      streaming: parseBooleanEnv(env.VITE_FEATURE_CHATBOT_STREAMING, true),
      history: parseBooleanEnv(env.VITE_FEATURE_CHATBOT_HISTORY, true),
      sessionManagement: parseBooleanEnv(env.VITE_FEATURE_CHATBOT_SESSION, true),
      markdown: parseBooleanEnv(env.VITE_FEATURE_CHATBOT_MARKDOWN, true),
    },
    documentManagement: {
      enabled: parseBooleanEnv(env.VITE_FEATURE_DOCUMENTS, true),
      upload: parseBooleanEnv(env.VITE_FEATURE_DOCUMENTS_UPLOAD, true),
      bulkDelete: parseBooleanEnv(env.VITE_FEATURE_DOCUMENTS_BULK_DELETE, true),
      search: parseBooleanEnv(env.VITE_FEATURE_DOCUMENTS_SEARCH, true),
      pagination: parseBooleanEnv(env.VITE_FEATURE_DOCUMENTS_PAGINATION, true),
      dragAndDrop: parseBooleanEnv(env.VITE_FEATURE_DOCUMENTS_DND, true),
      preview: parseBooleanEnv(env.VITE_FEATURE_DOCUMENTS_PREVIEW, true),
    },
    admin: {
      enabled: parseBooleanEnv(env.VITE_FEATURE_ADMIN, true),
      userManagement: parseBooleanEnv(env.VITE_FEATURE_ADMIN_USERS, true),
      systemStats: parseBooleanEnv(env.VITE_FEATURE_ADMIN_STATS, true),
      qdrantManagement: parseBooleanEnv(env.VITE_FEATURE_ADMIN_QDRANT, true),
      accessControl: parseBooleanEnv(env.VITE_FEATURE_ADMIN_ACCESS, true),
    },
    prompts: {
      enabled: parseBooleanEnv(env.VITE_FEATURE_PROMPTS, true),
      templates: parseBooleanEnv(env.VITE_FEATURE_PROMPTS_TEMPLATES, true),
      history: parseBooleanEnv(env.VITE_FEATURE_PROMPTS_HISTORY, true),
    },
    analysis: {
      enabled: parseBooleanEnv(env.VITE_FEATURE_ANALYSIS, true),
      realtime: parseBooleanEnv(env.VITE_FEATURE_ANALYSIS_REALTIME, true),
      export: parseBooleanEnv(env.VITE_FEATURE_ANALYSIS_EXPORT, true),
      visualization: parseBooleanEnv(env.VITE_FEATURE_ANALYSIS_VIZ, true),
    },
    privacy: {
      enabled: parseBooleanEnv(env.VITE_FEATURE_PRIVACY, true),
      maskPhoneNumbers: parseBooleanEnv(env.VITE_FEATURE_PRIVACY_MASK_PHONE, true),
    },
  };
}

/**
 * 런타임 구성에서 Feature Flag 로드
 */
function loadFeaturesFromRuntime(): Partial<FeatureConfig> {
  // window.RUNTIME_CONFIG가 존재하지 않으면 빈 객체 반환
  if (typeof window === 'undefined' || !window.RUNTIME_CONFIG?.FEATURES) {
    return {};
  }

  return window.RUNTIME_CONFIG.FEATURES as Partial<FeatureConfig>;
}

/**
 * 깊은 병합 유틸리티 함수
 */
function deepMerge<T extends Record<string, unknown>>(target: T, source: Partial<T>): T {
  const result = { ...target };

  for (const key in source) {
    if (Object.prototype.hasOwnProperty.call(source, key)) {
      const sourceValue = source[key];
      const targetValue = result[key];

      if (
        sourceValue &&
        typeof sourceValue === 'object' &&
        !Array.isArray(sourceValue) &&
        targetValue &&
        typeof targetValue === 'object' &&
        !Array.isArray(targetValue)
      ) {
        result[key] = deepMerge(targetValue, sourceValue);
      } else if (sourceValue !== undefined) {
        result[key] = sourceValue;
      }
    }
  }

  return result;
}

/**
 * 최종 Feature Flag 설정 로드
 * 우선순위: 런타임 구성 > 환경변수 > 기본값
 */
export function loadFeatureConfig(): FeatureConfig {
  let config = { ...DEFAULT_FEATURES };

  // 1. 환경변수에서 로드 (기본값 덮어쓰기)
  const envFeatures = loadFeaturesFromEnv();
  config = deepMerge(config, envFeatures);

  // 2. 런타임 구성에서 로드 (최종 덮어쓰기)
  const runtimeFeatures = loadFeaturesFromRuntime();
  config = deepMerge(config, runtimeFeatures);

  return config;
}

/**
 * 특정 모듈이 활성화되어 있는지 확인
 */
export function isModuleEnabled(config: FeatureConfig, module: keyof FeatureConfig): boolean {
  return config[module].enabled;
}

/**
 * 특정 기능이 활성화되어 있는지 확인
 */
export function isFeatureEnabled(
  config: FeatureConfig,
  module: keyof FeatureConfig,
  feature: string
): boolean {
  const moduleConfig = config[module] as Record<string, boolean>;
  return moduleConfig.enabled && moduleConfig[feature];
}
