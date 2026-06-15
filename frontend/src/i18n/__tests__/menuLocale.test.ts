// i18n 레이어 단위 테스트.
// 카탈로그 완전성, 로케일별 라벨, resolveMenuLocale 폴백,
// localStorage 영속화, CustomEvent 통지(같은 탭 동기화)를 검증한다.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MENU_LOCALES, menuMessages } from '../menuMessages';
import {
  DEFAULT_MENU_LOCALE,
  MENU_LOCALE_CHANGE_EVENT,
  MENU_LOCALE_STORAGE_KEY,
  getStoredMenuLocale,
  resolveMenuLocale,
  setStoredMenuLocale,
} from '../useMenuLocale';

describe('menu locale messages', () => {
  it('모든 지원 로케일에 대해 완전한 메시지 집합을 정의한다', () => {
    for (const locale of MENU_LOCALES) {
      const messages = menuMessages[locale];

      expect(messages.language.label).toBeTruthy();
      expect(messages.language.select).toBeTruthy();
      expect(messages.chat.header.title).toBeTruthy();
      expect(messages.chat.input.placeholder).toBeTruthy();
      expect(messages.chat.message.preparingResponse).toBeTruthy();
      expect(messages.chunkDetail.modalTitle).toBeTruthy();
      expect(messages.pdfViewer.heading).toBeTruthy();
      expect(messages.pdfViewer.zoomIn).toBeTruthy();
      expect(messages.pdfViewer.loadFailed).toBeTruthy();
      expect(messages.common.notAvailable).toBeTruthy();
    }
  });

  it('각 로케일이 자국어 라벨을 렌더링하도록 구분된다', () => {
    expect(menuMessages.ko.chat.input.send).toBe('보내기');
    expect(menuMessages.en.chat.input.send).toBe('Send');
    expect(menuMessages.ko.chunkDetail.close).toBe('닫기');
    expect(menuMessages.en.chunkDetail.close).toBe('Close');
  });
});

describe('menu locale storage', () => {
  const storage: Record<string, string> = {};

  beforeEach(() => {
    Object.keys(storage).forEach((key) => {
      delete storage[key];
    });
    vi.spyOn(window.localStorage, 'getItem').mockImplementation((key: string) => storage[key] ?? null);
    vi.spyOn(window.localStorage, 'setItem').mockImplementation((key: string, value: string) => {
      storage[key] = value;
    });
    vi.spyOn(window.localStorage, 'clear').mockImplementation(() => {
      Object.keys(storage).forEach((key) => {
        delete storage[key];
      });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('기본 로케일은 한국어(ko)다', () => {
    expect(DEFAULT_MENU_LOCALE).toBe('ko');
  });

  it('지원되지 않는 로케일 값은 기본 로케일로 폴백한다', () => {
    expect(resolveMenuLocale('ko')).toBe('ko');
    expect(resolveMenuLocale('en')).toBe('en');
    expect(resolveMenuLocale('ja')).toBe(DEFAULT_MENU_LOCALE);
    expect(resolveMenuLocale('fr')).toBe(DEFAULT_MENU_LOCALE);
    expect(resolveMenuLocale(undefined)).toBe(DEFAULT_MENU_LOCALE);
    expect(resolveMenuLocale(null)).toBe(DEFAULT_MENU_LOCALE);
    expect(resolveMenuLocale(123)).toBe(DEFAULT_MENU_LOCALE);
  });

  it('선택한 로케일을 localStorage에 영속화한다', () => {
    setStoredMenuLocale('en');

    expect(window.localStorage.getItem(MENU_LOCALE_STORAGE_KEY)).toBe('en');
    expect(getStoredMenuLocale()).toBe('en');
  });

  it('로케일 변경 시 같은 탭에 CustomEvent로 통지한다(탭 내 동기화)', () => {
    const listener = vi.fn();

    window.addEventListener(MENU_LOCALE_CHANGE_EVENT, listener);
    setStoredMenuLocale('en');
    window.removeEventListener(MENU_LOCALE_CHANGE_EVENT, listener);

    expect(listener).toHaveBeenCalledTimes(1);
    const event = listener.mock.calls[0][0] as CustomEvent;
    expect(event.detail).toBe('en');
  });

  it('localStorage 접근 실패 시에도 기본 로케일로 안전하게 폴백한다', () => {
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable');
    });

    expect(getStoredMenuLocale()).toBe(DEFAULT_MENU_LOCALE);
  });
});
