let clientIdCounter = 0;

export function createClientId(prefix: string = 'client'): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  // crypto.randomUUID 미지원 환경에서만 카운터로 충돌을 방지한다([44]).
  clientIdCounter = (clientIdCounter + 1) % Number.MAX_SAFE_INTEGER;
  const randomPart = Math.random().toString(36).substring(2, 11);
  return `${prefix}-${Date.now()}-${clientIdCounter}-${randomPart}`;
}
