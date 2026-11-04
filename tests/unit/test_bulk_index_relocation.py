"""운영 코드가 scripts/ 패키지를 import 하지 않도록 인덱싱 로직이 app 안으로 이동했는지 검증."""

from __future__ import annotations

from pathlib import Path


def test_production_code_does_not_import_scripts_package() -> None:
    offenders = []
    for path in [Path("main.py"), *Path("app").rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        if "from scripts." in text or "import scripts" in text:
            offenders.append(str(path))
    assert offenders == []


def test_index_all_data_is_importable_from_app() -> None:
    from app.modules.ingestion.bulk_index import SAMPLE_ENTITIES, index_all_data

    assert callable(index_all_data)
    assert SAMPLE_ENTITIES
