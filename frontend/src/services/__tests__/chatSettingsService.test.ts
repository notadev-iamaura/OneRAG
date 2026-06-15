/**
 * chatSettingsService 테스트 (서버 결선 + 폴백 + 관리자 키)
 *
 * 검증 범위:
 * - fetchAll: 서버 응답 병합, 서버 미응답 시 캐시/기본값 graceful 폴백
 * - saveSettings/resetSettings: X-API-Key 헤더, 관리자 키 부재 시 MissingAdminKeyError
 * - validateSettings: 클라이언트 사전 검증
 *
 * 외부 의존성은 모두 mock 한다(실제 네트워크/콘솔/운영 설정 차단).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// 콘솔 노이즈 차단.
vi.mock('../../utils/logger', () => ({
  logger: {
    log: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

// 고정 base URL을 반환해 테스트를 결정적으로 만든다.
vi.mock('../adminService', () => ({
  getAdminAPIBaseURL: vi.fn(() => 'http://test-host'),
}));

// 운영 설정의 관리자 키를 테스트별로 제어한다.
const mockReadOperatorSettings = vi.fn(() => ({ adminApiKey: '' }));
vi.mock('../../config/operatorSettings', () => ({
  readOperatorSettings: () => mockReadOperatorSettings(),
}));

import {
  chatSettingsService,
  MissingAdminKeyError,
  ChatSettingsValidationError,
} from '../chatSettingsService';

// 실제 동작하는 localStorage mock (전역 setup의 no-op stub을 대체).
class MemoryStorage {
  private store = new Map<string, string>();
  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  clear(): void {
    this.store.clear();
  }
  get length(): number {
    return this.store.size;
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }
}

// 서버 응답(ok)을 만드는 헬퍼.
const okResponse = (body: unknown): Response =>
  ({
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }) as unknown as Response;

// 서버 에러 응답을 만드는 헬퍼.
const errorResponse = (status: number, text = 'error'): Response =>
  ({
    ok: false,
    status,
    json: async () => ({}),
    text: async () => text,
  }) as unknown as Response;

describe('chatSettingsService', () => {
  beforeEach(() => {
    // 매 테스트마다 깨끗한 localStorage와 메모리 캐시로 시작한다.
    Object.defineProperty(window, 'localStorage', {
      value: new MemoryStorage(),
      writable: true,
      configurable: true,
    });
    // 서비스 내부 메모리 캐시를 비운다(싱글톤이므로 캐시 키를 초기화).
    window.localStorage.clear();
    // @ts-expect-error - 테스트 격리를 위해 내부 메모리 캐시를 강제 초기화한다.
    chatSettingsService.memoryCache = null;
    mockReadOperatorSettings.mockReturnValue({ adminApiKey: '' });
    if (window.RUNTIME_CONFIG) {
      delete window.RUNTIME_CONFIG.ADMIN_API_KEY;
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe('fetchAll', () => {
    it('서버 응답을 기본값과 병합해 전 로케일 설정을 반환한다', async () => {
      const serverBody = {
        ko: { mainMessage: '서버 메인', subMessage: '서버 보조', suggestions: ['서버질문1'] },
        // en은 서버가 내려주지 않음 → 기본값으로 보강되어야 한다.
      };
      const fetchMock = vi.fn(async () => okResponse(serverBody));
      vi.stubGlobal('fetch', fetchMock);

      const all = await chatSettingsService.fetchAll();

      // 호출 URL 검증
      expect(fetchMock).toHaveBeenCalledWith(
        'http://test-host/api/chat-empty-state',
        expect.objectContaining({ headers: { 'Content-Type': 'application/json' } })
      );
      // ko는 서버값, en은 기본값(보강)
      expect(all.ko.mainMessage).toBe('서버 메인');
      expect(all.ko.suggestions).toEqual(['서버질문1']);
      expect(all.en.mainMessage).toBe('How can I help you?');
    });

    it('서버 미응답(네트워크 실패) 시 기본값으로 graceful 폴백한다', async () => {
      const fetchMock = vi.fn(async () => {
        throw new Error('network down');
      });
      vi.stubGlobal('fetch', fetchMock);

      const all = await chatSettingsService.fetchAll();

      // 한국어 기본값으로 폴백
      expect(all.ko.mainMessage).toBe('무엇을 도와드릴까요?');
      expect(all.en.mainMessage).toBe('How can I help you?');
    });

    it('HTTP 에러(500) 시에도 캐시/기본값으로 폴백한다', async () => {
      const fetchMock = vi.fn(async () => errorResponse(500));
      vi.stubGlobal('fetch', fetchMock);

      const all = await chatSettingsService.fetchAll();
      expect(all.ko.mainMessage).toBe('무엇을 도와드릴까요?');
    });

    it('성공 응답을 localStorage 캐시에 기록해 이후 동기 조회에 사용한다', async () => {
      const serverBody = {
        ko: { mainMessage: '캐시될 메인', subMessage: '캐시 보조', suggestions: ['q1'] },
        en: { mainMessage: 'Cached main', subMessage: 'Cached sub', suggestions: ['q1'] },
      };
      vi.stubGlobal('fetch', vi.fn(async () => okResponse(serverBody)));

      await chatSettingsService.fetchAll();

      // localStorage에 캐시가 기록되어야 한다.
      const cached = window.localStorage.getItem('chatEmptyStateSettings:v2');
      expect(cached).toBeTruthy();
      // 동기 조회도 캐시값을 반환한다.
      expect(chatSettingsService.getSettings('ko').mainMessage).toBe('캐시될 메인');
    });
  });

  describe('관리자 키 처리', () => {
    it('관리자 키가 없으면 saveSettings는 MissingAdminKeyError를 던진다', async () => {
      const fetchMock = vi.fn();
      vi.stubGlobal('fetch', fetchMock);

      await expect(
        chatSettingsService.saveSettings('ko', {
          mainMessage: '유효한 메인',
          subMessage: '유효한 보조',
          suggestions: ['질문1'],
        })
      ).rejects.toBeInstanceOf(MissingAdminKeyError);
      // 키가 없으면 네트워크 호출 자체가 일어나지 않아야 한다.
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('운영 설정의 adminApiKey를 X-API-Key 헤더로 PUT 호출한다', async () => {
      mockReadOperatorSettings.mockReturnValue({ adminApiKey: 'secret-key' });
      const saved = { mainMessage: '저장된 메인', subMessage: '저장된 보조', suggestions: ['q1'] };
      const fetchMock = vi.fn(async () => okResponse(saved));
      vi.stubGlobal('fetch', fetchMock);

      const result = await chatSettingsService.saveSettings('ko', {
        mainMessage: '저장할 메인',
        subMessage: '저장할 보조',
        suggestions: ['질문1'],
      });

      expect(fetchMock).toHaveBeenCalledWith(
        'http://test-host/api/admin/chat-empty-state/ko',
        expect.objectContaining({
          method: 'PUT',
          headers: expect.objectContaining({ 'X-API-Key': 'secret-key' }),
        })
      );
      expect(result.mainMessage).toBe('저장된 메인');
    });

    it('RUNTIME_CONFIG.ADMIN_API_KEY 주입 시에도 키를 사용한다', async () => {
      window.RUNTIME_CONFIG = { ...(window.RUNTIME_CONFIG || {}), ADMIN_API_KEY: 'injected-key' };
      const def = { mainMessage: '기본 메인', subMessage: '기본 보조', suggestions: ['q1'] };
      const fetchMock = vi.fn(async () => okResponse(def));
      vi.stubGlobal('fetch', fetchMock);

      await chatSettingsService.resetSettings('en');

      expect(fetchMock).toHaveBeenCalledWith(
        'http://test-host/api/admin/chat-empty-state/en',
        expect.objectContaining({
          method: 'DELETE',
          headers: expect.objectContaining({ 'X-API-Key': 'injected-key' }),
        })
      );
    });

    it('hasAdminKey는 키 유무를 정확히 반영한다', () => {
      expect(chatSettingsService.hasAdminKey()).toBe(false);
      mockReadOperatorSettings.mockReturnValue({ adminApiKey: 'k' });
      expect(chatSettingsService.hasAdminKey()).toBe(true);
    });
  });

  describe('saveSettings 검증/에러', () => {
    it('클라이언트 검증 실패 시 ChatSettingsValidationError를 던지고 네트워크 호출하지 않는다', async () => {
      mockReadOperatorSettings.mockReturnValue({ adminApiKey: 'secret-key' });
      const fetchMock = vi.fn();
      vi.stubGlobal('fetch', fetchMock);

      await expect(
        chatSettingsService.saveSettings('ko', {
          mainMessage: '', // 비어 있어 검증 실패
          subMessage: '보조',
          suggestions: ['질문1'],
        })
      ).rejects.toBeInstanceOf(ChatSettingsValidationError);
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('서버 4xx/5xx 응답 시 HTTP 에러를 전파한다', async () => {
      mockReadOperatorSettings.mockReturnValue({ adminApiKey: 'secret-key' });
      vi.stubGlobal('fetch', vi.fn(async () => errorResponse(503, '저장 불가')));

      await expect(
        chatSettingsService.saveSettings('ko', {
          mainMessage: '메인',
          subMessage: '보조',
          suggestions: ['질문1'],
        })
      ).rejects.toThrow(/HTTP 503/);
    });
  });

  describe('validateSettings', () => {
    it('유효한 설정은 빈 배열을 반환한다', () => {
      expect(
        chatSettingsService.validateSettings({
          mainMessage: '안녕하세요',
          subMessage: '도움이 필요하신가요',
          suggestions: ['질문1', '질문2'],
        })
      ).toEqual([]);
    });

    it('중복 추천 질문을 검출한다', () => {
      const errors = chatSettingsService.validateSettings({
        mainMessage: '메인',
        subMessage: '보조',
        suggestions: ['같은질문', '같은질문'],
      });
      expect(errors).toContain('중복된 추천 질문이 있습니다');
    });

    it('100자 초과 메인 메시지를 검출한다', () => {
      const errors = chatSettingsService.validateSettings({
        mainMessage: 'a'.repeat(101),
        subMessage: '보조',
        suggestions: ['질문1'],
      });
      expect(errors.some((e) => e.includes('100자'))).toBe(true);
    });
  });
});
