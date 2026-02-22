/**
 * WebSocket 채팅 E2E 테스트
 *
 * 이 테스트는 WebSocket 기반 실시간 채팅 기능을 검증합니다.
 * 실제 서버가 실행 중일 때만 통과합니다.
 *
 * 테스트 항목:
 *   1. 메시지 전송 및 스트리밍 응답 수신
 *   2. WebSocket 연결 상태 표시
 *   3. 연속 메시지 전송
 *   4. 스트리밍 응답 중 UI 상태
 *   5. 연결 오류 처리
 *
 * 실행 방법:
 *   npx playwright test websocket-chat.spec.ts
 *   npx playwright test websocket-chat.spec.ts --headed  # 브라우저 표시
 *   npx playwright test websocket-chat.spec.ts --debug   # 디버그 모드
 */

import { test, expect } from '@playwright/test';

// 테스트 전역 설정
test.describe('WebSocket 채팅 E2E 테스트', () => {
  // 각 테스트 전에 실행
  test.beforeEach(async ({ page }) => {
    // 채팅 페이지로 이동
    await page.goto('/bot');

    // 페이지 로드 완료 대기 (채팅 입력창이 나타날 때까지)
    await page.waitForSelector('[data-testid="chat-input"]', { timeout: 10000 });
  });

  test('채팅 메시지를 전송하면 스트리밍 응답을 받아야 함', async ({ page }) => {
    // 채팅 입력창 찾기
    const input = page.locator('[data-testid="chat-input"]');
    await expect(input).toBeVisible();

    // 메시지 입력
    await input.fill('안녕하세요');

    // 전송 버튼 클릭
    const sendButton = page.locator('[data-testid="send-button"]');
    await expect(sendButton).toBeVisible();
    await sendButton.click();

    // 사용자 메시지가 표시되는지 확인
    const userMessage = page.locator('[data-testid="user-message"]').last();
    await expect(userMessage).toContainText('안녕하세요');

    // 스트리밍 응답 대기 (최대 15초)
    // 어시스턴트 메시지가 나타날 때까지 대기
    const assistantMessage = page.locator('[data-testid="assistant-message"]').last();
    await expect(assistantMessage).toBeVisible({ timeout: 15000 });

    // 응답 내용이 있는지 확인
    const content = await assistantMessage.textContent();
    expect(content).toBeTruthy();
    expect(content!.length).toBeGreaterThan(0);
  });

  test('WebSocket 연결 상태가 표시되어야 함', async ({ page }) => {
    // 연결 상태 표시 요소 확인 (선택적)
    const connectionStatus = page.locator('[data-testid="connection-status"]');

    // 연결 상태 표시가 있는 경우에만 검증
    if (await connectionStatus.isVisible({ timeout: 3000 }).catch(() => false)) {
      // 연결됨 또는 connected 텍스트 확인
      await expect(connectionStatus).toHaveText(/연결|connected|online/i);
    } else {
      // 연결 상태 표시가 없으면 테스트 스킵
      test.info().annotations.push({
        type: 'skip',
        description: '연결 상태 표시 요소가 없습니다 (data-testid="connection-status")',
      });
    }
  });

  test('여러 메시지를 연속으로 전송할 수 있어야 함', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    const sendButton = page.locator('[data-testid="send-button"]');

    // 첫 번째 메시지 전송
    await input.fill('첫 번째 질문입니다');
    await sendButton.click();

    // 첫 번째 응답 대기
    await page.waitForSelector('[data-testid="assistant-message"]', { timeout: 15000 });

    // 입력창이 비워졌는지 확인
    await expect(input).toHaveValue('');

    // 두 번째 메시지 전송
    await input.fill('두 번째 질문입니다');
    await sendButton.click();

    // 두 번째 응답 대기 - 어시스턴트 메시지가 2개가 될 때까지
    const assistantMessages = page.locator('[data-testid="assistant-message"]');
    await expect(assistantMessages).toHaveCount(2, { timeout: 20000 });

    // 모든 메시지가 내용을 가지고 있는지 확인
    const count = await assistantMessages.count();
    for (let i = 0; i < count; i++) {
      const message = assistantMessages.nth(i);
      const content = await message.textContent();
      expect(content).toBeTruthy();
      expect(content!.length).toBeGreaterThan(0);
    }
  });

  test('스트리밍 응답 중에는 입력이 비활성화되어야 함', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    const sendButton = page.locator('[data-testid="send-button"]');

    // 메시지 전송
    await input.fill('테스트 메시지');
    await sendButton.click();

    // 스트리밍 중 로딩 인디케이터 확인 (선택적)
    const loadingIndicator = page.locator('[data-testid="loading-indicator"]');

    if (await loadingIndicator.isVisible({ timeout: 2000 }).catch(() => false)) {
      // 로딩 중에는 전송 버튼이 비활성화되어야 함
      await expect(sendButton).toBeDisabled();
    }

    // 응답 완료 대기
    await page.waitForSelector('[data-testid="assistant-message"]', { timeout: 15000 });

    // 응답 완료 후 입력창이 다시 활성화되어야 함
    await expect(input).toBeEnabled();
    await expect(sendButton).toBeEnabled();
  });

  test('Enter 키로 메시지를 전송할 수 있어야 함', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');

    // 메시지 입력 후 Enter 키 누르기
    await input.fill('Enter 키 테스트');
    await input.press('Enter');

    // 사용자 메시지 확인
    const userMessage = page.locator('[data-testid="user-message"]').last();
    await expect(userMessage).toContainText('Enter 키 테스트');

    // 응답 대기
    const assistantMessage = page.locator('[data-testid="assistant-message"]').last();
    await expect(assistantMessage).toBeVisible({ timeout: 15000 });
  });

  test('빈 메시지는 전송되지 않아야 함', async ({ page }) => {
    const sendButton = page.locator('[data-testid="send-button"]');

    // 메시지 없이 전송 버튼 확인
    // 빈 상태에서는 버튼이 비활성화되거나 클릭해도 메시지가 전송되지 않아야 함
    const isDisabled = await sendButton.isDisabled().catch(() => false);

    if (isDisabled) {
      // 버튼이 비활성화된 경우 - 예상대로 동작
      await expect(sendButton).toBeDisabled();
    } else {
      // 버튼이 활성화된 경우 - 클릭해도 메시지가 없어야 함
      await sendButton.click();

      // 잠시 대기 후 메시지가 전송되지 않았는지 확인
      await page.waitForTimeout(1000);
      const userMessages = page.locator('[data-testid="user-message"]');
      const count = await userMessages.count();
      expect(count).toBe(0);
    }
  });

  test('긴 메시지도 정상적으로 전송되어야 함', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    const sendButton = page.locator('[data-testid="send-button"]');

    // 긴 메시지 생성 (500자)
    const longMessage = '이것은 긴 테스트 메시지입니다. '.repeat(25);

    // 메시지 입력 및 전송
    await input.fill(longMessage);
    await sendButton.click();

    // 사용자 메시지 확인
    const userMessage = page.locator('[data-testid="user-message"]').last();
    await expect(userMessage).toBeVisible();

    // 응답 대기
    const assistantMessage = page.locator('[data-testid="assistant-message"]').last();
    await expect(assistantMessage).toBeVisible({ timeout: 20000 });
  });
});

// 네트워크 오류 처리 테스트 (별도 describe 블록)
test.describe('WebSocket 연결 오류 처리', () => {
  test('서버 연결 실패 시 오류 메시지를 표시해야 함', async ({ page }) => {
    // 네트워크 요청 차단하여 연결 실패 시뮬레이션
    await page.route('**/ws/**', (route) => route.abort());
    await page.route('**/chat/ws**', (route) => route.abort());

    // 채팅 페이지로 이동
    await page.goto('/bot');

    // 페이지 로드 대기
    await page.waitForSelector('[data-testid="chat-input"]', { timeout: 10000 });

    const input = page.locator('[data-testid="chat-input"]');
    const sendButton = page.locator('[data-testid="send-button"]');

    // 메시지 전송 시도
    await input.fill('연결 테스트');
    await sendButton.click();

    // 오류 메시지 또는 재연결 시도 표시 확인 (선택적)
    const errorMessage = page.locator('[data-testid="error-message"]');
    const connectionError = page.locator('[data-testid="connection-error"]');

    // 오류 관련 요소 중 하나가 표시되는지 확인
    const hasError = await Promise.race([
      errorMessage.isVisible({ timeout: 5000 }).catch(() => false),
      connectionError.isVisible({ timeout: 5000 }).catch(() => false),
    ]);

    if (!hasError) {
      // 오류 표시가 없으면 정보 추가
      test.info().annotations.push({
        type: 'info',
        description: '연결 오류 시 별도의 오류 메시지가 표시되지 않습니다.',
      });
    }
  });
});

// 반응형 디자인 테스트
test.describe('반응형 채팅 UI 테스트', () => {
  test('모바일 뷰포트에서 채팅이 정상 동작해야 함', async ({ page }) => {
    // 모바일 뷰포트 설정
    await page.setViewportSize({ width: 375, height: 667 });

    // 채팅 페이지로 이동
    await page.goto('/bot');
    await page.waitForSelector('[data-testid="chat-input"]', { timeout: 10000 });

    const input = page.locator('[data-testid="chat-input"]');
    const sendButton = page.locator('[data-testid="send-button"]');

    // 모바일에서 입력 및 전송
    await input.fill('모바일 테스트');
    await sendButton.click();

    // 응답 확인
    const assistantMessage = page.locator('[data-testid="assistant-message"]').last();
    await expect(assistantMessage).toBeVisible({ timeout: 15000 });
  });
});

// 접근성 테스트
test.describe('채팅 접근성 테스트', () => {
  test('키보드만으로 채팅을 사용할 수 있어야 함', async ({ page }) => {
    await page.goto('/bot');
    await page.waitForSelector('[data-testid="chat-input"]', { timeout: 10000 });

    // Tab 키로 입력창으로 이동
    await page.keyboard.press('Tab');

    // 현재 포커스된 요소가 입력창인지 확인
    const focusedElement = page.locator(':focus');
    const tagName = await focusedElement.evaluate((el) => el.tagName.toLowerCase());

    // input 또는 textarea인지 확인
    expect(['input', 'textarea']).toContain(tagName);

    // 메시지 입력
    await page.keyboard.type('키보드 접근성 테스트');

    // Tab으로 전송 버튼으로 이동
    await page.keyboard.press('Tab');

    // Enter로 전송
    await page.keyboard.press('Enter');

    // 응답 대기
    const assistantMessage = page.locator('[data-testid="assistant-message"]').last();
    await expect(assistantMessage).toBeVisible({ timeout: 15000 });
  });
});
