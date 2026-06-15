import { afterEach, describe, expect, it, vi } from 'vitest';

// 로거는 콘솔 노이즈를 막기 위해 mock 처리한다.
vi.mock('../../utils/logger', () => ({
  logger: {
    log: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

// operatorSettings는 운영자 오버라이드가 없는 기본 상태(빈 문자열)를 가정한다.
vi.mock('../../config/operatorSettings', () => ({
  getOperatorApiBaseUrl: vi.fn(() => ''),
  getOperatorWsBaseUrl: vi.fn(() => ''),
}));

describe('adminService 런타임 URL 계약', () => {
  const originalLocation = window.location;

  afterEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
    Object.defineProperty(window, 'location', {
      value: originalLocation,
      writable: true,
      configurable: true,
    });
    delete window.RUNTIME_CONFIG?.API_BASE_URL;
    delete window.RUNTIME_CONFIG?.WS_BASE_URL;
  });

  it('RUNTIME_CONFIG의 API_BASE_URL이 빈 문자열이면 same-origin(빈 문자열)을 사용한다', async () => {
    window.RUNTIME_CONFIG = {
      ...(window.RUNTIME_CONFIG || {}),
      API_BASE_URL: '',
    };

    const { getAdminAPIBaseURL } = await import('../adminService');

    expect(getAdminAPIBaseURL()).toBe('');
  });

  it('RUNTIME_CONFIG의 WS_BASE_URL이 빈 문자열이면 현재 페이지 origin 기반 wss를 사용한다', async () => {
    window.RUNTIME_CONFIG = {
      ...(window.RUNTIME_CONFIG || {}),
      WS_BASE_URL: '',
    };
    Object.defineProperty(window, 'location', {
      value: new URL('https://customer.example.com/admin'),
      writable: true,
      configurable: true,
    });

    const { getAdminWSBaseURL } = await import('../adminService');

    expect(getAdminWSBaseURL()).toBe('wss://customer.example.com');
  });

  it('RUNTIME_CONFIG의 WS_BASE_URL 값이 설정되어 있으면 그대로 사용한다', async () => {
    window.RUNTIME_CONFIG = {
      ...(window.RUNTIME_CONFIG || {}),
      WS_BASE_URL: 'wss://my-backend.internal',
    };

    const { getAdminWSBaseURL } = await import('../adminService');

    expect(getAdminWSBaseURL()).toBe('wss://my-backend.internal');
  });

  it('하드코딩된 외부 Railway 인스턴스 폴백을 더 이상 사용하지 않는다', async () => {
    // RUNTIME_CONFIG 미설정 + http origin → ws same-origin이어야 한다.
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:3000/admin'),
      writable: true,
      configurable: true,
    });

    const { getAdminWSBaseURL } = await import('../adminService');
    const wsUrl = getAdminWSBaseURL();

    // DEV 환경에서는 ws://localhost:8000, 그 외에는 same-origin. 어느 경우든 외부 Railway 호스트는 금지.
    expect(wsUrl).not.toContain('railway.app');
    expect(wsUrl).not.toContain('simple-rag-production');
  });

  it('downloadLogs는 same-origin admin URL로 호출한다', async () => {
    window.RUNTIME_CONFIG = {
      ...(window.RUNTIME_CONFIG || {}),
      API_BASE_URL: '',
    };

    const blob = new Blob(['logs'], { type: 'text/plain' });
    const fetchMock = vi.fn().mockResolvedValue(new Response(blob, { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    // jsdom에 createObjectURL/revokeObjectURL이 없으므로 보강한다.
    const urlMock = {
      createObjectURL: vi.fn(() => 'blob:mock'),
      revokeObjectURL: vi.fn(),
    };
    vi.stubGlobal('URL', Object.assign(URL, urlMock));

    const { AdminService } = await import('../adminService');
    const service = new AdminService();
    await service.downloadLogs();

    expect(fetchMock).toHaveBeenCalledWith('/api/admin/logs/download');
  });
});
