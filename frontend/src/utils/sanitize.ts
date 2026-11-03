/**
 * XSS 방어를 위한 입력 sanitization 유틸리티
 */
import DOMPurify, { type Config as DOMPurifyConfig } from 'dompurify';

/**
 * 사용자 입력을 sanitize하여 XSS 공격 방어
 * @param dirty - Sanitize할 HTML 문자열
 * @param options - DOMPurify 옵션
 * @returns Sanitized HTML 문자열
 */
export const sanitizeHTML = (dirty: string, options?: DOMPurifyConfig): string => {
  return DOMPurify.sanitize(dirty, {
    ALLOWED_TAGS: ['b', 'i', 'em', 'strong', 'a', 'p', 'br', 'ul', 'ol', 'li', 'code', 'pre'],
    ALLOWED_ATTR: ['href', 'title', 'target'],
    ...options,
  });
};

/**
 * 일반 텍스트 입력을 sanitize (HTML 태그 모두 제거)
 * @param text - Sanitize할 텍스트
 * @returns Sanitized 텍스트
 */
export const sanitizeText = (text: string): string => {
  const cleaned = DOMPurify.sanitize(text, {
    ALLOWED_TAGS: [],
    RETURN_DOM: true
  });
  return cleaned.textContent || '';
};

/**
 * URL을 검증하고 안전한 URL만 허용
 * @param url - 검증할 URL
 * @returns 안전한 URL 또는 빈 문자열
 */
export const sanitizeURL = (url: string): string => {
  try {
    const parsed = new URL(url);
    // HTTP/HTTPS만 허용
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return url;
    }
    return '';
  } catch {
    return '';
  }
};
