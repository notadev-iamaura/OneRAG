import { DEFAULT_FEATURES } from './features';

export const OPERATOR_SETTINGS_STORAGE_KEY = 'onerag_operator_settings';

export interface OperatorSettings {
  apiBaseUrl: string;
  wsBaseUrl: string;
  defaultModel: string;
  ragProfile: 'basic' | 'hybrid' | 'hybrid-reranker' | 'graph-rag' | 'agent';
  chunkSize: number;
  chunkOverlap: number;
  enableStreaming: boolean;
  enableDocumentUpload: boolean;
  enablePhoneMasking: boolean;
  systemNotice: string;
  // 관리자 쓰기 API(X-API-Key)에 사용하는 키. 빈 화면 설정 저장/리셋 등에 사용한다.
  // 운영자가 직접 입력하거나, 배포 시 RUNTIME_CONFIG.ADMIN_API_KEY로 주입한다.
  adminApiKey: string;
}

export const DEFAULT_OPERATOR_SETTINGS: OperatorSettings = {
  apiBaseUrl: '',
  wsBaseUrl: '',
  defaultModel: 'gemini',
  ragProfile: 'hybrid-reranker',
  chunkSize: 1000,
  chunkOverlap: 150,
  enableStreaming: true,
  enableDocumentUpload: true,
  enablePhoneMasking: true,
  systemNotice: '',
  adminApiKey: '',
};

function normalizeSettings(value: Partial<OperatorSettings>): OperatorSettings {
  const chunkSize = Number(value.chunkSize);
  const chunkOverlap = Number(value.chunkOverlap);

  return {
    ...DEFAULT_OPERATOR_SETTINGS,
    ...value,
    chunkSize: Number.isFinite(chunkSize) && chunkSize > 0 ? chunkSize : DEFAULT_OPERATOR_SETTINGS.chunkSize,
    chunkOverlap: Number.isFinite(chunkOverlap) && chunkOverlap >= 0 ? chunkOverlap : DEFAULT_OPERATOR_SETTINGS.chunkOverlap,
    enableStreaming: value.enableStreaming ?? DEFAULT_OPERATOR_SETTINGS.enableStreaming,
    enableDocumentUpload: value.enableDocumentUpload ?? DEFAULT_OPERATOR_SETTINGS.enableDocumentUpload,
    enablePhoneMasking: value.enablePhoneMasking ?? DEFAULT_OPERATOR_SETTINGS.enablePhoneMasking,
    // 관리자 키는 공백을 제거해 저장한다(빈 문자열이면 미설정으로 간주).
    adminApiKey: (value.adminApiKey ?? DEFAULT_OPERATOR_SETTINGS.adminApiKey).trim(),
  };
}

export function hasStoredOperatorSettings(): boolean {
  if (typeof window === 'undefined') return false;
  return Boolean(localStorage.getItem(OPERATOR_SETTINGS_STORAGE_KEY));
}

export function readOperatorSettings(): OperatorSettings {
  if (typeof window === 'undefined') return DEFAULT_OPERATOR_SETTINGS;

  try {
    const raw = localStorage.getItem(OPERATOR_SETTINGS_STORAGE_KEY);
    if (!raw) return DEFAULT_OPERATOR_SETTINGS;
    return normalizeSettings(JSON.parse(raw));
  } catch {
    return DEFAULT_OPERATOR_SETTINGS;
  }
}

export function getOperatorApiBaseUrl(): string {
  return readOperatorSettings().apiBaseUrl.trim();
}

export function getOperatorWsBaseUrl(): string {
  return readOperatorSettings().wsBaseUrl.trim();
}

export function writeOperatorSettings(settings: OperatorSettings) {
  localStorage.setItem(OPERATOR_SETTINGS_STORAGE_KEY, JSON.stringify(normalizeSettings(settings)));
}

export function clearOperatorSettings() {
  localStorage.removeItem(OPERATOR_SETTINGS_STORAGE_KEY);
}

export function applyOperatorRuntimeSettings(settings: OperatorSettings) {
  if (typeof window === 'undefined') return;

  window.RUNTIME_CONFIG = window.RUNTIME_CONFIG || {};

  const apiBaseUrl = settings.apiBaseUrl.trim();
  const wsBaseUrl = settings.wsBaseUrl.trim();

  if (apiBaseUrl) {
    window.RUNTIME_CONFIG.API_BASE_URL = apiBaseUrl;
  } else {
    delete window.RUNTIME_CONFIG.API_BASE_URL;
  }

  if (wsBaseUrl) {
    window.RUNTIME_CONFIG.WS_BASE_URL = wsBaseUrl;
  } else {
    delete window.RUNTIME_CONFIG.WS_BASE_URL;
  }
}

export function clearOperatorRuntimeSettings() {
  if (typeof window === 'undefined' || !window.RUNTIME_CONFIG) return;
  delete window.RUNTIME_CONFIG.API_BASE_URL;
  delete window.RUNTIME_CONFIG.WS_BASE_URL;
}

export function buildOperatorRuntimeConfig(settings: OperatorSettings) {
  const normalized = normalizeSettings(settings);
  // 관리자 키는 비밀값이므로 화면 표시/내보내기용 런타임 설정에는 포함하지 않는다.
  // (저장은 localStorage operatorSettings에만 유지되고, 주입은 RUNTIME_CONFIG.ADMIN_API_KEY로 별도 처리)
  const operatorWithoutSecret: Omit<OperatorSettings, 'adminApiKey'> = {
    apiBaseUrl: normalized.apiBaseUrl,
    wsBaseUrl: normalized.wsBaseUrl,
    defaultModel: normalized.defaultModel,
    ragProfile: normalized.ragProfile,
    chunkSize: normalized.chunkSize,
    chunkOverlap: normalized.chunkOverlap,
    enableStreaming: normalized.enableStreaming,
    enableDocumentUpload: normalized.enableDocumentUpload,
    enablePhoneMasking: normalized.enablePhoneMasking,
    systemNotice: normalized.systemNotice,
  };

  return {
    operator: operatorWithoutSecret,
    features: {
      ...DEFAULT_FEATURES,
      chatbot: {
        ...DEFAULT_FEATURES.chatbot,
        streaming: normalized.enableStreaming,
      },
      documentManagement: {
        ...DEFAULT_FEATURES.documentManagement,
        upload: normalized.enableDocumentUpload,
      },
      privacy: {
        ...DEFAULT_FEATURES.privacy,
        maskPhoneNumbers: normalized.enablePhoneMasking,
      },
    },
  };
}
