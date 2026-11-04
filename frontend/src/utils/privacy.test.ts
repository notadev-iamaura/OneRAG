/**
 * privacy.ts 유틸리티 함수 단위 테스트
 *
 * 전화번호 마스킹 로직의 정확성과 False Positive 방지를 검증합니다.
 *
 * @module privacy.test
 * @author Claude Code
 * @created 2025-11-18
 */

import { describe, it, expect } from 'vitest';
import {
  maskPhoneNumber,
  maskPhoneNumberDeep,
  measureMaskingPerformance,
  type MaskingOptions,
} from './privacy';

describe('maskPhoneNumber - 기본 기능 테스트', () => {
  it('하이픈 구분 전화번호를 마스킹해야 함', () => {
    const input = '연락처: 010-1234-5678';
    const expected = '연락처: [전화번호]';
    expect(maskPhoneNumber(input)).toBe(expected);
  });

  it('점 구분 전화번호를 마스킹해야 함', () => {
    const input = '전화번호는 010.1234.5678입니다';
    const expected = '전화번호는 [전화번호]입니다';
    expect(maskPhoneNumber(input)).toBe(expected);
  });

  it('구분자 없는 전화번호를 마스킹해야 함', () => {
    const input = '01012345678로 연락주세요';
    const expected = '[전화번호]로 연락주세요';
    expect(maskPhoneNumber(input)).toBe(expected);
  });

  it('여러 전화번호를 모두 마스킹해야 함', () => {
    const input = '010-1234-5678 또는 010.8765.4321 또는 01011112222';
    const expected = '[전화번호] 또는 [전화번호] 또는 [전화번호]';
    expect(maskPhoneNumber(input)).toBe(expected);
  });

  it('커스텀 대체 텍스트를 사용할 수 있어야 함', () => {
    const input = '연락처: 010-1234-5678';
    const options: MaskingOptions = { replacement: '***' };
    const expected = '연락처: ***';
    expect(maskPhoneNumber(input, options)).toBe(expected);
  });
});

describe('maskPhoneNumber - False Positive 방지 테스트', () => {
  it('날짜 패턴을 전화번호로 오인하지 않아야 함', () => {
    const testCases = [
      '2010년 1234월 5678일',
      '2010-1234-5678 (날짜 형식)',
      '생년월일: 2010.1234.5678',
    ];

    testCases.forEach((input) => {
      expect(maskPhoneNumber(input)).toBe(input);
    });
  });

  it('사업자등록번호를 전화번호로 오인하지 않아야 함', () => {
    const input = '사업자등록번호: 010-12-34567';
    expect(maskPhoneNumber(input)).toBe(input);
  });

  it('긴 숫자 문자열의 일부를 전화번호로 오인하지 않아야 함', () => {
    const testCases = [
      '계좌번호: 1234010123456789', // 앞부분이 010으로 시작하지만 11자리를 초과
      '주문번호: 20231201012345678', // 중간에 010이 포함되지만 단어 경계가 아님
    ];

    testCases.forEach((input) => {
      expect(maskPhoneNumber(input)).toBe(input);
    });
  });

  it('010으로 시작하지만 전화번호가 아닌 패턴을 마스킹하지 않아야 함', () => {
    const testCases = [
      '010개의 사과', // 단순 숫자 + 텍스트
      '010-12-345', // 자릿수 부족
      '010.1234.567', // 자릿수 부족
      '0101234567', // 10자리 (11자리 미만)
    ];

    testCases.forEach((input) => {
      expect(maskPhoneNumber(input)).toBe(input);
    });
  });
});

describe('maskPhoneNumber - Edge Case 테스트', () => {
  it('빈 문자열을 처리해야 함', () => {
    expect(maskPhoneNumber('')).toBe('');
    expect(maskPhoneNumber('   ')).toBe('   ');
  });

  it('null과 undefined를 안전하게 처리해야 함', () => {
    expect(maskPhoneNumber(null)).toBe('');
    expect(maskPhoneNumber(undefined)).toBe('');
  });

  it('전화번호가 없는 텍스트는 변경하지 않아야 함', () => {
    const input = '안녕하세요, 이것은 전화번호가 없는 텍스트입니다.';
    expect(maskPhoneNumber(input)).toBe(input);
  });

  it('전화번호만 있는 텍스트를 마스킹해야 함', () => {
    expect(maskPhoneNumber('010-1234-5678')).toBe('[전화번호]');
    expect(maskPhoneNumber('010.1234.5678')).toBe('[전화번호]');
    expect(maskPhoneNumber('01012345678')).toBe('[전화번호]');
  });

  it('문자열이 아닌 타입을 안전하게 처리해야 함', () => {
    // @ts-expect-error - 테스트를 위해 의도적으로 잘못된 타입 전달
    expect(maskPhoneNumber(12345)).toBe('');

    // @ts-expect-error - 테스트를 위해 의도적으로 잘못된 타입 전달
    expect(maskPhoneNumber({})).toBe('');

    // @ts-expect-error - 테스트를 위해 의도적으로 잘못된 타입 전달
    expect(maskPhoneNumber([])).toBe('');
  });
});

describe('maskPhoneNumberDeep - 재귀 마스킹 테스트', () => {
  it('객체의 모든 문자열 필드를 마스킹해야 함', () => {
    const input = {
      name: '홍길동',
      contact: '010-1234-5678',
      address: '서울시 강남구',
      backup: '010.8765.4321',
    };

    const expected = {
      name: '홍길동',
      contact: '[전화번호]',
      address: '서울시 강남구',
      backup: '[전화번호]',
    };

    expect(maskPhoneNumberDeep(input)).toEqual(expected);
  });

  it('배열의 모든 요소를 마스킹해야 함', () => {
    const input = [
      { text: '연락처: 010-1234-5678' },
      { text: '주소: 서울시' },
      { text: '전화: 01012345678' },
    ];

    const expected = [
      { text: '연락처: [전화번호]' },
      { text: '주소: 서울시' },
      { text: '전화: [전화번호]' },
    ];

    expect(maskPhoneNumberDeep(input)).toEqual(expected);
  });

  it('중첩된 객체를 재귀적으로 마스킹해야 함', () => {
    const input = {
      user: {
        name: '홍길동',
        contact: {
          phone: '010-1234-5678',
          email: 'test@example.com',
        },
      },
      messages: [
        { text: '전화번호: 010.8765.4321' },
        { text: '이메일로 연락주세요' },
      ],
    };

    const expected = {
      user: {
        name: '홍길동',
        contact: {
          phone: '[전화번호]',
          email: 'test@example.com',
        },
      },
      messages: [
        { text: '전화번호: [전화번호]' },
        { text: '이메일로 연락주세요' },
      ],
    };

    expect(maskPhoneNumberDeep(input)).toEqual(expected);
  });

  it('null과 undefined를 안전하게 처리해야 함', () => {
    expect(maskPhoneNumberDeep(null)).toBe(null);
    expect(maskPhoneNumberDeep(undefined)).toBe(undefined);
  });

  it('숫자와 boolean 타입은 변경하지 않아야 함', () => {
    const input = {
      count: 100,
      isActive: true,
      percentage: 75.5,
    };

    expect(maskPhoneNumberDeep(input)).toEqual(input);
  });

  it('원본 객체를 변경하지 않아야 함 (불변성 유지)', () => {
    const original = {
      name: '홍길동',
      phone: '010-1234-5678',
    };

    const originalCopy = { ...original };
    const masked = maskPhoneNumberDeep(original);

    // 원본 객체는 변경되지 않아야 함
    expect(original).toEqual(originalCopy);
    expect(masked).not.toEqual(original);
    expect(masked.phone).toBe('[전화번호]');
  });
});

describe('maskPhoneNumber - 성능 테스트', () => {
  it('단일 메시지 처리는 1ms 이하여야 함', () => {
    const input = '안녕하세요, 연락처는 010-1234-5678입니다.';
    const [, duration] = measureMaskingPerformance(input);

    expect(duration).toBeLessThan(1); // < 1ms
  });

  it('100개 메시지 처리는 10ms 이하여야 함', () => {
    const messages = Array(100).fill('연락처: 010-1234-5678');
    const startTime = performance.now();

    messages.forEach((msg) => maskPhoneNumber(msg));

    const duration = performance.now() - startTime;
    expect(duration).toBeLessThan(10); // < 10ms
  });

  it('대용량 텍스트 (10KB) 처리는 50ms 이하여야 함', () => {
    const largeText = '안녕하세요. 연락처: 010-1234-5678\n'.repeat(500); // ~10KB
    const [, duration] = measureMaskingPerformance(largeText);

    expect(duration).toBeLessThan(50); // < 50ms
  });
});

describe('maskPhoneNumber - 실전 시나리오 테스트', () => {
  it('채팅 메시지 형식을 올바르게 마스킹해야 함', () => {
    const chatMessages = [
      '안녕하세요! 저는 홍길동입니다.',
      '연락 가능한 번호는 010-1234-5678입니다.',
      '이메일은 hong@example.com이고, 휴대폰은 010.8765.4321입니다.',
      '긴급 연락처: 01011112222',
    ];

    const expected = [
      '안녕하세요! 저는 홍길동입니다.',
      '연락 가능한 번호는 [전화번호]입니다.',
      '이메일은 hong@example.com이고, 휴대폰은 [전화번호]입니다.',
      '긴급 연락처: [전화번호]',
    ];

    chatMessages.forEach((msg, idx) => {
      expect(maskPhoneNumber(msg)).toBe(expected[idx]);
    });
  });

  it('문서 내용 형식을 올바르게 마스킹해야 함', () => {
    const documentContent = `
      고객 정보:
      - 이름: 홍길동
      - 전화번호: 010-1234-5678
      - 이메일: hong@example.com
      - 생년월일: 1990.01.01
      - 비상연락처: 010.8765.4321

      참고: 2010년 입사
    `;

    const result = maskPhoneNumber(documentContent);

    expect(result).toContain('[전화번호]');
    expect(result).not.toContain('010-1234-5678');
    expect(result).not.toContain('010.8765.4321');
    expect(result).toContain('1990.01.01'); // 생년월일은 유지
    expect(result).toContain('2010년 입사'); // 연도는 유지
  });

  it('API 응답 객체를 올바르게 마스킹해야 함', () => {
    const apiResponse = {
      status: 'success',
      data: {
        messages: [
          {
            id: 1,
            user: '홍길동',
            text: '제 연락처는 010-1234-5678입니다.',
            timestamp: '2024-01-01T10:00:00Z',
          },
          {
            id: 2,
            user: '김철수',
            text: '010.8765.4321로 연락주세요.',
            timestamp: '2024-01-01T10:05:00Z',
          },
        ],
        documents: [
          {
            id: 1,
            title: '고객 정보',
            content: '연락처: 01011112222',
          },
        ],
      },
    };

    const masked = maskPhoneNumberDeep(apiResponse);

    expect(masked.data.messages[0]?.text).toBe('제 연락처는 [전화번호]입니다.');
    expect(masked.data.messages[1]?.text).toBe('[전화번호]로 연락주세요.');
    expect(masked.data.documents[0]?.content).toBe('연락처: [전화번호]');
  });
});
