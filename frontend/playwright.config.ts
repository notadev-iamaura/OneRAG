/**
 * Playwright E2E 테스트 설정 파일
 *
 * 이 파일은 Playwright 테스트 러너의 기본 설정을 정의합니다.
 * WebSocket 채팅 기능 테스트를 포함한 E2E 테스트에 사용됩니다.
 *
 * 실행 방법:
 *   npx playwright test                    # 모든 테스트 실행
 *   npx playwright test websocket-chat     # WebSocket 테스트만 실행
 *   npx playwright test --ui               # UI 모드로 실행
 *   npx playwright test --debug            # 디버그 모드로 실행
 */

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  // 테스트 파일 위치
  testDir: './e2e',

  // 테스트 파일 패턴
  testMatch: '**/*.spec.ts',

  // 최대 병렬 실행 워커 수
  fullyParallel: true,
  workers: process.env.CI ? 1 : undefined,

  // 실패 시 재시도 횟수 (CI에서는 2번 재시도)
  retries: process.env.CI ? 2 : 0,

  // 리포터 설정
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],

  // 전역 설정
  use: {
    // 기본 URL (개발 서버)
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5000',

    // 테스트 실패 시 스크린샷 캡처
    screenshot: 'only-on-failure',

    // 테스트 실패 시 비디오 녹화
    video: 'retain-on-failure',

    // 트레이스 수집 (첫 번째 재시도 시)
    trace: 'on-first-retry',

    // 뷰포트 설정
    viewport: { width: 1280, height: 720 },

    // 타임아웃 설정
    actionTimeout: 10000,
    navigationTimeout: 30000,
  },

  // 전역 타임아웃 (각 테스트당 60초)
  timeout: 60000,

  // 전역 expect 타임아웃
  expect: {
    timeout: 10000,
  },

  // 브라우저 프로젝트 설정
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
    // 모바일 테스트
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
    },
    {
      name: 'mobile-safari',
      use: { ...devices['iPhone 12'] },
    },
  ],

  // 개발 서버 자동 실행 (CI가 아닌 경우)
  webServer: process.env.CI
    ? undefined
    : {
        command: 'npm run dev',
        url: 'http://localhost:5000',
        reuseExistingServer: !process.env.CI,
        timeout: 120000,
      },

  // 출력 디렉토리
  outputDir: './e2e/test-results',
});
