/**
 * 클라이언트 측 Rate Limiting
 * API 호출 빈도를 제한하여 서버 부하 감소 및 DoS 방지
 */
import { logger } from './logger';

export interface RateLimiterConfig {
  maxRequests: number; // 최대 요청 수
  windowMs: number; // 시간 윈도우 (밀리초)
  keyPrefix?: string; // localStorage 키 접두사
}

interface RequestRecord {
  timestamp: number;
  count: number;
}

/**
 * Token Bucket 알고리즘 기반 Rate Limiter
 */
export class RateLimiter {
  private config: RateLimiterConfig;

  constructor(config: RateLimiterConfig) {
    this.config = {
      keyPrefix: 'rate_limit',
      ...config,
    };
  }

  /**
   * 요청 허용 여부 확인
   * @param key - Rate limit 키 (예: 'api_call', 'chat_message')
   * @returns 요청 허용 여부
   */
  async checkLimit(key: string): Promise<boolean> {
    const now = Date.now();
    const record = this.getRecord(key);

    // 시간 윈도우가 지났으면 리셋
    if (now - record.timestamp >= this.config.windowMs) {
      this.resetRecord(key, now);
      return true;
    }

    // 요청 수 확인
    if (record.count >= this.config.maxRequests) {
      const remainingTime = this.config.windowMs - (now - record.timestamp);
      logger.warn(`⚠️ Rate limit 초과: ${key}`, {
        current: record.count,
        max: this.config.maxRequests,
        remainingMs: remainingTime,
      });
      return false;
    }

    // 요청 수 증가
    this.incrementRecord(key, record);
    return true;
  }

  /**
   * 요청 레코드 조회
   */
  private getRecord(key: string): RequestRecord {
    try {
      const stored = localStorage.getItem(this.getStorageKey(key));
      if (stored) {
        return JSON.parse(stored);
      }
    } catch (error) {
      logger.error('⚠️ Rate limit 레코드 조회 실패:', error);
    }

    return {
      timestamp: Date.now(),
      count: 0,
    };
  }

  /**
   * 요청 레코드 초기화
   */
  private resetRecord(key: string, timestamp: number): void {
    const record: RequestRecord = {
      timestamp,
      count: 1,
    };

    try {
      localStorage.setItem(this.getStorageKey(key), JSON.stringify(record));
    } catch (error) {
      logger.error('⚠️ Rate limit 레코드 저장 실패:', error);
    }
  }

  /**
   * 요청 수 증가
   */
  private incrementRecord(key: string, record: RequestRecord): void {
    record.count += 1;

    try {
      localStorage.setItem(this.getStorageKey(key), JSON.stringify(record));
    } catch (error) {
      logger.error('⚠️ Rate limit 레코드 업데이트 실패:', error);
    }
  }

  /**
   * 스토리지 키 생성
   */
  private getStorageKey(key: string): string {
    return `${this.config.keyPrefix}_${key}`;
  }

  /**
   * 남은 시간 조회 (밀리초)
   */
  getRemainingTime(key: string): number {
    const record = this.getRecord(key);
    const now = Date.now();
    const elapsed = now - record.timestamp;

    if (elapsed >= this.config.windowMs) {
      return 0;
    }

    return this.config.windowMs - elapsed;
  }

  /**
   * 남은 요청 수 조회
   */
  getRemainingRequests(key: string): number {
    const record = this.getRecord(key);
    const now = Date.now();

    // 시간 윈도우가 지났으면 최대값 반환
    if (now - record.timestamp >= this.config.windowMs) {
      return this.config.maxRequests;
    }

    return Math.max(0, this.config.maxRequests - record.count);
  }

  /**
   * 레코드 수동 리셋
   */
  reset(key: string): void {
    try {
      localStorage.removeItem(this.getStorageKey(key));
      logger.info(`✅ Rate limit 리셋: ${key}`);
    } catch (error) {
      logger.error('⚠️ Rate limit 리셋 실패:', error);
    }
  }

  /**
   * 모든 레코드 정리
   */
  clearAll(): void {
    try {
      const keys = Object.keys(localStorage);
      const prefix = this.config.keyPrefix || 'rate_limit';

      keys.forEach((key) => {
        if (key.startsWith(prefix)) {
          localStorage.removeItem(key);
        }
      });

      logger.info('✅ 모든 Rate limit 레코드 정리 완료');
    } catch (error) {
      logger.error('⚠️ Rate limit 정리 실패:', error);
    }
  }
}

/**
 * 전역 Rate Limiter 인스턴스
 */
export const chatRateLimiter = new RateLimiter({
  maxRequests: 10, // 10개 요청
  windowMs: 60000, // 1분
  keyPrefix: 'chat_rate_limit',
});

export const apiRateLimiter = new RateLimiter({
  maxRequests: 50, // 50개 요청
  windowMs: 60000, // 1분
  keyPrefix: 'api_rate_limit',
});

export const uploadRateLimiter = new RateLimiter({
  maxRequests: 5, // 5개 업로드
  windowMs: 300000, // 5분
  keyPrefix: 'upload_rate_limit',
});

/**
 * Rate Limiter HOF (Higher-Order Function)
 * 함수를 래핑하여 자동으로 rate limiting 적용
 */
export function withRateLimit<T extends (...args: unknown[]) => Promise<unknown>>(
  fn: T,
  limiter: RateLimiter,
  key: string
): T {
  return (async (...args: unknown[]) => {
    const allowed = await limiter.checkLimit(key);

    if (!allowed) {
      const remainingTime = limiter.getRemainingTime(key);
      throw new Error(
        `Rate limit exceeded. Please wait ${Math.ceil(remainingTime / 1000)} seconds.`
      );
    }

    return fn(...args);
  }) as T;
}
