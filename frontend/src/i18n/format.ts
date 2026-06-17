// 경량 i18n 보간/포맷 헬퍼.
//
// 목적: 카탈로그(menuMessages)의 정적 문자열 위에 외부 의존성(react-i18next 등) 없이
//   (1) 단일/다중 변수 보간, (2) 로케일 인지 숫자·날짜 포맷을 얇게 제공한다.
//   기존 정적 문자열 사용 경로는 그대로 두므로(미사용 시) 회귀 0.
//
// 설계 메모(범용화):
//   - 어순이 로케일별로 다른 문장은 템플릿 '전체'를 로케일별로 카탈로그에 보유하고,
//     변수만 format()으로 끼워넣는다(접미 결합 금지).
//   - 날짜/숫자는 toLocaleString('ko-KR') 하드코딩 대신 현재 로케일을 받는 래퍼로 통일한다.
import { type MenuLocale } from "./menuMessages";

// MenuLocale → BCP-47 로케일 태그(Intl 위임용). 새 로케일 추가 시 여기에 매핑한다.
const INTL_LOCALES: Record<MenuLocale, string> = {
  ko: "ko-KR",
  en: "en-US",
};

/**
 * format - 템플릿의 `{key}` 플레이스홀더를 params 값으로 치환한다.
 *
 * 예) format("참고한 문서 {count}개", { count: 3 }) → "참고한 문서 3개"
 *     format("Delete {name}", { name: "doc.pdf" }) → "Delete doc.pdf"
 *
 * @param template 치환할 템플릿 문자열(보통 카탈로그 값)
 * @param params `{key}`에 대응하는 치환 값(문자열/숫자). 미전달 시 원본을 그대로 반환.
 * @returns 치환된 문자열. 대응 키가 없는 플레이스홀더는 원본 그대로 둔다(부분 치환 안전).
 */
export function format(
  template: string,
  params?: Record<string, string | number>
): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : match
  );
}

/**
 * formatNumber - 현재 로케일 규칙으로 숫자를 포맷한다(Intl.NumberFormat 위임).
 *
 * @param value 포맷할 숫자
 * @param locale 현재 로케일(useMenuMessages의 locale)
 * @param options Intl.NumberFormat 옵션(통화/소수 자리 등, 선택)
 */
export function formatNumber(
  value: number,
  locale: MenuLocale,
  options?: Intl.NumberFormatOptions
): string {
  return new Intl.NumberFormat(INTL_LOCALES[locale], options).format(value);
}

/**
 * formatDate - 현재 로케일 규칙으로 날짜를 포맷한다(Intl.DateTimeFormat 위임).
 *
 * toLocaleDateString('ko-KR') 하드코딩을 대체하기 위한 래퍼다(로케일 전환 시 자동 반영).
 *
 * @param value Date | ISO 문자열 | epoch(ms)
 * @param locale 현재 로케일(useMenuMessages의 locale)
 * @param options Intl.DateTimeFormat 옵션(선택)
 */
export function formatDate(
  value: Date | string | number,
  locale: MenuLocale,
  options?: Intl.DateTimeFormatOptions
): string {
  const date = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat(INTL_LOCALES[locale], options).format(date);
}
