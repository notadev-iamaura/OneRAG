from types import SimpleNamespace

from app.api.upload import estimate_processing_time, validate_file


def test_validate_file_accepts_pptx_mime_type() -> None:
    file = SimpleNamespace(
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename="deck.pptx",
        size=1024,
    )

    result = validate_file(file)

    assert result["valid"] is True
    assert result["file_type"] == "pptx"


def test_validate_file_accepts_pptx_extension_fallback() -> None:
    file = SimpleNamespace(
        content_type="application/octet-stream",
        filename="deck.pptx",
        size=1024,
    )

    result = validate_file(file)

    assert result["valid"] is True
    assert result["file_type"] == "pptx"


def test_estimate_processing_time_has_pptx_rate() -> None:
    assert estimate_processing_time(file_size=1024 * 1024, file_type="pptx") == 32.0
