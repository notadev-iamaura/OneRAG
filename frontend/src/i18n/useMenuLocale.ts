// 의존성 없는 경량 i18n 레이어(localStorage + CustomEvent + storage 이벤트).
//
// 목적: react-i18next 등 외부 의존성 없이 메뉴/핵심 UI 문자열의 로케일 전환을 제공한다.
//   - localStorage에 선택 로케일을 영속화한다.
//   - 같은 탭 내 동기화: CustomEvent로 즉시 반영한다.
//   - 탭 간 동기화: storage 이벤트로 다른 탭의 변경을 감지한다.
//   - MenuMessages 인터페이스로 누락 키를 컴파일 타임에 검출한다(타입 안전 사전).
//
// OneRAG 범용화: 기본 로케일은 'ko'(한국어)이며 빌드 시 VITE_DEFAULT_LOCALE로 재정의 가능하다.
import { useCallback, useEffect, useMemo, useState } from "react";

import { MENU_LOCALES, type MenuLocale, menuMessages } from "./menuMessages";

// 환경변수 값이 지원 로케일인지 검증하여 기본 로케일을 결정한다.
const resolveDefaultLocale = (): MenuLocale => {
  const fromEnv = import.meta.env.VITE_DEFAULT_LOCALE;
  if (typeof fromEnv === "string" && MENU_LOCALES.includes(fromEnv as MenuLocale)) {
    return fromEnv as MenuLocale;
  }
  // OSS 범용 기본값은 한국어(OneRAG 현 UI 기준).
  return "ko";
};

// 기본 로케일(빌드 시 VITE_DEFAULT_LOCALE로 재정의 가능)
export const DEFAULT_MENU_LOCALE: MenuLocale = resolveDefaultLocale();
// localStorage 키(OneRAG 네임스페이스)
export const MENU_LOCALE_STORAGE_KEY = "onerag_menu_locale";
// 같은 탭 동기화에 사용하는 CustomEvent 이름
export const MENU_LOCALE_CHANGE_EVENT = "onerag-menu-locale-change";

// 임의의 값을 지원되는 로케일로 정규화한다(미지원 값은 기본 로케일로 폴백).
export function resolveMenuLocale(value: unknown): MenuLocale {
  if (typeof value === "string" && MENU_LOCALES.includes(value as MenuLocale)) {
    return value as MenuLocale;
  }
  return DEFAULT_MENU_LOCALE;
}

// localStorage에서 저장된 로케일을 읽어온다(접근 불가 시 기본값).
export function getStoredMenuLocale(): MenuLocale {
  if (typeof window === "undefined") {
    return DEFAULT_MENU_LOCALE;
  }

  try {
    return resolveMenuLocale(window.localStorage.getItem(MENU_LOCALE_STORAGE_KEY));
  } catch {
    return DEFAULT_MENU_LOCALE;
  }
}

// 로케일을 localStorage에 저장하고, 같은 탭에 CustomEvent로 통지한다.
export function setStoredMenuLocale(locale: MenuLocale): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(MENU_LOCALE_STORAGE_KEY, locale);
  } catch {
    // 저장이 불가해도(스토리지 비활성 등) 메모리 상 UI는 즉시 반응하게 둔다.
  }

  window.dispatchEvent(new CustomEvent<MenuLocale>(MENU_LOCALE_CHANGE_EVENT, { detail: locale }));
}

/**
 * useMenuLocale - 현재 로케일 상태와 변경 함수를 제공하는 훅.
 * 같은 탭(CustomEvent)과 다른 탭(storage 이벤트) 변경을 모두 동기화한다.
 */
export function useMenuLocale() {
  const [locale, setLocaleState] = useState<MenuLocale>(() => getStoredMenuLocale());

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }

    // CustomEvent(같은 탭)와 storage 이벤트(다른 탭) 모두를 동일 핸들러로 처리한다.
    const syncLocale = (event: Event) => {
      if (event instanceof CustomEvent) {
        setLocaleState(resolveMenuLocale(event.detail));
        return;
      }

      setLocaleState(getStoredMenuLocale());
    };

    window.addEventListener(MENU_LOCALE_CHANGE_EVENT, syncLocale);
    window.addEventListener("storage", syncLocale);

    return () => {
      window.removeEventListener(MENU_LOCALE_CHANGE_EVENT, syncLocale);
      window.removeEventListener("storage", syncLocale);
    };
  }, []);

  const setLocale = useCallback((nextLocale: MenuLocale) => {
    setLocaleState(nextLocale);
    setStoredMenuLocale(nextLocale);
  }, []);

  return [locale, setLocale] as const;
}

/**
 * useMenuMessages - 현재 로케일에 해당하는 번역 사전과 로케일 제어를 함께 제공하는 훅.
 * 컴포넌트에서 `const { messages, locale, setLocale } = useMenuMessages();`로 사용한다.
 */
export function useMenuMessages() {
  const [locale, setLocale] = useMenuLocale();

  return useMemo(
    () => ({
      locale,
      setLocale,
      messages: menuMessages[locale],
    }),
    [locale, setLocale]
  );
}
