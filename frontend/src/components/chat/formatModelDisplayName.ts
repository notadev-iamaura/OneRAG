/**
 * 모델 표시명 정규화 유틸 (순수 문자열 — GCP/SDK 결합 없음, 도메인 무관)
 *
 * 백엔드가 내려주는 원시 모델 식별자를 사용자 친화적인 표시명으로 변환한다.
 * - `publishers/google/models/`, `models/` prefix 및 슬래시 경로를 제거해 모델 ID만 남긴다.
 * - Gemini 계열은 'Gemini {version} {Family}' 형태로 가독성 있게 포맷한다
 *   (예: `gemini-2.0-flash` → `Gemini 2.0 Flash`).
 */

// Gemini 모델 family 토큰을 보기 좋은 라벨로 변환하기 위한 매핑.
const GEMINI_FAMILY_LABELS: Record<string, string> = {
  flash: 'Flash',
  lite: 'Lite',
  pro: 'Pro',
  image: 'Image',
  live: 'Live',
  experimental: 'Experimental',
};

/**
 * 모델 표시명 정규화.
 *
 * @param rawValue 백엔드가 내려준 모델 식별자(임의 타입 허용)
 * @returns 표시용 모델명 문자열, 값이 없으면 undefined(호출 측에서 N/A 처리)
 */
export function formatModelDisplayName(rawValue: unknown): string | undefined {
  if (rawValue === undefined || rawValue === null || rawValue === '') {
    return undefined;
  }

  const fullName = String(rawValue);
  // prefix/경로 제거 후 마지막 세그먼트를 모델 ID로 사용한다.
  const modelId =
    fullName
      .replace(/^publishers\/google\/models\//i, '')
      .replace(/^models\//i, '')
      .split('/')
      .filter(Boolean)
      .at(-1) || fullName;

  // Gemini 계열(`gemini-{버전}-{family}`)만 보기 좋게 변환한다.
  const geminiMatch = modelId.match(/^gemini-(\d+(?:\.\d+)?)-(.+)$/i);
  const version = geminiMatch?.[1];
  const family = geminiMatch?.[2];
  if (version && family) {
    const familyName = family
      .split('-')
      .map(
        (part) =>
          GEMINI_FAMILY_LABELS[part.toLowerCase()] ??
          part.charAt(0).toUpperCase() + part.slice(1).toLowerCase()
      )
      .join(' ');
    return `Gemini ${version} ${familyName}`;
  }

  return modelId;
}
