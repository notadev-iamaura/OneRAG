import { describe, it, expect } from "vitest";

import { format, formatNumber, formatDate } from "../format";

describe("format (보간 헬퍼)", () => {
  it("params 미전달 시 템플릿을 그대로 반환한다(회귀 안전)", () => {
    expect(format("참고한 문서")).toBe("참고한 문서");
  });

  it("단일 변수를 치환한다", () => {
    expect(format("참고한 문서 {count}개", { count: 3 })).toBe("참고한 문서 3개");
  });

  it("어순이 다른 로케일 템플릿도 변수 위치대로 치환한다", () => {
    expect(format("{name}을 삭제", { name: "doc.pdf" })).toBe("doc.pdf을 삭제");
    expect(format("Delete {name}", { name: "doc.pdf" })).toBe("Delete doc.pdf");
  });

  it("다중 변수를 치환한다", () => {
    expect(format("{a}/{b}", { a: 1, b: 2 })).toBe("1/2");
  });

  it("대응 키가 없는 플레이스홀더는 원본 그대로 둔다(부분 치환 안전)", () => {
    expect(format("{known}-{unknown}", { known: "x" })).toBe("x-{unknown}");
  });
});

describe("formatNumber (로케일 인지 숫자)", () => {
  it("ko/en 모두 천 단위 구분 기호를 적용한다", () => {
    expect(formatNumber(1234567, "ko")).toBe("1,234,567");
    expect(formatNumber(1234567, "en")).toBe("1,234,567");
  });
});

describe("formatDate (로케일 인지 날짜)", () => {
  it("ISO 문자열/epoch/Date 입력을 모두 허용한다", () => {
    const iso = "2026-01-15T00:00:00Z";
    // 로케일별 출력 형식은 환경에 의존하므로, 비어있지 않고 예외 없이 동작함을 검증한다.
    expect(formatDate(iso, "ko")).toBeTruthy();
    expect(formatDate(new Date(iso), "en")).toBeTruthy();
    expect(formatDate(Date.parse(iso), "ko")).toBeTruthy();
  });

  it("로케일에 따라 다른 표기를 만들 수 있다(연-월-일 옵션)", () => {
    const opts: Intl.DateTimeFormatOptions = { year: "numeric", month: "long", day: "numeric" };
    const ko = formatDate("2026-01-15T00:00:00Z", "ko", opts);
    const en = formatDate("2026-01-15T00:00:00Z", "en", opts);
    expect(ko).toBeTruthy();
    expect(en).toBeTruthy();
    // ko는 '년'/'월'/'일' 표기를 포함한다.
    expect(ko).toContain("년");
  });
});
