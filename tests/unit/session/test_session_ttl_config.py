from app.modules.core.session.facade import EnhancedSessionModule
from app.modules.core.session.services.memory_service import MemoryService
from app.modules.core.session.services.session_service import SessionService


def test_session_service_prefers_new_ttl_keys() -> None:
    service = SessionService(
        {
            "session": {
                "ttl_seconds": 1234,
                "ttl": 9999,
                "cleanup_interval_seconds": 77,
                "cleanup_interval": 88,
            }
        }
    )

    assert service.ttl == 1234
    assert service.cleanup_interval == 77


def test_session_service_keeps_legacy_key_fallback() -> None:
    service = SessionService(
        {
            "session": {
                "ttl": 999,
                "cleanup_interval": 111,
            }
        }
    )

    assert service.ttl == 999
    assert service.cleanup_interval == 111


def test_enhanced_session_module_passes_new_keys_to_facade_services() -> None:
    module = EnhancedSessionModule(
        {
            "session": {
                "ttl_seconds": 2222,
                "cleanup_interval_seconds": 333,
            }
        },
        memory_service=MemoryService(max_exchanges=2),
    )

    assert module.ttl == 2222
    assert module.admin_service.ttl == 2222
    assert module.cleanup_interval == 333
    assert module.cleanup_service.cleanup_interval == 333
