/**
 * 로깅 유틸리티
 * 개발 환경에서만 콘솔 로그를 출력하고, 프로덕션에서는 무시합니다.
 * 민감 정보는 자동으로 마스킹됩니다.
 */

const isDev = import.meta.env.DEV;

/**
 * 민감 정보를 마스킹하는 함수
 */
const maskSensitiveData = (data: unknown): unknown => {
  if (typeof data !== 'object' || data === null) {
    return data;
  }

  if (Array.isArray(data)) {
    return data.map(maskSensitiveData);
  }

  const masked: Record<string, unknown> = {};
    const sensitiveKeys = [
      'sessionId',
      'session_id',
      'session-id',
      'x-session-id',
      'chatSessionId',
      'authorization',
      'password',
      'token',
      'jwt',
      'apiKey',
      'api_key',
      'secret',
      'cookie',
      'csrf',
      'xsrf',
      'accessCode',
      'access_code',
    ];

  for (const [key, value] of Object.entries(data)) {
    if (sensitiveKeys.some(sk => key.toLowerCase().includes(sk.toLowerCase()))) {
      masked[key] = '***masked***';
    } else if (typeof value === 'object' && value !== null) {
      masked[key] = maskSensitiveData(value);
    } else {
      masked[key] = value;
    }
  }

  return masked;
};

export const logger = {
  /**
   * 일반 로그 (개발 환경에서만 출력, 민감 정보 마스킹)
   */
  log: (...args: unknown[]) => {
    if (isDev) {
      console.log(...args.map(maskSensitiveData));
    }
  },

  /**
   * 정보 로그 (개발 환경에서만 출력, 민감 정보 마스킹)
   */
  info: (...args: unknown[]) => {
    if (isDev) {
      console.info(...args.map(maskSensitiveData));
    }
  },

  /**
   * 경고 로그 (항상 출력, 민감 정보 마스킹)
   */
  warn: (...args: unknown[]) => {
    console.warn(...args.map(maskSensitiveData));
  },

  /**
   * 에러 로그 (항상 출력, 민감 정보 마스킹)
   */
  error: (...args: unknown[]) => {
    console.error(...args.map(maskSensitiveData));
  },

  /**
   * 디버그 로그 (개발 환경에서만 출력, 민감 정보 마스킹)
   */
  debug: (...args: unknown[]) => {
    if (isDev) {
      console.debug(...args.map(maskSensitiveData));
    }
  },

  /**
   * 그룹 시작 (개발 환경에서만 출력)
   */
  group: (label: string) => {
    if (isDev) {
      console.group(label);
    }
  },

  /**
   * 그룹 종료 (개발 환경에서만 출력)
   */
  groupEnd: () => {
    if (isDev) {
      console.groupEnd();
    }
  },
};

export default logger;
