import { describe, expect, it } from 'vitest';
import { createClientId } from '../clientId';

describe('createClientId', () => {
  it('같은 prefix로 반복 생성해도 고유한 ID를 반환한다', () => {
    const ids = Array.from({ length: 20 }, () => createClientId('api-log'));

    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.every((id) => id.startsWith('api-log-'))).toBe(true);
  });
});
