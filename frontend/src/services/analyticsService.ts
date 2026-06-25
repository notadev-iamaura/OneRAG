import { getOperatorApiBaseUrl } from '../config/operatorSettings';
import { createClientId } from '../utils/clientId';
import { logger } from '../utils/logger';

const VISITOR_ID_STORAGE_KEY = 'onerag_visitor_id';

export function getAnalyticsVisitorId(): string {
  if (typeof window === 'undefined') {
    return 'visitor-ssr';
  }
  const existing = localStorage.getItem(VISITOR_ID_STORAGE_KEY);
  if (existing) {
    return existing;
  }
  const visitorId = createClientId('visitor');
  localStorage.setItem(VISITOR_ID_STORAGE_KEY, visitorId);
  return visitorId;
}
function getAnalyticsAPIBaseURL(): string {
  const operatorApiUrl = getOperatorApiBaseUrl();
  if (operatorApiUrl) {
    return operatorApiUrl;
  }
  if (typeof window !== 'undefined' && window.RUNTIME_CONFIG?.API_BASE_URL !== undefined) {
    return window.RUNTIME_CONFIG.API_BASE_URL || '';
  }
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL;
  }
  if (import.meta.env.DEV) {
    return import.meta.env.VITE_DEV_API_BASE_URL || 'http://localhost:8000';
  }
  return '';
}

export async function trackAnalyticsEvent(
  eventType: string,
  metadata: Record<string, string> = {},
): Promise<void> {
  if (typeof window === 'undefined') {
    return;
  }
  const payload = {
    eventType,
    visitorId: getAnalyticsVisitorId(),
    sessionId: localStorage.getItem('chatSessionId') || undefined,
    channel: window.location.pathname.startsWith('/embed/') ? 'embed' : 'web',
    route: window.location.pathname,
    referrerOrigin: document.referrer || window.location.origin,
    metadata,
  };

  try {
    await fetch(`${getAnalyticsAPIBaseURL()}/api/analytics/event`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    });
  } catch (error) {
    logger.debug('analytics event skipped', error);
  }
}
