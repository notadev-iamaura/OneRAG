/**
 * 깊은 부분 설정 타입 (중첩 객체의 일부 키만 오버라이드 가능)
 *
 * 설정 병합(mergeConfig/deepMerge)과 런타임 오버라이드(프리셋, Feature Flag)에서 공용으로 사용한다.
 * 순환 import를 피하기 위해 독립 모듈로 분리했다.
 */
export type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends readonly unknown[]
    ? T[K]
    : T[K] extends object
      ? DeepPartial<T[K]>
      : T[K];
};
