/**
 * MSW 서버 설정 (테스트 환경용)
 */
import { afterAll, afterEach, beforeAll } from 'vitest';
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

// MSW 서버 생성
export const server = setupServer(...handlers);

// 테스트 환경 전역 설정
export const setupMockServer = () => {
  // 모든 테스트 시작 전 서버 시작
  beforeAll(() => {
    server.listen({
      onUnhandledRequest: 'warn', // 처리되지 않은 요청에 대해 경고
    });
  });

  // 각 테스트 후 핸들러 초기화
  afterEach(() => {
    server.resetHandlers();
  });

  // 모든 테스트 종료 후 서버 종료
  afterAll(() => {
    server.close();
  });
};
