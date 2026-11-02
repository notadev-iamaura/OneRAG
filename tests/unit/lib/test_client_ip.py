"""신뢰 프록시 정책 기반 클라이언트 IP 해석 테스트.

핵심 시나리오:
- peer가 신뢰 프록시가 아니면 X-Forwarded-For를 무시한다(스푸핑 차단)
- peer가 신뢰 프록시면 오른쪽부터 신뢰 프록시를 건너뛰고 첫 비신뢰 주소를 고른다
- 환경변수 문자열(private/none/*/목록)을 정책으로 올바르게 해석한다
"""

from __future__ import annotations

import pytest

from app.lib.client_ip import (
    TrustedProxyPolicy,
    get_trusted_proxy_policy,
    reset_trusted_proxy_policy_cache,
    resolve_client_ip,
)


class TestTrustedProxyPolicyParsing:
    def test_default_is_private_networks(self) -> None:
        policy = TrustedProxyPolicy.from_string(None)
        assert policy.source == "private"
        assert policy.is_trusted("127.0.0.1")
        assert policy.is_trusted("10.1.2.3")
        assert policy.is_trusted("172.16.5.5")
        assert policy.is_trusted("192.168.0.9")
        assert policy.is_trusted("::1")
        assert not policy.is_trusted("203.0.113.7")

    def test_none_trusts_nobody(self) -> None:
        policy = TrustedProxyPolicy.from_string("none")
        assert not policy.is_trusted("127.0.0.1")
        assert not policy.is_trusted("10.0.0.1")

    def test_star_trusts_everyone(self) -> None:
        policy = TrustedProxyPolicy.from_string("*")
        assert policy.trust_all
        assert policy.is_trusted("203.0.113.7")

    def test_explicit_list_with_cidr(self) -> None:
        policy = TrustedProxyPolicy.from_string("203.0.113.10, 10.0.0.0/8")
        assert policy.is_trusted("203.0.113.10")
        assert policy.is_trusted("10.9.8.7")
        assert not policy.is_trusted("203.0.113.11")
        assert not policy.is_trusted("127.0.0.1")

    def test_invalid_entries_fall_back_to_private(self) -> None:
        policy = TrustedProxyPolicy.from_string("not-an-ip, also-bad")
        assert policy.source == "private"

    def test_unparseable_peer_is_not_trusted(self) -> None:
        policy = TrustedProxyPolicy.private()
        assert not policy.is_trusted("testclient")
        assert not policy.is_trusted(None)

    def test_env_cache_reset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRUSTED_PROXY_IPS", "none")
        reset_trusted_proxy_policy_cache()
        assert get_trusted_proxy_policy().source == "none"
        monkeypatch.setenv("TRUSTED_PROXY_IPS", "*")
        # 캐시가 유지되므로 reset 전에는 바뀌지 않는다
        assert get_trusted_proxy_policy().source == "none"
        reset_trusted_proxy_policy_cache()
        assert get_trusted_proxy_policy().trust_all
        reset_trusted_proxy_policy_cache()


class TestResolveClientIp:
    def test_untrusted_peer_ignores_forwarded_headers(self) -> None:
        """공개 IP에서 직접 접속한 클라이언트가 헤더를 위조해도 peer IP가 쓰여야 한다."""
        policy = TrustedProxyPolicy.private()
        ip = resolve_client_ip(
            "203.0.113.7",
            {"X-Forwarded-For": "1.1.1.1", "X-Real-IP": "2.2.2.2"},
            policy,
        )
        assert ip == "203.0.113.7"

    def test_trusted_peer_uses_forwarded_for(self) -> None:
        policy = TrustedProxyPolicy.private()
        ip = resolve_client_ip("10.0.0.5", {"X-Forwarded-For": "198.51.100.20"}, policy)
        assert ip == "198.51.100.20"

    def test_skips_trusted_hops_from_the_right(self) -> None:
        """클라이언트가 왼쪽에 가짜 주소를 넣어도 프록시가 덧붙인 실제 주소를 고른다."""
        policy = TrustedProxyPolicy.private()
        ip = resolve_client_ip(
            "10.0.0.5",
            {"X-Forwarded-For": "9.9.9.9, 198.51.100.20, 10.0.0.9"},
            policy,
        )
        assert ip == "198.51.100.20"

    def test_all_hops_trusted_uses_leftmost(self) -> None:
        policy = TrustedProxyPolicy.private()
        ip = resolve_client_ip("10.0.0.5", {"X-Forwarded-For": "192.168.1.2, 10.0.0.9"}, policy)
        assert ip == "192.168.1.2"

    def test_trusted_peer_falls_back_to_real_ip(self) -> None:
        policy = TrustedProxyPolicy.private()
        ip = resolve_client_ip("127.0.0.1", {"X-Real-IP": "198.51.100.30"}, policy)
        assert ip == "198.51.100.30"

    def test_trusted_peer_without_headers_uses_peer(self) -> None:
        policy = TrustedProxyPolicy.private()
        assert resolve_client_ip("127.0.0.1", {}, policy) == "127.0.0.1"

    def test_none_policy_always_uses_peer(self) -> None:
        policy = TrustedProxyPolicy.none()
        ip = resolve_client_ip("127.0.0.1", {"X-Forwarded-For": "198.51.100.20"}, policy)
        assert ip == "127.0.0.1"

    def test_trust_all_uses_leftmost_like_legacy(self) -> None:
        policy = TrustedProxyPolicy.all()
        ip = resolve_client_ip(
            "203.0.113.7", {"X-Forwarded-For": "1.1.1.1, 2.2.2.2"}, policy
        )
        assert ip == "1.1.1.1"

    def test_ipv4_mapped_ipv6_is_normalized(self) -> None:
        policy = TrustedProxyPolicy.private()
        ip = resolve_client_ip("::1", {"X-Forwarded-For": "::ffff:198.51.100.20"}, policy)
        assert ip == "198.51.100.20"

    def test_no_peer_no_headers(self) -> None:
        assert resolve_client_ip(None, {}, TrustedProxyPolicy.private()) is None

    def test_header_lookup_is_case_insensitive_for_plain_dicts(self) -> None:
        policy = TrustedProxyPolicy.private()
        ip = resolve_client_ip("10.0.0.1", {"x-forwarded-for": "198.51.100.40"}, policy)
        assert ip == "198.51.100.40"
