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

  return {
    operator: normalized,
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
