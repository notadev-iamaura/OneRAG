import { readOperatorSettings } from '../config/operatorSettings';

const UPLOAD_TOKEN_STORAGE_KEY = 'chatUploadToken';
const UPLOAD_TOKEN_BY_SESSION_PREFIX = 'chatUploadToken:';
const UPLOAD_TOKEN_EXPIRY_SKEW_SECONDS = 5;

interface UploadAccessTokenRecord {
  sessionId: string;
  token: string;
  expiresAt?: number | null;
  ttlSeconds?: number | null;
}

export interface UploadAccessTokenInput {
  sessionId: string;
  token?: string | null;
  expiresAt?: number | null;
  ttlSeconds?: number | null;
}

/** 관리자 API 키 미설정 시 던지는 에러 (호출 측에서 안내 메시지 표시). */
export class MissingAdminKeyError extends Error {
  constructor() {
    super('admin api key is not configured');
    this.name = 'MissingAdminKeyError';
  }
}

function canUseBrowserStorage(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

function readStorageValue(key: string): string | null {
  if (!canUseBrowserStorage()) return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorageValue(key: string, value: string): void {
  if (!canUseBrowserStorage()) return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage may be unavailable in private browsing or embedded contexts.
  }
}

function removeStorageValue(key: string): void {
  if (!canUseBrowserStorage()) return;
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Ignore storage cleanup failures.
  }
}

function parseUploadTokenRecord(raw: string | null): UploadAccessTokenRecord | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<UploadAccessTokenRecord>;
    if (
      typeof parsed.sessionId === 'string'
      && parsed.sessionId.length > 0
      && typeof parsed.token === 'string'
      && parsed.token.length > 0
    ) {
      return {
        sessionId: parsed.sessionId,
        token: parsed.token,
        expiresAt: typeof parsed.expiresAt === 'number' ? parsed.expiresAt : null,
        ttlSeconds: typeof parsed.ttlSeconds === 'number' ? parsed.ttlSeconds : null,
      };
    }
  } catch {
    if (raw.length > 0) {
      const sessionId = readStorageValue('chatSessionId') || readStorageValue('sessionId');
      return sessionId ? { sessionId, token: raw } : null;
    }
  }
  return null;
}

function isExpired(record: UploadAccessTokenRecord): boolean {
  if (!record.expiresAt) return false;
  return record.expiresAt <= Math.floor(Date.now() / 1000) + UPLOAD_TOKEN_EXPIRY_SKEW_SECONDS;
}

function readUploadTokenRecord(sessionId: string): UploadAccessTokenRecord | null {
  const sessionRecord = parseUploadTokenRecord(
    readStorageValue(`${UPLOAD_TOKEN_BY_SESSION_PREFIX}${sessionId}`)
  );
  if (sessionRecord?.sessionId === sessionId) {
    return sessionRecord;
  }

  const latestRecord = parseUploadTokenRecord(readStorageValue(UPLOAD_TOKEN_STORAGE_KEY));
  if (latestRecord?.sessionId === sessionId) {
    return latestRecord;
  }
  return null;
}

export function persistUploadAccessToken({
  sessionId,
  token,
  expiresAt,
  ttlSeconds,
}: UploadAccessTokenInput): void {
  if (!sessionId || !token) {
    clearUploadAccessToken(sessionId);
    return;
  }

  const record: UploadAccessTokenRecord = {
    sessionId,
    token,
    expiresAt: expiresAt ?? null,
    ttlSeconds: ttlSeconds ?? null,
  };
  const serialized = JSON.stringify(record);
  writeStorageValue(`${UPLOAD_TOKEN_BY_SESSION_PREFIX}${sessionId}`, serialized);
  writeStorageValue(UPLOAD_TOKEN_STORAGE_KEY, serialized);
}

export function clearUploadAccessToken(sessionId?: string | null): void {
  if (sessionId) {
    removeStorageValue(`${UPLOAD_TOKEN_BY_SESSION_PREFIX}${sessionId}`);
    const latestRecord = parseUploadTokenRecord(readStorageValue(UPLOAD_TOKEN_STORAGE_KEY));
    if (latestRecord?.sessionId === sessionId) {
      removeStorageValue(UPLOAD_TOKEN_STORAGE_KEY);
    }
    return;
  }
  removeStorageValue(UPLOAD_TOKEN_STORAGE_KEY);
}

export function getUploadAccessHeaders(sessionId?: string | null): Record<string, string> {
  const effectiveSessionId = (
    sessionId
    || readStorageValue('chatSessionId')
    || readStorageValue('sessionId')
    || ''
  ).trim();
  if (!effectiveSessionId) return {};

  const record = readUploadTokenRecord(effectiveSessionId);
  if (!record) return {};
  if (isExpired(record)) {
    clearUploadAccessToken(effectiveSessionId);
    return {};
  }

  return {
    'X-OneRAG-Upload-Token': record.token,
    'X-OneRAG-Session-Id': effectiveSessionId,
  };
}

export function getAdminApiKey(): string {
  const fromSettings = (readOperatorSettings().adminApiKey || '').trim();
  if (fromSettings) return fromSettings;
  if (typeof window !== 'undefined') {
    return (window.RUNTIME_CONFIG?.ADMIN_API_KEY || '').trim();
  }
  return '';
}

export function hasAdminApiKey(): boolean {
  return Boolean(getAdminApiKey());
}

export function getOptionalAdminAuthHeaders(): Record<string, string> {
  const key = getAdminApiKey();
  return key ? { 'X-API-Key': key } : {};
}

export function getRequiredAdminAuthHeaders(
  options: { includeContentType?: boolean } = {},
): Record<string, string> {
  const key = getAdminApiKey();
  if (!key) {
    throw new MissingAdminKeyError();
  }
  return {
    ...(options.includeContentType === false ? {} : { 'Content-Type': 'application/json' }),
    'X-API-Key': key,
  };
}

function requestPath(url?: string): string {
  if (!url) return '';
  try {
    const base = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';
    return new URL(url, base).pathname;
  } catch {
    return url.split('?')[0] || '';
  }
}

export function isUploadApiRequest(url?: string): boolean {
  return requestPath(url).startsWith('/api/upload');
}

export function isAdminApiRequest(url?: string): boolean {
  return requestPath(url).startsWith('/api/admin');
}

export function isAdminProtectedApiRequest(url?: string, method?: string): boolean {
  const path = requestPath(url);
  const normalizedMethod = (method || 'get').toLowerCase();
  if (path.startsWith('/api/admin')) return true;
  if (path === '/api/documents/all') return normalizedMethod === 'delete';
  if (path === '/api/prompts' || path === '/api/prompts/' || path === '/api/prompts/import') {
    return ['post', 'put', 'patch', 'delete'].includes(normalizedMethod);
  }
  return path.startsWith('/api/prompts/')
    && ['put', 'patch', 'delete'].includes(normalizedMethod);
}

export function buildAdminWebSocketUrl(baseUrl: string): string {
  const key = getAdminApiKey();
  if (!key) {
    throw new MissingAdminKeyError();
  }
  const url = new URL('/api/admin/ws', baseUrl);
  url.searchParams.set('api_key', key);
  return url.toString();
}
