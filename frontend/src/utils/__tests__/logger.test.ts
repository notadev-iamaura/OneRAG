import { afterEach, describe, expect, it, vi } from 'vitest';
import { logger } from '../logger';

describe('logger', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('인증 헤더, CSRF, 쿠키 값을 마스킹해야 함', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    logger.error('auth failure', {
      Authorization: 'Bearer access-token-secret',
      cookie: 'session_id=session-secret',
      nested: {
        'X-XSRF-TOKEN': 'csrf-token-secret',
        'X-Session-Id': 'session-id-secret',
        keep: 'visible',
      },
    });

    expect(errorSpy).toHaveBeenCalledWith('auth failure', {
      Authorization: '***masked***',
      cookie: '***masked***',
      nested: {
        'X-XSRF-TOKEN': '***masked***',
        'X-Session-Id': '***masked***',
        keep: 'visible',
      },
    });
  });
});
