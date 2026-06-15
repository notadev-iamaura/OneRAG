"""브라우저용 단기 업로드 토큰(#22) 단위 테스트.

검증 대상:
    - 세션+scope 바인딩 토큰 생성/검증 라운드트립
    - 만료/위변조/scope·session 불일치 거부
    - TTL 클램프(기본/최대/잘못된 값)
"""

from __future__ import annotations

import pytest

from app.lib.auth import (
    DEFAULT_UPLOAD_TOKEN_TTL_SECONDS,
    MAX_UPLOAD_TOKEN_TTL_SECONDS,
    create_upload_access_token,
    get_upload_token_ttl_seconds,
    verify_upload_access_token,
)

_SECRET = "test-secret-key"
_SESSION = "session-abc"
_SCOPE = "upload"


def test_create_and_verify_round_trip() -> None:
    """발급한 토큰은 같은 session/scope/secret으로 검증되어야 한다."""
    token = create_upload_access_token(_SESSION, _SECRET, ttl_seconds=900, now=1000)
    assert verify_upload_access_token(_SESSION, token, _SECRET, now=1001) is True


def test_expired_token_rejected() -> None:
    """만료 시각 이후에는 거부되어야 한다."""
    token = create_upload_access_token(_SESSION, _SECRET, ttl_seconds=10, now=1000)
    assert verify_upload_access_token(_SESSION, token, _SECRET, now=1011) is False


def test_session_mismatch_rejected() -> None:
    """다른 session_id로는 검증되지 않아야 한다."""
    token = create_upload_access_token(_SESSION, _SECRET, ttl_seconds=900, now=1000)
    assert verify_upload_access_token("other-session", token, _SECRET, now=1001) is False


def test_tampered_token_rejected() -> None:
    """서명이 위변조된 토큰은 거부되어야 한다."""
    token = create_upload_access_token(_SESSION, _SECRET, ttl_seconds=900, now=1000)
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    assert verify_upload_access_token(_SESSION, tampered, _SECRET, now=1001) is False


def test_wrong_secret_rejected() -> None:
    """다른 secret으로 발급한 토큰은 거부되어야 한다."""
    token = create_upload_access_token(_SESSION, "secret-a", ttl_seconds=900, now=1000)
    assert verify_upload_access_token(_SESSION, token, "secret-b", now=1001) is False


def test_none_and_malformed_tokens_rejected() -> None:
    """None/형식 오류 토큰은 거부되어야 한다."""
    assert verify_upload_access_token(_SESSION, None, _SECRET) is False
    assert verify_upload_access_token(_SESSION, "garbage", _SECRET) is False
    assert verify_upload_access_token(_SESSION, "v1.notanumber.x.y", _SECRET) is False


def test_ttl_clamping(monkeypatch: pytest.MonkeyPatch) -> None:
    """TTL 환경변수는 기본/최대 범위로 클램프되어야 한다."""
    monkeypatch.delenv("ONERAG_UPLOAD_TOKEN_TTL_SECONDS", raising=False)
    assert get_upload_token_ttl_seconds() == DEFAULT_UPLOAD_TOKEN_TTL_SECONDS

    monkeypatch.setenv("ONERAG_UPLOAD_TOKEN_TTL_SECONDS", "0")
    assert get_upload_token_ttl_seconds() == DEFAULT_UPLOAD_TOKEN_TTL_SECONDS

    monkeypatch.setenv("ONERAG_UPLOAD_TOKEN_TTL_SECONDS", "not-int")
    assert get_upload_token_ttl_seconds() == DEFAULT_UPLOAD_TOKEN_TTL_SECONDS

    monkeypatch.setenv("ONERAG_UPLOAD_TOKEN_TTL_SECONDS", str(MAX_UPLOAD_TOKEN_TTL_SECONDS + 100))
    assert get_upload_token_ttl_seconds() == MAX_UPLOAD_TOKEN_TTL_SECONDS

    monkeypatch.setenv("ONERAG_UPLOAD_TOKEN_TTL_SECONDS", "1800")
    assert get_upload_token_ttl_seconds() == 1800
