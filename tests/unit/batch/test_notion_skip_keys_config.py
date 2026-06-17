"""
NotionBatchProcessor 속성 skip 키 config 외부화 테스트

_extract_properties_text의 제목 중복 컬럼 skip 키가 config로 외부화되어
(domain.batch.skip_property_keys) 데드 키가 아닌지, 미설정 시 한국어 기본
집합으로 폴백하는지(회귀 0) 검증한다.
"""

from app.batch.notion_batch import NotionBatchConfig, NotionBatchProcessor


class TestNotionSkipKeysConfig:
    """skip_property_keys 주입 + 기본 폴백 검증"""

    def _processor(self, skip_keys: list[str] | None) -> NotionBatchProcessor:
        """config만 주입한 프로세서 생성(환경변수 로드 우회)"""
        cfg = NotionBatchConfig(
            skip_property_keys=skip_keys or [],
        )
        return NotionBatchProcessor(config=cfg)

    def test_default_skip_keys_unchanged(self) -> None:
        """skip_property_keys 미설정 시 기본 집합({업체명,이름,Name}) 사용(회귀 0)"""
        proc = self._processor(None)
        props = {
            "업체명": "테스트상점",
            "이름": "홍길동",
            "Name": "John",
            "내용": "상세 설명",
        }
        text = proc._extract_properties_text(props)

        # 기본 skip 키는 본문에서 제외되어야 함
        assert "업체명" not in text
        assert "[이름]" not in text
        assert "[Name]" not in text
        # skip 대상이 아닌 속성은 포함
        assert "내용" in text
        assert "상세 설명" in text

    def test_custom_skip_keys_applied(self) -> None:
        """config로 영어/타 언어 제목 속성명 지정 시 해당 키 제외(데드 키 해소)"""
        proc = self._processor(["Company", "Title"])
        props = {
            "Company": "ACME Inc",
            "Title": "Manager",
            "Detail": "some content",
            "업체명": "한국상점",  # 기본 집합이 아닌 custom 집합이 적용되므로 포함되어야 함
        }
        text = proc._extract_properties_text(props)

        # custom skip 키는 제외
        assert "[Company]" not in text
        assert "[Title]" not in text
        # custom 집합이 적용되면 기본 집합("업체명")은 더 이상 skip되지 않음
        assert "업체명" in text
        assert "[Detail]" in text

    def test_empty_list_falls_back_to_default(self) -> None:
        """빈 목록이면 기본 집합으로 폴백(회귀 0)"""
        proc = self._processor([])
        props = {"이름": "홍길동", "내용": "설명"}
        text = proc._extract_properties_text(props)
        assert "[이름]" not in text
        assert "내용" in text
