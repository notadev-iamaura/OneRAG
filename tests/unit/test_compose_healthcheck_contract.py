from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load_compose(name: str) -> dict:
    with (ROOT / name).open() as f:
        return yaml.safe_load(f)


def test_dev_compose_api_healthcheck_targets_readiness() -> None:
    compose = _load_compose("docker-compose.yml")

    assert "http://localhost:8000/ready" in compose["services"]["api"]["healthcheck"]["test"]


def test_prod_compose_api_healthcheck_targets_readiness() -> None:
    compose = _load_compose("docker-compose.prod.yml")

    assert "http://localhost:8000/ready" in compose["services"]["api"]["healthcheck"]["test"]


def test_fullstack_frontend_healthcheck_uses_nginx_health_endpoint() -> None:
    compose = _load_compose("docker-compose.yml")

    assert "http://127.0.0.1:80/health" in compose["services"]["frontend"]["healthcheck"]["test"]


def test_frontend_nginx_exposes_health_endpoint() -> None:
    nginx_conf = (ROOT / "frontend" / "nginx.conf").read_text()

    assert "location /health" in nginx_conf
    assert 'return 200 "healthy\\n";' in nginx_conf


def test_runtime_entrypoint_scripts_have_shell_syntax() -> None:
    assert (ROOT / "docker-entrypoint.sh").exists()
    assert (ROOT / "frontend" / "entrypoint.sh").exists()


def test_main_rate_limit_middleware_exempts_readiness() -> None:
    from main import app

    rate_limit_middlewares = [
        middleware
        for middleware in app.user_middleware
        if middleware.cls.__name__ == "RateLimitMiddleware"
    ]

    assert rate_limit_middlewares
    assert "/ready" in rate_limit_middlewares[0].options["excluded_paths"]
