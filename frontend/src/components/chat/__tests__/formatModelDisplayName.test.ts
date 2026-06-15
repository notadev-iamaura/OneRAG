/**
 * formatModelDisplayName 유틸 테스트 (순수 문자열 정규화, GCP 결합 없음)
 *
 * - publishers/google/models/ · models/ prefix 및 슬래시 경로 제거
 * - Gemini 계열을 'Gemini {버전} {Family}' 형태로 포맷
 * - 빈 값은 undefined 반환(호출 측 N/A 처리)
 */
import { describe, it, expect } from 'vitest';
import { formatModelDisplayName } from '../formatModelDisplayName';

describe('formatModelDisplayName', () => {
  it('빈 값(undefined/null/빈문자열)은 undefined를 반환한다', () => {
    expect(formatModelDisplayName(undefined)).toBeUndefined();
    expect(formatModelDisplayName(null)).toBeUndefined();
    expect(formatModelDisplayName('')).toBeUndefined();
  });

  it('publishers/google/models/ prefix를 제거한다', () => {
    expect(formatModelDisplayName('publishers/google/models/gemini-2.0-flash')).toBe('Gemini 2.0 Flash');
  });

  it('models/ prefix를 제거한다', () => {
    expect(formatModelDisplayName('models/gemini-1.5-pro')).toBe('Gemini 1.5 Pro');
  });

  it('Gemini family 토큰을 라벨 매핑으로 변환한다', () => {
    expect(formatModelDisplayName('gemini-2.0-flash')).toBe('Gemini 2.0 Flash');
    expect(formatModelDisplayName('gemini-2.5-flash-lite')).toBe('Gemini 2.5 Flash Lite');
    expect(formatModelDisplayName('gemini-1.5-pro')).toBe('Gemini 1.5 Pro');
  });

  it('매핑에 없는 family 토큰은 첫 글자만 대문자로 변환한다', () => {
    expect(formatModelDisplayName('gemini-2.0-thinking')).toBe('Gemini 2.0 Thinking');
  });

  it('family가 없는 Gemini 표기는 그대로 둔다(과변환 방지)', () => {
    // 기존 RagTracePanel 회귀 테스트 보호: 'gemini-2.0'은 family가 없어 변환하지 않는다.
    expect(formatModelDisplayName('gemini-2.0')).toBe('gemini-2.0');
  });

  it('Gemini가 아닌 모델은 마지막 경로 세그먼트(모델 ID)를 그대로 반환한다', () => {
    expect(formatModelDisplayName('gpt-4o')).toBe('gpt-4o');
    expect(formatModelDisplayName('claude-sonnet-4-5')).toBe('claude-sonnet-4-5');
    expect(formatModelDisplayName('openrouter/google/gemini-flash')).toBe('gemini-flash');
  });

  it('숫자 등 비문자열 입력도 안전하게 문자열화한다', () => {
    expect(formatModelDisplayName(42)).toBe('42');
  });
});
