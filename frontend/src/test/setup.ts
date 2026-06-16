/**
 * Vitest 테스트 환경 설정
 */
import '@testing-library/jest-dom';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import { setupMockServer } from './mocks/server';

// MSW 서버 설정
setupMockServer();

// happy-dom iframe 페이지 로딩 전역 비활성화.
// ChunkDetailModal 등에서 PDF blob을 iframe src로 설정하면 happy-dom이
// 비동기로 페이지 로딩을 시도하는데, 이 로딩이 테스트(및 afterAll) 종료 후에
// 늦게 실패하면서 unhandled DOMException으로 새어 나와 warning-gate를 깨뜨린다(CI flaky).
// 어떤 테스트도 실제 iframe 페이지 로딩을 필요로 하지 않으므로 전역으로 끈다.
{
  const happyDOM = (
    globalThis as { happyDOM?: { settings: { disableIframePageLoading: boolean } } }
  ).happyDOM;
  if (happyDOM) {
    happyDOM.settings.disableIframePageLoading = true;
  }
}

// 각 테스트 후 자동 클린업
afterEach(() => {
  cleanup();
});

// 전역 설정
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// localStorage mock
const localStorageMock = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
  clear: () => {},
  length: 0,
  key: () => null,
};

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
});

// matchMedia mock
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => {},
  }),
});
