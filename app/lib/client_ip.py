"""
클라이언트 IP 해석 모듈 (신뢰 프록시 정책 기반)

왜 필요한가:
    X-Forwarded-For / X-Real-IP 헤더는 누구나 임의로 붙여 보낼 수 있다. 이 헤더를
    무조건 믿으면 공격자가 요청마다 헤더 값을 바꿔 IP 기반 레이트리밋을 우회할 수 있다
    (LLM 호출 비용 공격). 따라서 "직접 연결된 상대(peer)가 신뢰하는 프록시일 때만"
    헤더를 읽고, 그렇지 않으면 소켓에서 본 peer IP를 그대로 쓴다.

정책(TRUSTED_PROXY_IPS 환경변수):
    - 미설정/빈 값 : 기본 정책 "private" (loopback + 사설망 + 링크로컬). Docker/K8s/
                    Railway/Cloud Run처럼 리버스 프록시가 내부망에서 붙는 일반 배포에 맞다.
    - "none"       : 어떤 프록시도 신뢰하지 않음(헤더 무시, 항상 peer IP).
    - "*"          : 모든 peer를 신뢰(예전 동작, 스푸핑 가능 — 권장하지 않음).
    - "1.2.3.4,10.0.0.0/8" : 콤마 구분 IP/CIDR 목록.

X-Forwarded-For 해석:
    값은 "client, proxy1, proxy2" 순서로 프록시가 뒤에 덧붙인다. 오른쪽부터 신뢰
    프록시를 건너뛰고 처음 만나는 비신뢰 주소를 클라이언트로 본다. 이렇게 하면
    클라이언트가 가짜 주소를 왼쪽에 넣어도 무시된다.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from .logger import get_logger

logger = get_logger(__name__)

TRUSTED_PROXY_ENV = "TRUSTED_PROXY_IPS"

# "private" 기본 정책에 포함되는 네트워크.
_PRIVATE_NETWORKS: tuple[str, ...] = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "fc00::/7",
    "fe80::/10",
)

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True)
class TrustedProxyPolicy:
    """어떤 peer 주소를 프록시로 신뢰할지 정의한다."""

    networks: tuple[IPNetwork, ...] = field(default_factory=tuple)
    trust_all: bool = False
    source: str = "private"

    def is_trusted(self, host: str | None) -> bool:
        """peer 호스트가 신뢰 프록시인지 판단한다. 파싱 불가 주소는 신뢰하지 않는다."""
        if self.trust_all:
            return True
        if not host:
            return False
        address = _parse_ip(host)
        if address is None:
            return False
        return any(address in network for network in self.networks)

    @classmethod
    def private(cls) -> TrustedProxyPolicy:
        """loopback + 사설망 + 링크로컬을 신뢰하는 기본 정책."""
        return cls(
            networks=tuple(ipaddress.ip_network(cidr) for cidr in _PRIVATE_NETWORKS),
            source="private",
        )

    @classmethod
    def none(cls) -> TrustedProxyPolicy:
        """어떤 프록시도 신뢰하지 않는 정책."""
        return cls(networks=(), source="none")

    @classmethod
    def all(cls) -> TrustedProxyPolicy:
        """모든 peer를 신뢰하는 정책(스푸핑 가능 — 레거시 호환 전용)."""
        return cls(trust_all=True, source="*")

    @classmethod
    def from_string(cls, raw: str | None) -> TrustedProxyPolicy:
        """환경변수 문자열을 정책으로 변환한다. 잘못된 항목은 경고 후 건너뛴다."""
        value = (raw or "").strip()
        if not value or value.lower() == "private":
            return cls.private()
        if value.lower() == "none":
            return cls.none()
        if value == "*":
            logger.warning(
                "TRUSTED_PROXY_IPS='*' — 모든 peer의 X-Forwarded-For를 신뢰합니다. "
                "레이트리밋 우회가 가능하므로 프록시 IP/CIDR 목록으로 제한하세요."
            )
            return cls.all()

        networks: list[IPNetwork] = []
        for item in value.split(","):
            entry = item.strip()
            if not entry:
                continue
            try:
                networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                logger.warning(
                    "TRUSTED_PROXY_IPS 항목 파싱 실패 — 무시",
                    extra={"entry": entry},
                )
        if not networks:
            logger.warning("TRUSTED_PROXY_IPS에 유효한 항목이 없어 기본 정책(private)을 사용합니다")
            return cls.private()
        return cls(networks=tuple(networks), source=value)

    @classmethod
    def from_env(cls) -> TrustedProxyPolicy:
        """TRUSTED_PROXY_IPS 환경변수에서 정책을 읽는다."""
        return cls.from_string(os.getenv(TRUSTED_PROXY_ENV))


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """문자열을 IP 주소로 파싱한다. IPv6 zone id, IPv4-mapped IPv6를 정규화한다."""
    candidate = host.strip()
    if not candidate:
        return None
    # "[::1]" 형태 괄호 제거
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    # IPv6 zone id(fe80::1%eth0) 제거
    candidate = candidate.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """대소문자 무관 헤더 조회(Starlette Headers는 자체 처리, dict는 수동 탐색)."""
    value = headers.get(name)
    if value is not None:
        return value
    lowered = name.lower()
    for key, candidate in headers.items():
        if key.lower() == lowered:
            return candidate
    return None


def resolve_client_ip(
    peer_host: str | None,
    headers: Mapping[str, str],
    policy: TrustedProxyPolicy,
) -> str | None:
    """레이트리밋 등에 쓸 클라이언트 IP를 결정한다.

    Args:
        peer_host: 소켓이 보고한 직접 연결 상대 주소(request.client.host).
        headers: 요청 헤더.
        policy: 신뢰 프록시 정책.

    Returns:
        클라이언트 IP 문자열. peer도 헤더도 없으면 None.
    """
    if not policy.is_trusted(peer_host):
        # peer가 신뢰 프록시가 아니면 헤더는 전부 무시한다(스푸핑 방지).
        return peer_host.strip() if peer_host else None

    forwarded_for = _header(headers, "X-Forwarded-For")
    if forwarded_for:
        hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
        if hops:
            if policy.trust_all:
                # 레거시 정책: 가장 왼쪽(원 클라이언트 주장값)을 그대로 사용한다.
                return _normalize_hop(hops[0])
            # 오른쪽(가장 가까운 프록시)부터 신뢰 프록시를 건너뛴다.
            for hop in reversed(hops):
                if not policy.is_trusted(hop):
                    return _normalize_hop(hop)
            # 전부 신뢰 프록시였다면 가장 왼쪽 값을 사용한다.
            return _normalize_hop(hops[0])

    real_ip = _header(headers, "X-Real-IP")
    if real_ip and real_ip.strip():
        return _normalize_hop(real_ip)

    return peer_host.strip() if peer_host else None


def _normalize_hop(hop: str) -> str:
    """파싱 가능한 주소는 정규화된 문자열로, 아니면 공백만 제거해 돌려준다."""
    parsed = _parse_ip(hop)
    return str(parsed) if parsed is not None else hop.strip()


_policy_cache: TrustedProxyPolicy | None = None


def get_trusted_proxy_policy() -> TrustedProxyPolicy:
    """환경변수 기반 정책을 한 번만 읽어 재사용한다."""
    global _policy_cache
    if _policy_cache is None:
        _policy_cache = TrustedProxyPolicy.from_env()
        logger.info(
            "신뢰 프록시 정책 로드",
            extra={"source": _policy_cache.source, "trust_all": _policy_cache.trust_all},
        )
        if _policy_cache.source == "private":
            # 기본 정책은 사설망 peer 를 전부 프록시로 본다. 프록시 없이 LAN/VPN 에 직접 노출하면
            # 같은 망의 클라이언트가 X-Forwarded-For 를 위조할 수 있으므로 명시 설정을 권한다.
            logger.warning(
                "TRUSTED_PROXY_IPS 미설정(기본 private). 리버스 프록시가 없는 직접 노출 환경이면 "
                "TRUSTED_PROXY_IPS=none, 프록시가 있으면 그 IP/CIDR 로 명시하세요."
            )
    return _policy_cache


def reset_trusted_proxy_policy_cache() -> None:
    """테스트용: 캐시된 정책을 비워 환경변수를 다시 읽게 한다."""
    global _policy_cache
    _policy_cache = None
